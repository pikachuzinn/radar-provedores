"""
clientes.py — Clientes HTTP das duas gerações da Places API.

O Google congelou a Places API legada em 01/03/2025: projetos do Cloud criados
a partir dessa data não conseguem mais ativá-la, enquanto projetos anteriores
continuam funcionando normalmente. Por isso o buscador fala as duas línguas:

    ClienteNovo    — Places API (New). Padrão. Único caminho possível para
                     projetos do Cloud criados a partir de março de 2025.
    ClienteLegado  — Places API (Legacy). Para projetos antigos que já a usam.

Escolha em config.py, pela constante USAR_PLACES_NOVA.

────────────────────────────────────────────────────────────────────────
Por que a diferença importa para o custo

Na API legada, a Text Search devolve um resumo sem telefone nem site: era
preciso uma chamada de Place Details para *cada* estabelecimento encontrado.
Uma busca de 60 provedores custava 15 buscas + 60 detalhes.

Na API nova, o cabeçalho X-Goog-FieldMask permite pedir telefone, site e
avaliação já na própria busca, para até 20 lugares por requisição. As mesmas
60 empresas saem em 15 requisições, sem nenhuma chamada de detalhes.

Cada cliente declara isso em `requer_detalhes`, e o orquestrador em
buscador.py age de acordo.
────────────────────────────────────────────────────────────────────────

Ambos os clientes devolvem registros já normalizados, com as chaves internas
definidas em config.COLUNAS_SAIDA. Assim buscador.py não precisa saber com
qual geração está falando.
"""

import logging
from typing import Optional

import requests

