"""
buscador.py — Orquestração da busca de provedores de internet.

Responsabilidades:
  1. Geocodificação de endereços → coordenadas (lat, lng)
  2. Coordenação das buscas por termo e por página
  3. Deduplicação, cálculo de distância e filtro de raio
  4. Cache de Place Details e segurança da chave nas mensagens de log

O diálogo com a Places API fica em clientes.py, que abriga uma implementação
para cada geração da API (nova e legada). Este módulo não sabe com qual delas
está falando: recebe registros já normalizados e trata todos igual.

Segurança: a chave de API nunca é incluída em mensagens de log. Um filtro
(_FiltroChaveAPI) é instalado nos handlers do logger raiz ao instanciar
BuscadorProvedores, mascarando a chave em qualquer log acidental — inclusive
nos emitidos por bibliotecas de terceiros, como requests/urllib3.

Ciclo de vida: use o buscador como context manager sempre que possível.

    with BuscadorProvedores(api_key=chave) as buscador:
        lat, lng = buscador.geocodificar("Itajaí, SC")
        provedores = buscador.buscar_todos(lat, lng, raio=5000)

Ao sair do bloco, o cache pendente é gravado, a sessão HTTP é fechada e o
filtro de log é removido. Sem isso, processos de vida longa (servidor web,
GUI) acumulam um filtro por instância criada.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests

from cache import carregar_cache, salvar_cache
from clientes import ErroAPI, criar_cliente, mesclar
from config import (
    CACHE_VALIDADE_DIAS,
    CAMINHO_CACHE,
    INTERVALO_ENTRE_CHAMADAS,
    INTERVALO_GRAVACAO_CACHE,
    MAX_PAGINAS,
    RAIO_ESTRITO,
    TERMOS_DE_BUSCA,
    URL_GEOCODING,
    USAR_PLACES_NOVA,
)
from geo import distancia_km

logger = logging.getLogger(__name__)

# ErroAPI é definido em clientes.py, mas continua exportado aqui: é a partir
# deste módulo que service.py e os testes o importam.
__all__ = ["BuscadorProvedores", "ErroAPI", "ErroLocalizacao"]


# ---------------------------------------------------------------------------
# Exceções públicas
# ---------------------------------------------------------------------------

class ErroLocalizacao(Exception):
    """Levantado quando o endereço não pode ser geocodificado."""


# ---------------------------------------------------------------------------
# Filtro de segurança para logs
# ---------------------------------------------------------------------------

class _FiltroChaveAPI(logging.Filter):
    """
    Mascara a chave de API em qualquer mensagem de log.

    Substitui ocorrências literais da chave pelo marcador '***API_KEY***',
    evitando que a chave vaze em arquivos de log ou saída de debug.

    Só valores de texto são tocados. Números são devolvidos intactos: convertê-los
    para str quebraria a formatação preguiçosa do logging — um argumento inteiro
    virado string faz `"%d" % ("20",)` levantar TypeError.
    """

    _MASCARA = "***API_KEY***"

    def __init__(self, chave: str) -> None:
        super().__init__()
        self._chave = chave

    def filter(self, record: logging.LogRecord) -> bool:
        if self._chave:
            record.msg = self._mascarar(record.msg)
            record.args = self._mascarar_args(record.args)
        return True

    def _mascarar(self, valor):
        """Mascara a chave se o valor for texto; qualquer outro tipo passa intacto."""
        if isinstance(valor, str):
            return valor.replace(self._chave, self._MASCARA)
        return valor

    def _mascarar_args(self, args):
        """Percorre os argumentos de formatação do log e mascara a chave."""
        if args is None:
            return args
        if isinstance(args, dict):
            return {chave: self._mascarar(valor) for chave, valor in args.items()}
        return tuple(self._mascarar(arg) for arg in args)


def _instalar_filtro_chave(filtro: logging.Filter) -> list:
    """
    Instala o filtro de mascaramento nos handlers do logger raiz.

    Detalhe crítico do módulo logging: um filtro adicionado a um *Logger* só é
    aplicado aos registros emitidos naquele logger — não aos que chegam a ele por
    propagação dos loggers filhos. Como todo módulo deste projeto usa
    `getLogger(__name__)`, um filtro instalado apenas no logger raiz nunca veria
    essas mensagens, e a chave passaria sem máscara. Filtros de *Handler*, ao
    contrário, são aplicados a tudo que chega ao handler, venha de onde vier.

    Por isso instalamos nos handlers do raiz — e também no logger raiz em si,
    para cobrir chamadas diretas a logging.info() e afins.

    Limitação conhecida: handlers criados *depois* desta chamada não recebem o
    filtro. Configure o logging antes de instanciar BuscadorProvedores.

    Args:
        filtro: Instância de _FiltroChaveAPI a ser instalada.

    Returns:
        Lista dos objetos onde o filtro foi instalado, para remoção em fechar().
    """
    raiz = logging.getLogger()
    alvos: list = [raiz, *raiz.handlers]
    for alvo in alvos:
        alvo.addFilter(filtro)
    return alvos


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class BuscadorProvedores:
    """
    Realiza buscas de provedores de internet via Google Places API.

    Uso básico:
        with BuscadorProvedores(api_key="SUA_CHAVE") as buscador:
            lat, lng = buscador.geocodificar("Florianópolis, SC")
            provedores = buscador.buscar_todos(lat, lng, raio=8000)
    """

    def __init__(
        self,
        api_key: str,
        caminho_cache: str = CAMINHO_CACHE,
        usar_nova: Optional[bool] = None,
    ) -> None:
        """
        Args:
            api_key: Chave da Google Maps API.
            caminho_cache: Caminho do arquivo de cache de Place Details.
            usar_nova: True para Places API (New), False para a legada.
                Quando None, usa config.USAR_PLACES_NOVA.
        """
        if not api_key:
            raise ValueError("A chave de API do Google Maps não pode ser vazia.")

        self.api_key = api_key
        self._sessao = requests.Session()
        self._sessao.headers.update({"Accept": "application/json"})

        # O cliente encapsula as diferenças entre as duas gerações da Places API
        self._cliente = criar_cliente(
            api_key=api_key,
            sessao=self._sessao,
            usar_nova=USAR_PLACES_NOVA if usar_nova is None else usar_nova,
        )
        logger.debug("Usando a Places API: %s", self._cliente.nome)

        # Carrega o cache de Place Details do disco
        self._caminho_cache = caminho_cache
        self._cache: dict = carregar_cache(caminho_cache)

        # Instrumentação da última busca, preenchida por buscar_todos.
        # Sai de graça: são os mesmos resultados que a busca já percorre, e
        # permitem medir a sobreposição entre os termos sem nenhuma
        # requisição extra à API. Ver analise_termos.py.
        self.ids_por_termo: dict[str, set[str]] = {}
        self.requisicoes_por_termo: dict[str, int] = {}

        # Marcado quando uma busca é interrompida a pedido de quem chamou.
        # O resultado parcial continua válido — apenas incompleto.
        self.cancelado: bool = False

        # Entradas adicionadas ao cache desde a última gravação em disco.
        # Gravar a cada nova entrada reescreveria o arquivo JSON inteiro a cada
        # place_id — custo O(n²) em buscas grandes.
        self._entradas_nao_gravadas: int = 0

        # Instala o filtro de segurança para mascarar a chave em qualquer
        # mensagem de log emitida enquanto este objeto existir
        self._filtro_log = _FiltroChaveAPI(api_key)
        self._alvos_filtro = _instalar_filtro_chave(self._filtro_log)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def gravar_cache(self) -> None:
        """
        Persiste em disco as entradas de cache ainda não gravadas.

        Não faz nada se não houver pendências, evitando escrita desnecessária.
        """
        if self._entradas_nao_gravadas == 0:
            return
        salvar_cache(self._cache, self._caminho_cache)
        self._entradas_nao_gravadas = 0

    def fechar(self) -> None:
        """
        Libera os recursos do buscador.

        Grava o cache pendente, fecha a sessão HTTP e — importante — remove o
        filtro de log dos alvos onde foi instalado. Sem essa remoção, cada
        instância criada deixa um filtro pendurado no logging global: num
        servidor web que instancia o buscador por requisição, eles se acumulam
        indefinidamente e cada mensagem de log passa por todos eles.

        Seguro chamar mais de uma vez.
        """
        self.gravar_cache()

        for alvo in self._alvos_filtro:
            alvo.removeFilter(self._filtro_log)
        self._alvos_filtro = []

        self._sessao.close()

    def __enter__(self) -> "BuscadorProvedores":
        return self

    def __exit__(self, exc_type, exc_valor, traceback) -> bool:
        self.fechar()
        return False  # não suprime exceções

    # ------------------------------------------------------------------
    # Geocodificação
    # ------------------------------------------------------------------

    def geocodificar(self, endereco: str) -> tuple[float, float]:
        """
        Converte um endereço textual em coordenadas geográficas (lat, lng).

        Usa a Geocoding API, que é comum às duas gerações da Places API e não
        foi afetada pela migração.

        Args:
            endereco: Endereço completo ou parcial em texto livre.

        Returns:
            Tupla (latitude, longitude) em graus decimais.

        Raises:
            ErroLocalizacao: Se o endereço não for encontrado.
            ConnectionError: Se houver falha de rede.
            ErroAPI: Para outros erros retornados pela API.
        """
        logger.debug("Geocodificando: %s", endereco)
        params = {"address": endereco, "key": self.api_key}

        try:
            resposta = self._sessao.get(URL_GEOCODING, params=params, timeout=10)
            resposta.raise_for_status()
        except requests.ConnectionError as exc:
            raise ConnectionError(
                f"Sem conexão com a internet ao geocodificar '{endereco}'."
            ) from exc
        except requests.Timeout as exc:
            raise ConnectionError(
                f"Tempo esgotado ao geocodificar '{endereco}'. Tente novamente."
            ) from exc
        except requests.HTTPError as exc:
            raise ErroAPI(
                f"Erro HTTP {resposta.status_code} na geocodificação."
            ) from exc

        dados = resposta.json()
        status = dados.get("status")

        if status == "ZERO_RESULTS":
            raise ErroLocalizacao(
                f"Endereço não encontrado: '{endereco}'. "
                "Tente fornecer mais detalhes (cidade, estado, CEP)."
            )
        if status == "REQUEST_DENIED":
            raise ErroAPI(
                "Chave de API inválida ou sem permissão para a Geocoding API. "
                "Verifique sua chave no Google Cloud Console."
            )
        if status != "OK":
            raise ErroAPI(f"Geocoding API retornou status inesperado: {status}")

        localizacao = dados["results"][0]["geometry"]["location"]
        lat, lng = localizacao["lat"], localizacao["lng"]
        logger.debug("Coordenadas obtidas: lat=%.6f, lng=%.6f", lat, lng)
        return lat, lng

    # ------------------------------------------------------------------
    # Detalhes de um lugar (com cache)
    # ------------------------------------------------------------------

    def obter_detalhes(self, place_id: str) -> dict:
        """
        Obtém informações detalhadas de um estabelecimento pelo place_id.

        Consulta o cache local antes de chamar a API. Se o place_id já
        estiver em cache, retorna o valor salvo sem nenhuma chamada de rede.

        Com a Places API (New) esta chamada não é usada durante a busca — o
        field mask já traz telefone, site e avaliação nos próprios resultados.
        O método permanece público para consultas pontuais e para atualizar um
        registro específico.

        Returns:
            Registro normalizado parcial, ou {} em caso de erro.
        """
        # A chave do cache inclui a geração da API: os registros das duas têm
        # origens diferentes e um cache antigo não deve ser lido como novo.
        chave_cache = f"{self._cliente.nome}:{place_id}"

        # --- Consulta o cache ---
        do_cache = self._ler_do_cache(chave_cache)
        if do_cache is not None:
            logger.debug("Cache hit para place_id '%s'.", place_id)
            return do_cache

        # --- Chama a API ---
        # A pausa de rate limit vive aqui, e não no laço de buscar_todos, para
        # não penalizar os acertos de cache: dormir antes de uma leitura que
        # nunca toca a rede anula justamente o ganho que o cache existe para dar.
        time.sleep(INTERVALO_ENTRE_CHAMADAS)

        try:
            resultado = self._cliente.obter_detalhes(place_id)
        except (ConnectionError, ErroAPI) as exc:
            logger.warning("Falha ao obter detalhes de '%s': %s", place_id, exc)
            return {}

        if not resultado:
            return {}

        # --- Salva no cache ---
        # A gravação em disco é feita em lote (ver gravar_cache) para não
        # reescrever o arquivo inteiro a cada place_id consultado.
        self._cache[chave_cache] = {
            "salvo_em": datetime.now(timezone.utc).isoformat(),
            "dados": resultado,
        }
        self._entradas_nao_gravadas += 1
        if self._entradas_nao_gravadas >= INTERVALO_GRAVACAO_CACHE:
            self.gravar_cache()

        return resultado

    def _ler_do_cache(self, chave: str):
        """
        Devolve a entrada do cache se existir e ainda estiver válida.

        As políticas da Places API isentam apenas o place_id das restrições de
        cache; o restante do conteúdo não pode ser retido sem prazo. Entradas
        vencidas são removidas na leitura e reconsultadas na API.

        Entradas gravadas por versões anteriores não têm o carimbo "salvo_em" —
        como não há como saber a idade delas, são tratadas como vencidas.

        Returns:
            Os dados do cache, ou None se ausente, vencido ou em formato antigo.
        """
        entrada = self._cache.get(chave)
        if not isinstance(entrada, dict) or "salvo_em" not in entrada:
            if entrada is not None:
                logger.debug("Entrada de cache '%s' em formato antigo. Ignorando.", chave)
                self._cache.pop(chave, None)
            return None

        try:
            salvo_em = datetime.fromisoformat(entrada["salvo_em"])
        except (TypeError, ValueError):
            self._cache.pop(chave, None)
            return None

        if datetime.now(timezone.utc) - salvo_em > timedelta(days=CACHE_VALIDADE_DIAS):
            logger.debug("Entrada de cache '%s' vencida. Reconsultando.", chave)
            self._cache.pop(chave, None)
            return None

        return entrada["dados"]

    # ------------------------------------------------------------------
    # Orquestrador principal
    # ------------------------------------------------------------------

    def buscar_todos(
        self,
        lat: float,
        lng: float,
        raio: int,
        callback_progresso: Optional[Callable[[dict], None]] = None,
        deve_cancelar: Optional[Callable[[], bool]] = None,
    ) -> list[dict]:
        """
        Busca provedores de internet usando todos os termos configurados.

        Deduplicação automática por place_id garante que cada empresa
        apareça apenas uma vez no resultado final.

        Args:
            lat: Latitude do ponto central da busca.
            lng: Longitude do ponto central da busca.
            raio: Raio de busca em metros.
            callback_progresso: Função opcional chamada a cada atualização.
                Recebe um dict com as chaves:
                    "etapa"            (int)  — índice do termo atual (1-based)
                    "total_etapas"     (int)  — total de termos de busca
                    "mensagem"         (str)  — descrição legível do evento
                    "novos_provedores" (int | None) — novos encontrados neste
                        termo; None durante a busca, int após a conclusão
                    "total_acumulado"  (int)  — total geral até o momento
                    "erro"             (str | None) — mensagem da falha, quando
                        a busca daquele termo não pôde ser concluída
            deve_cancelar: Consultada entre termos e entre páginas. Quando
                devolve True, a busca para e retorna o que já foi coletado —
                o atributo `cancelado` fica marcado. Serve para interfaces em
                que o usuário pode desistir no meio, evitando gastar cota à toa.

        Returns:
            Lista de dicts com os campos padronizados definidos em COLUNAS_SAIDA,
            incluindo latitude, longitude e distancia_km em relação ao centro.
        """
        notificar = callback_progresso or (lambda _: None)
        total_etapas = len(TERMOS_DE_BUSCA)
        ids_vistos: set[str] = set()
        provedores: list[dict] = []
        raio_km = raio / 1000

        self.ids_por_termo = {}
        self.requisicoes_por_termo = {}
        self.cancelado = False
        parar = deve_cancelar or (lambda: False)

        for i, termo in enumerate(TERMOS_DE_BUSCA, start=1):
            if parar():
                self.cancelado = True
                logger.debug("Busca cancelada antes do termo '%s'.", termo)
                break

            # Notifica o início da etapa (novos_provedores=None = ainda buscando)
            notificar({
                "etapa": i,
                "total_etapas": total_etapas,
                "mensagem": f'Buscando por: "{termo}"...',
                "novos_provedores": None,
                "total_acumulado": len(provedores),
                "erro": None,
            })

            try:
                registros = self.buscar_por_termo(termo, lat, lng, raio, parar)
            except (ConnectionError, ErroAPI) as exc:
                notificar({
                    "etapa": i,
                    "total_etapas": total_etapas,
                    "mensagem": f'Aviso ao buscar "{termo}": {exc}',
                    "novos_provedores": 0,
                    "total_acumulado": len(provedores),
                    # A interface precisa distinguir "nada encontrado" de
                    # "a busca falhou" — sem isso, um erro de API vira um
                    # silencioso "nenhum resultado" e o conselho ao usuário
                    # ("aumente o raio") passa a ser enganoso.
                    "erro": str(exc),
                })
                continue

            novos = 0
            ids_do_termo: set[str] = set()

            for registro in registros:
                place_id = registro.get("place_id")
                if not place_id:
                    continue

                # O raio da Places API é um viés de relevância, não um filtro —
                # a API devolve resultados bem além dele. Descartamos aqui, ANTES
                # de gastar uma eventual chamada de Place Details.
                distancia = self._distancia_do_centro(registro, lat, lng)
                if RAIO_ESTRITO and distancia is not None and distancia > raio_km:
                    logger.debug(
                        "Descartado '%s': %.2f km do centro (raio de %.2f km).",
                        registro.get("nome", place_id), distancia, raio_km,
                    )
                    continue

                # Registra antes da deduplicação: para medir sobreposição é
                # preciso saber tudo que o termo trouxe, e não apenas o que
                # sobrou depois dos termos anteriores. O contador de novos é
                # dependente da ordem; este conjunto não é.
                ids_do_termo.add(place_id)

                if place_id in ids_vistos:
                    continue
                ids_vistos.add(place_id)

                registro["distancia_km"] = distancia if distancia is not None else ""

                # Só a API legada precisa de uma chamada extra por estabelecimento:
                # a busca dela não devolve telefone nem site.
                if self._cliente.requer_detalhes:
                    registro = mesclar(registro, self.obter_detalhes(place_id))

                provedores.append(registro)
                novos += 1

            self.ids_por_termo[termo] = ids_do_termo

            # Notifica o resultado da etapa com o número de novos encontrados
            notificar({
                "etapa": i,
                "total_etapas": total_etapas,
                "mensagem": f'Busca por "{termo}" concluída.',
                "novos_provedores": novos,
                "total_acumulado": len(provedores),
                "erro": None,
            })

        # Garante que nenhuma entrada de cache obtida nesta busca se perca,
        # mesmo que o total não tenha atingido INTERVALO_GRAVACAO_CACHE.
        self.gravar_cache()

        return provedores

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def buscar_por_termo(
        self,
        termo: str,
        lat: float,
        lng: float,
        raio: int,
        deve_cancelar: Optional[Callable[[], bool]] = None,
    ) -> list[dict]:
        """
        Busca um termo percorrendo todas as páginas disponíveis.

        Registra em requisicoes_por_termo quantas requisições foram gastas, o
        que permite estimar a economia de cortar um termo redundante.

        Returns:
            Lista de registros normalizados, ainda sem distância nem deduplicação.
        """
        registros: list[dict] = []
        token: Optional[str] = None
        paginas_lidas = 0

        for pagina in range(1, MAX_PAGINAS + 1):
            if deve_cancelar and deve_cancelar():
                self.cancelado = True
                break

            # A API legada exige um atraso antes de usar o token da próxima
            # página; a nova aceita de imediato e declara intervalo zero.
            if token and self._cliente.intervalo_paginacao:
                logger.debug(
                    "Aguardando %.1fs para próxima página...",
                    self._cliente.intervalo_paginacao,
                )
                time.sleep(self._cliente.intervalo_paginacao)

            da_pagina, token = self._cliente.buscar_pagina(termo, lat, lng, raio, token)
            paginas_lidas += 1
            self.requisicoes_por_termo[termo] = paginas_lidas
            registros.extend(da_pagina)
            logger.debug(
                "Página %d: %d resultado(s) para '%s'.", pagina, len(da_pagina), termo
            )

            if not token:
                break

        return registros

    @staticmethod
    def _distancia_do_centro(
        registro: dict, lat_centro: float, lng_centro: float
    ) -> float | None:
        """
        Distância em km entre o centro da busca e o estabelecimento.

        Returns:
            Distância em km, ou None se o registro não trouxer coordenadas.
        """
        lat, lng = registro.get("latitude"), registro.get("longitude")
        if lat in ("", None) or lng in ("", None):
            return None
        return distancia_km(lat_centro, lng_centro, lat, lng)
