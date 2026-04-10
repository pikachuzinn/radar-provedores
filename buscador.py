"""
buscador.py — Módulo principal de busca de provedores de internet.

Encapsula todas as chamadas à Google Places API:
  1. Geocodificação de endereços → coordenadas (lat, lng)
  2. Text Search para encontrar provedores próximos
  3. Place Details para enriquecer cada resultado com telefone, site, etc.

Segurança: a chave de API nunca é incluída em mensagens de log. Um filtro
de logging (_FiltroChaveAPI) é registrado automaticamente no logger raiz ao
instanciar BuscadorProvedores, mascarando a chave em qualquer log acidental.
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
    INTERVALO_PAGINACAO,
    MAX_PAGINAS,
    TERMOS_DE_BUSCA,
    URL_DETALHES,
    URL_GEOCODING,
    URL_TEXT_SEARCH,
)

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
    """

    _MASCARA = "***API_KEY***"

    def __init__(self, chave: str) -> None:
        super().__init__()
        self._chave = chave

    def filter(self, record: logging.LogRecord) -> bool:
        if self._chave:
            record.msg = str(record.msg).replace(self._chave, self._MASCARA)
            record.args = self._mascarar_args(record.args)
        return True

    def _mascarar_args(self, args):
        """Percorre os argumentos de formatação do log e mascara a chave."""
        if args is None:
            return args
        if isinstance(args, dict):
            return {k: str(v).replace(self._chave, self._MASCARA) for k, v in args.items()}
        return tuple(str(a).replace(self._chave, self._MASCARA) for a in args)


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

        # Registra o filtro de segurança no logger raiz para mascarar a chave
        # em qualquer mensagem de log emitida enquanto este objeto existir
        self._filtro_log = _FiltroChaveAPI(api_key)
        logging.getLogger().addFilter(self._filtro_log)

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
        self._cache[place_id] = resultado
        salvar_cache(self._cache, self._caminho_cache)

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
            Lista de dicts com os campos padronizados definidos em COLUNAS_SAIDA.
        """
        notificar = callback_progresso or (lambda _: None)
        total_etapas = len(TERMOS_DE_BUSCA)
        ids_vistos: set[str] = set()
        provedores: list[dict] = []

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
                time.sleep(INTERVALO_ENTRE_CHAMADAS)

                detalhes = self.obter_detalhes(place_id)
                provedores.append(self._normalizar(item, detalhes, place_id))
                novos += 1

            # Notifica o resultado da etapa com o número de novos encontrados
            notificar({
                "etapa": i,
                "total_etapas": total_etapas,
                "mensagem": f'Busca por "{termo}" concluída.',
                "novos_provedores": novos,
                "total_acumulado": len(provedores),
            })

        return provedores

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    @staticmethod
    def _normalizar(bruto: dict, detalhes: dict, place_id: str) -> dict:
        """
        Combina dados brutos da Text Search com os detalhes do Place Details
        em um dict com chaves padronizadas.
        """
        # Preferimos os dados de Place Details por serem mais completos;
        # usamos os dados brutos como fallback.
        status_raw = detalhes.get("business_status", bruto.get("business_status", ""))
        status_map = {
            "OPERATIONAL": "Operacional",
            "CLOSED_TEMPORARILY": "Fechado temporariamente",
            "CLOSED_PERMANENTLY": "Fechado permanentemente",
        }

        return {
            "nome": detalhes.get("name") or bruto.get("name", ""),
            "endereco": (
                detalhes.get("formatted_address")
                or bruto.get("formatted_address", "")
            ),
            "telefone": detalhes.get("formatted_phone_number", ""),
            "site": detalhes.get("website", ""),
            "avaliacao": detalhes.get("rating", bruto.get("rating", "")),
            "total_avaliacoes": detalhes.get(
                "user_ratings_total", bruto.get("user_ratings_total", "")
            ),
            "status": status_map.get(status_raw, status_raw),
            "place_id": place_id,
        }
