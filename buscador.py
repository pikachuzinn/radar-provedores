"""
buscador.py — Módulo principal de busca de provedores de internet.

Encapsula todas as chamadas à Google Places API:
  1. Geocodificação de endereços → coordenadas (lat, lng)
  2. Text Search para encontrar provedores próximos
  3. Place Details para enriquecer cada resultado com telefone, site, etc.

Segurança: a chave de API nunca é incluída em mensagens de log. Um filtro
de logging (_FiltroChaveAPI) é instalado nos handlers do logger raiz ao
instanciar BuscadorProvedores, mascarando a chave em qualquer log acidental —
inclusive nos emitidos por bibliotecas de terceiros, como requests/urllib3.

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
from typing import Callable, Optional

import requests

from cache import carregar_cache, salvar_cache
from config import (
    CAMINHO_CACHE,
    CAMPOS_DETALHES,
    INTERVALO_ENTRE_CHAMADAS,
    INTERVALO_GRAVACAO_CACHE,
    INTERVALO_PAGINACAO,
    MAX_PAGINAS,
    RAIO_ESTRITO,
    TERMOS_DE_BUSCA,
    URL_DETALHES,
    URL_GEOCODING,
    URL_TEXT_SEARCH,
)
from geo import distancia_km

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceções públicas
# ---------------------------------------------------------------------------

class ErroLocalizacao(Exception):
    """Levantado quando o endereço não pode ser geocodificado."""


class ErroAPI(Exception):
    """Levantado para erros inesperados retornados pela API do Google."""


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
        buscador = BuscadorProvedores(api_key="SUA_CHAVE")
        lat, lng = buscador.geocodificar("Florianópolis, SC")
        provedores = buscador.buscar_todos(lat, lng, raio=8000)
    """

    def __init__(self, api_key: str, caminho_cache: str = CAMINHO_CACHE) -> None:
        """
        Args:
            api_key: Chave da Google Maps API.
            caminho_cache: Caminho do arquivo de cache de Place Details.
        """
        if not api_key:
            raise ValueError("A chave de API do Google Maps não pode ser vazia.")

        self.api_key = api_key
        self._sessao = requests.Session()
        self._sessao.headers.update({"Accept": "application/json"})

        # Carrega o cache de Place Details do disco
        self._caminho_cache = caminho_cache
        self._cache: dict = carregar_cache(caminho_cache)

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
    # Busca de lugares
    # ------------------------------------------------------------------

    def _buscar_pagina(
        self,
        query: str,
        lat: float,
        lng: float,
        raio: int,
        next_page_token: Optional[str] = None,
    ) -> dict:
        """
        Executa uma única chamada à Places Text Search API.

        Quando `next_page_token` é fornecido, ignora os demais parâmetros
        pois a API usa o token para continuar a busca anterior.
        """
        if next_page_token:
            params = {"pagetoken": next_page_token, "key": self.api_key}
        else:
            params = {
                "query": query,
                "location": f"{lat},{lng}",
                "radius": raio,
                "key": self.api_key,
            }

        try:
            resposta = self._sessao.get(URL_TEXT_SEARCH, params=params, timeout=10)
            resposta.raise_for_status()
        except requests.ConnectionError as exc:
            raise ConnectionError("Falha de rede ao buscar provedores.") from exc
        except requests.Timeout as exc:
            raise ConnectionError("Tempo esgotado ao buscar provedores.") from exc
        except requests.HTTPError as exc:
            raise ErroAPI(
                f"Erro HTTP {resposta.status_code} na Places Text Search."
            ) from exc

        return resposta.json()

    def _buscar_por_termo(
        self, termo: str, lat: float, lng: float, raio: int
    ) -> list[dict]:
        """
        Busca provedores para um único termo, iterando por todas as páginas.

        Returns:
            Lista de dicts brutos retornados pela API (campo 'results').
        """
        resultados: list[dict] = []
        next_token: Optional[str] = None

        for pagina in range(1, MAX_PAGINAS + 1):
            # A API exige um atraso antes de usar o next_page_token
            if next_token:
                logger.debug(
                    "Aguardando %.1fs para próxima página...", INTERVALO_PAGINACAO
                )
                time.sleep(INTERVALO_PAGINACAO)

            dados = self._buscar_pagina(termo, lat, lng, raio, next_token)
            status = dados.get("status")

            if status == "ZERO_RESULTS":
                logger.debug(
                    "Nenhum resultado para '%s' (página %d).", termo, pagina
                )
                break
            if status == "REQUEST_DENIED":
                raise ErroAPI(
                    "Chave de API inválida ou sem permissão para a Places API."
                )
            if status not in ("OK", "ZERO_RESULTS"):
                logger.warning(
                    "Status inesperado '%s' para o termo '%s' (página %d).",
                    status, termo, pagina,
                )
                break

            itens = dados.get("results", [])
            resultados.extend(itens)
            logger.debug(
                "Página %d: %d resultado(s) para '%s'.", pagina, len(itens), termo
            )

            next_token = dados.get("next_page_token")
            if not next_token:
                break

        return resultados

    # ------------------------------------------------------------------
    # Detalhes de um lugar (com cache)
    # ------------------------------------------------------------------

    def obter_detalhes(self, place_id: str) -> dict:
        """
        Obtém informações detalhadas de um estabelecimento pelo place_id.

        Consulta o cache local antes de chamar a API. Se o place_id já
        estiver em cache, retorna o valor salvo sem nenhuma chamada de rede.
        Caso contrário, chama a API e persiste o resultado no cache.

        Returns:
            Dict com os campos definidos em CAMPOS_DETALHES, ou {} em caso de erro.
        """
        # --- Consulta o cache ---
        if place_id in self._cache:
            logger.debug("Cache hit para place_id '%s'.", place_id)
            return self._cache[place_id]

        # --- Chama a API ---
        # A pausa de rate limit vive aqui, e não no laço de buscar_todos, para
        # não penalizar os acertos de cache: dormir antes de uma leitura que
        # nunca toca a rede anula justamente o ganho que o cache existe para dar.
        time.sleep(INTERVALO_ENTRE_CHAMADAS)

        params = {
            "place_id": place_id,
            "fields": ",".join(CAMPOS_DETALHES),
            "key": self.api_key,
        }

        try:
            resposta = self._sessao.get(URL_DETALHES, params=params, timeout=10)
            resposta.raise_for_status()
        except (requests.ConnectionError, requests.Timeout):
            logger.warning(
                "Falha de rede ao obter detalhes do place_id '%s'. Pulando.", place_id
            )
            return {}
        except requests.HTTPError:
            logger.warning(
                "Erro HTTP ao obter detalhes do place_id '%s'. Pulando.", place_id
            )
            return {}

        dados = resposta.json()
        if dados.get("status") != "OK":
            logger.warning(
                "Place Details retornou status '%s' para '%s'.",
                dados.get("status"), place_id,
            )
            return {}

        resultado = dados.get("result", {})

        # --- Salva no cache ---
        # A gravação em disco é feita em lote (ver gravar_cache) para não
        # reescrever o arquivo inteiro a cada place_id consultado.
        self._cache[place_id] = resultado
        self._entradas_nao_gravadas += 1
        if self._entradas_nao_gravadas >= INTERVALO_GRAVACAO_CACHE:
            self.gravar_cache()

        return resultado

    # ------------------------------------------------------------------
    # Orquestrador principal
    # ------------------------------------------------------------------

    def buscar_todos(
        self,
        lat: float,
        lng: float,
        raio: int,
        callback_progresso: Optional[Callable[[dict], None]] = None,
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

        Returns:
            Lista de dicts com os campos padronizados definidos em COLUNAS_SAIDA,
            incluindo latitude, longitude e distancia_km em relação ao centro.
        """
        notificar = callback_progresso or (lambda _: None)
        total_etapas = len(TERMOS_DE_BUSCA)
        ids_vistos: set[str] = set()
        provedores: list[dict] = []
        raio_km = raio / 1000

        for i, termo in enumerate(TERMOS_DE_BUSCA, start=1):
            # Notifica o início da etapa (novos_provedores=None = ainda buscando)
            notificar({
                "etapa": i,
                "total_etapas": total_etapas,
                "mensagem": f'Buscando por: "{termo}"...',
                "novos_provedores": None,
                "total_acumulado": len(provedores),
            })

            try:
                brutos = self._buscar_por_termo(termo, lat, lng, raio)
            except (ConnectionError, ErroAPI) as exc:
                notificar({
                    "etapa": i,
                    "total_etapas": total_etapas,
                    "mensagem": f'Aviso ao buscar "{termo}": {exc}',
                    "novos_provedores": 0,
                    "total_acumulado": len(provedores),
                })
                continue

            novos = 0
            for item in brutos:
                place_id = item.get("place_id")
                if not place_id or place_id in ids_vistos:
                    continue

                ids_vistos.add(place_id)

                # O parâmetro `radius` da Text Search é um viés de relevância,
                # não um filtro rígido — a API devolve resultados além do raio.
                # Descartamos aqui, ANTES de gastar uma chamada de Place Details.
                distancia = self._distancia_do_centro(item, lat, lng)
                if RAIO_ESTRITO and distancia is not None and distancia > raio_km:
                    logger.debug(
                        "Descartado '%s': %.2f km do centro (raio de %.2f km).",
                        item.get("name", place_id), distancia, raio_km,
                    )
                    continue

                detalhes = self.obter_detalhes(place_id)
                provedores.append(
                    self._normalizar(item, detalhes, place_id, distancia)
                )
                novos += 1

            # Notifica o resultado da etapa com o número de novos encontrados
            notificar({
                "etapa": i,
                "total_etapas": total_etapas,
                "mensagem": f'Busca por "{termo}" concluída.',
                "novos_provedores": novos,
                "total_acumulado": len(provedores),
            })

        # Garante que nenhuma entrada de cache obtida nesta busca se perca,
        # mesmo que o total não tenha atingido INTERVALO_GRAVACAO_CACHE.
        self.gravar_cache()

        return provedores

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    @staticmethod
    def _coordenadas(bruto: dict) -> tuple[float | None, float | None]:
        """
        Extrai (latitude, longitude) do bloco geometry.location do resultado bruto.

        As coordenadas já vêm na resposta da Text Search — não custam nenhuma
        chamada extra à API.

        Returns:
            Tupla (lat, lng), ou (None, None) se o resultado não trouxer geometria.
        """
        local = bruto.get("geometry", {}).get("location", {})
        return local.get("lat"), local.get("lng")

    @classmethod
    def _distancia_do_centro(
        cls, bruto: dict, lat_centro: float, lng_centro: float
    ) -> float | None:
        """
        Distância em km entre o centro da busca e o estabelecimento.

        Returns:
            Distância em km, ou None se o resultado não trouxer coordenadas.
        """
        lat, lng = cls._coordenadas(bruto)
        if lat is None or lng is None:
            return None
        return distancia_km(lat_centro, lng_centro, lat, lng)

    @classmethod
    def _normalizar(
        cls,
        bruto: dict,
        detalhes: dict,
        place_id: str,
        distancia: float | None = None,
    ) -> dict:
        """
        Combina dados brutos da Text Search com os detalhes do Place Details
        em um dict com chaves padronizadas.

        Args:
            bruto: Item retornado pela Text Search.
            detalhes: Resposta do Place Details (pode ser {} se a chamada falhou).
            place_id: Identificador do estabelecimento no Google.
            distancia: Distância em km até o centro da busca, se já calculada.
        """
        # Preferimos os dados de Place Details por serem mais completos;
        # usamos os dados brutos como fallback.
        status_raw = detalhes.get("business_status", bruto.get("business_status", ""))
        status_map = {
            "OPERATIONAL": "Operacional",
            "CLOSED_TEMPORARILY": "Fechado temporariamente",
            "CLOSED_PERMANENTLY": "Fechado permanentemente",
        }

        lat, lng = cls._coordenadas(bruto)

        return {
            "nome": detalhes.get("name") or bruto.get("name", ""),
            "endereco": (
                detalhes.get("formatted_address")
                or bruto.get("formatted_address", "")
            ),
            "telefone": detalhes.get("formatted_phone_number", ""),
            "site": detalhes.get("website", ""),
            # Campo vazio (e não 0) quando não há coordenadas: numa planilha,
            # um zero seria lido como "no mesmo endereço do centro da busca".
            "distancia_km": distancia if distancia is not None else "",
            "avaliacao": detalhes.get("rating", bruto.get("rating", "")),
            "total_avaliacoes": detalhes.get(
                "user_ratings_total", bruto.get("user_ratings_total", "")
            ),
            "status": status_map.get(status_raw, status_raw),
            "latitude": lat if lat is not None else "",
            "longitude": lng if lng is not None else "",
            "place_id": place_id,
        }