import diagnostico
from config import (
    CAMPOS_DETALHES,
    CAMPOS_PLACES_NOVA,
    IDIOMA_RESULTADOS,
    INTERVALO_PAGINACAO,
    REGIAO_RESULTADOS,
    RESULTADOS_POR_PAGINA,
    URL_DETALHES,
    URL_PLACES_BUSCA,
    URL_PLACES_DETALHES,
    URL_TEXT_SEARCH,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceções públicas
# ---------------------------------------------------------------------------

class ErroAPI(Exception):
    """
    Erro retornado pela API do Google.

    Carrega o diagnóstico (ver diagnostico.py) para que a interface possa
    mostrar a causa provável e o caminho de correção, em vez de repassar a
    mensagem em inglês do Google. A mensagem da exceção em si é o título do
    diagnóstico — uma linha, adequada a log e a resumo.
    """

    def __init__(self, mensagem: str, diag: dict | None = None) -> None:
        super().__init__(mensagem)
        self.diagnostico = diag or {}


# ---------------------------------------------------------------------------
# Normalização compartilhada
# ---------------------------------------------------------------------------

# Tradução dos status de funcionamento. As duas gerações usam os mesmos valores.
STATUS_TRADUZIDO = {
    "OPERATIONAL": "Operacional",
    "CLOSED_TEMPORARILY": "Fechado temporariamente",
    "CLOSED_PERMANENTLY": "Fechado permanentemente",
}


def _traduzir_status(valor: str) -> str:
    """Converte o status do Google para português, preservando o original se desconhecido."""
    return STATUS_TRADUZIDO.get(valor, valor or "")


def registro_vazio(place_id: str = "") -> dict:
    """
    Molde de registro com todas as chaves internas preenchidas com string vazia.

    Garante que todo registro tenha o mesmo formato, independentemente da
    geração da API e de quais campos o Google devolveu.
    """
    return {
        "nome": "",
        "endereco": "",
        "telefone": "",
        "site": "",
        "distancia_km": "",
        "avaliacao": "",
        "total_avaliacoes": "",
        "status": "",
        "latitude": "",
        "longitude": "",
        "place_id": place_id,
    }


def mesclar(base: dict, complemento: dict) -> dict:
    """
    Sobrepõe `complemento` a `base`, ignorando os campos vazios do complemento.

    Usado para enriquecer um registro de busca com os dados de Place Details
    sem apagar o que a busca já havia trazido.
    """
    resultado = dict(base)
    for chave, valor in complemento.items():
        if valor not in ("", None):
            resultado[chave] = valor
    return resultado


# ---------------------------------------------------------------------------
# Base comum
# ---------------------------------------------------------------------------

class ClientePlaces:
    """
    Contrato comum às duas gerações da API.

    Subclasses implementam `buscar_pagina` e `obter_detalhes`, e declaram:
        nome                 — identificador curto, usado como prefixo no cache
        requer_detalhes      — se a busca precisa de uma chamada extra por lugar
        intervalo_paginacao  — pausa obrigatória antes de usar o token da página seguinte
    """

    nome: str = ""
    requer_detalhes: bool = False
    intervalo_paginacao: float = 0.0

    def __init__(self, api_key: str, sessao: requests.Session) -> None:
        self.api_key = api_key
        self._sessao = sessao

    # -- helpers de rede compartilhados --------------------------------

    def _executar(self, metodo: str, url: str, **kwargs):
        """
        Faz a requisição e converte falhas de transporte em exceções nossas.

        Erros HTTP não são levantados aqui: cada geração reporta erro de um
        jeito diferente e o tratamento fica com a subclasse.
        """
        try:
            return self._sessao.request(metodo, url, timeout=10, **kwargs)
        except requests.ConnectionError as exc:
            raise ConnectionError("Sem conexão com a internet ao consultar a Places API.") from exc
        except requests.Timeout as exc:
            raise ConnectionError("Tempo esgotado ao consultar a Places API.") from exc

    def buscar_pagina(
        self, termo: str, lat: float, lng: float, raio: int,
        token: Optional[str] = None,
    ) -> tuple[list[dict], Optional[str]]:
        """
        Busca uma página de resultados.

        Returns:
            Tupla (registros_normalizados, token_da_proxima_pagina).
            O token é None quando não há mais páginas.
        """
        raise NotImplementedError

    def obter_detalhes(self, place_id: str) -> dict:
        """
        Consulta os detalhes de um estabelecimento.

        Returns:
            Registro normalizado parcial, ou {} se a consulta falhar.
            Falhas aqui nunca interrompem a busca — apenas empobrecem um registro.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Places API (New)
# ---------------------------------------------------------------------------

class ClienteNovo(ClientePlaces):
    """
    Cliente da Places API (New) — places.googleapis.com/v1.

    Diferenças relevantes em relação à legada:
      - Busca é POST com corpo JSON, não GET com query string.
      - A chave vai no cabeçalho X-Goog-Api-Key, nunca na URL.
      - X-Goog-FieldMask é obrigatório: sem ele a API retorna erro.
      - Erros vêm como status HTTP 4xx com corpo {"error": {...}}, e não como
        um campo "status" dentro de uma resposta 200.
      - O token da próxima página é utilizável de imediato, sem a espera de
        2 segundos que a API legada exigia.
    """

    nome = "novo"
    requer_detalhes = False   # o FieldMask já traz telefone, site e avaliação
    intervalo_paginacao = 0.0

    def _cabecalhos(self, mascara: str) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": mascara,
        }

    def _tratar_erro(self, resposta) -> None:
        """
        Converte a resposta de erro da API nova em ErroAPI com diagnóstico.

        A classificação usa o identificador `reason` do bloco `details`, que é
        estável e documentado, em vez do texto da mensagem — que vem em inglês
        e é reescrito pelo Google de tempos em tempos. Ver diagnostico.py.
        """
        if resposta.status_code < 400:
            return

        try:
            corpo = resposta.json()
        except ValueError:
            corpo = None

        diag = diagnostico.diagnosticar(resposta.status_code, corpo)
        logger.debug(
            "Erro da Places API classificado como '%s' (HTTP %d).",
            diag["causa"], resposta.status_code,
        )
        raise ErroAPI(diagnostico.resumo(diag), diag)

    def buscar_pagina(self, termo, lat, lng, raio, token=None):
        # Na paginação, todos os demais parâmetros devem ser idênticos aos da
        # primeira chamada — caso contrário a API responde INVALID_ARGUMENT.
        corpo = {
            "textQuery": termo,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    # A API aceita raio de até 50.000 m; acima disso, rejeita.
                    "radius": float(min(raio, 50_000)),
                }
            },
            "pageSize": RESULTADOS_POR_PAGINA,
            "languageCode": IDIOMA_RESULTADOS,
            "regionCode": REGIAO_RESULTADOS,
        }
        if token:
            corpo["pageToken"] = token

        mascara = ",".join(f"places.{campo}" for campo in CAMPOS_PLACES_NOVA)
        resposta = self._executar(
            "POST", URL_PLACES_BUSCA, json=corpo, headers=self._cabecalhos(mascara)
        )
        self._tratar_erro(resposta)

        dados = resposta.json()
        registros = [self._normalizar(p) for p in dados.get("places", [])]
        return registros, dados.get("nextPageToken")

    def obter_detalhes(self, place_id: str) -> dict:
        # Place Details (New) usa o field mask SEM o prefixo "places."
        mascara = ",".join(CAMPOS_PLACES_NOVA)
        resposta = self._executar(
            "GET", f"{URL_PLACES_DETALHES}/{place_id}", headers=self._cabecalhos(mascara)
        )

        if resposta.status_code >= 400:
            logger.warning(
                "Place Details (New) falhou para '%s' (HTTP %d). Registro segue sem enriquecimento.",
                place_id, resposta.status_code,
            )
            return {}

        return self._normalizar(resposta.json())

    @staticmethod
    def _normalizar(lugar: dict) -> dict:
        """Converte um objeto Place da API nova no registro interno do projeto."""
        local = lugar.get("location", {})
        registro = registro_vazio(lugar.get("id", ""))
        registro.update({
            "nome": lugar.get("displayName", {}).get("text", ""),
            "endereco": lugar.get("formattedAddress", ""),
            "telefone": lugar.get("nationalPhoneNumber", ""),
            "site": lugar.get("websiteUri", ""),
            "avaliacao": lugar.get("rating", ""),
            "total_avaliacoes": lugar.get("userRatingCount", ""),
            "status": _traduzir_status(lugar.get("businessStatus", "")),
            "latitude": local.get("latitude", ""),
            "longitude": local.get("longitude", ""),
        })
        return registro


# ---------------------------------------------------------------------------
# Places API (Legacy)
# ---------------------------------------------------------------------------

class ClienteLegado(ClientePlaces):
    """
    Cliente da Places API legada — maps.googleapis.com/maps/api/place.

    Mantido para projetos do Google Cloud que já a utilizam. Projetos criados
    a partir de 01/03/2025 não conseguem mais ativá-la: nesses casos, use
    ClienteNovo (USAR_PLACES_NOVA = True em config.py).
    """

    nome = "legado"
    requer_detalhes = True          # a busca legada não traz telefone nem site
    intervalo_paginacao = INTERVALO_PAGINACAO   # a API exige a espera antes do token

    def buscar_pagina(self, termo, lat, lng, raio, token=None):
        if token:
            # Com pagetoken, os demais parâmetros são ignorados pela API.
            params = {"pagetoken": token, "key": self.api_key}
        else:
            params = {
                "query": termo,
                "location": f"{lat},{lng}",
                "radius": raio,
                "key": self.api_key,
            }

        resposta = self._executar("GET", URL_TEXT_SEARCH, params=params)
        if resposta.status_code >= 400:
            diag = diagnostico.diagnosticar(resposta.status_code, None)
            raise ErroAPI(diagnostico.resumo(diag), diag)

        dados = resposta.json()
        status = dados.get("status")

        if status == "ZERO_RESULTS":
            return [], None
        if status == "REQUEST_DENIED":
            diag = diagnostico.diagnosticar_legado(
                status, dados.get("error_message", ""), places_legada=True
            )
            raise ErroAPI(diagnostico.resumo(diag), diag)
        if status != "OK":
            logger.warning("Status inesperado '%s' para o termo '%s'.", status, termo)
            return [], None

        registros = [self._normalizar_busca(item) for item in dados.get("results", [])]
        return registros, dados.get("next_page_token")

    def obter_detalhes(self, place_id: str) -> dict:
        params = {
            "place_id": place_id,
            "fields": ",".join(CAMPOS_DETALHES),
            "key": self.api_key,
        }

        resposta = self._executar("GET", URL_DETALHES, params=params)
        if resposta.status_code >= 400:
            logger.warning(
                "Erro HTTP %d ao obter detalhes de '%s'. Pulando.",
                resposta.status_code, place_id,
            )
            return {}

        dados = resposta.json()
        if dados.get("status") != "OK":
            logger.warning(
                "Place Details retornou status '%s' para '%s'.", dados.get("status"), place_id
            )
            return {}

        return self._normalizar_detalhes(dados.get("result", {}), place_id)

    @staticmethod
    def _normalizar_busca(item: dict) -> dict:
        """Converte um item da Text Search legada no registro interno."""
        local = item.get("geometry", {}).get("location", {})
        registro = registro_vazio(item.get("place_id", ""))
        registro.update({
            "nome": item.get("name", ""),
            "endereco": item.get("formatted_address", ""),
            "avaliacao": item.get("rating", ""),
            "total_avaliacoes": item.get("user_ratings_total", ""),
            "status": _traduzir_status(item.get("business_status", "")),
            "latitude": local.get("lat", ""),
            "longitude": local.get("lng", ""),
        })
        return registro

    @staticmethod
    def _normalizar_detalhes(resultado: dict, place_id: str) -> dict:
        """Converte a resposta do Place Details legado no registro interno."""
        registro = registro_vazio(place_id)
        registro.update({
            "nome": resultado.get("name", ""),
            "endereco": resultado.get("formatted_address", ""),
            "telefone": resultado.get("formatted_phone_number", ""),
            "site": resultado.get("website", ""),
            "avaliacao": resultado.get("rating", ""),
            "total_avaliacoes": resultado.get("user_ratings_total", ""),
            "status": _traduzir_status(resultado.get("business_status", "")),
        })
        return registro


# ---------------------------------------------------------------------------
# Fábrica
# ---------------------------------------------------------------------------

def criar_cliente(api_key: str, sessao: requests.Session, usar_nova: bool) -> ClientePlaces:
    """
    Instancia o cliente da geração escolhida.

    Args:
        api_key: Chave da Google Maps API.
        sessao: Sessão HTTP compartilhada, criada e fechada pelo buscador.
        usar_nova: True para Places API (New), False para a legada.
    """
    return ClienteNovo(api_key, sessao) if usar_nova else ClienteLegado(api_key, sessao)
