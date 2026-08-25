"""
conftest.py — Fixtures compartilhadas pela suíte de testes.

Fica na raiz do projeto (e não em tests/) para que o pytest insira este
diretório no sys.path, tornando os módulos do projeto importáveis nos testes
sem precisar instalar o pacote.

Nenhum teste toca a rede: a sessão HTTP do buscador é substituída pela
SessaoFalsa, que devolve respostas pré-programadas e registra cada chamada.
Como o cliente da Places API guarda a sessão por referência, use sempre
`injetar_sessao()` — trocar apenas `buscador._sessao` deixaria o cliente
falando com a sessão real.
"""

from typing import NamedTuple, Optional

import pytest

from config import (
    URL_DETALHES,
    URL_GEOCODING,
    URL_PLACES_BUSCA,
    URL_PLACES_DETALHES,
    URL_TEXT_SEARCH,
)

# Centro de referência usado nos testes: Florianópolis, SC
LAT_CENTRO, LNG_CENTRO = -27.5954, -48.5480

# Prefixo das chamadas de Place Details (New). A barra final importa:
# sem ela, "…/v1/places" também casaria com "…/v1/places:searchText".
PREFIXO_DETALHES_NOVO = URL_PLACES_DETALHES + "/"

CHAVE = "AIzaSyFAKE_CHAVE_DE_TESTE_123"


# ---------------------------------------------------------------------------
# Dublês de requests
# ---------------------------------------------------------------------------

class Chamada(NamedTuple):
    """Registro de uma requisição feita através da SessaoFalsa."""
    metodo: str
    url: str
    params: dict
    corpo: dict
    cabecalhos: dict


class RespostaFalsa:
    """Imita requests.Response com apenas o que o projeto consome."""

    def __init__(
        self,
        payload: Optional[dict] = None,
        status_code: int = 200,
        erro: Optional[Exception] = None,
    ):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self._erro = erro

    def raise_for_status(self) -> None:
        if self._erro is not None:
            raise self._erro

    def json(self) -> dict:
        return self._payload


class SessaoFalsa:
    """
    Substitui requests.Session.

    Roteia por URL — casando primeiro por igualdade exata, depois pelo prefixo
    mais longo, o que permite atender endpoints com id no caminho, como
    /v1/places/{place_id}. Registra toda chamada, permitindo assertar quantas
    vezes a API foi (ou não foi) consultada.

    Cada rota aceita:
        RespostaFalsa          — devolvida sempre
        list[RespostaFalsa]    — consumida em ordem (a última se repete)
        callable(Chamada)      — resposta calculada a partir da requisição
    """

    def __init__(self, rotas: Optional[dict] = None):
        self.rotas = rotas or {}
        self.chamadas: list[Chamada] = []
        self.headers: dict = {}
        self.fechada = False

    # -- interface usada pelo projeto ----------------------------------

    def get(self, url, params=None, timeout=None, headers=None):
        return self._responder("GET", url, params=params, headers=headers)

    def request(self, metodo, url, timeout=None, params=None, json=None, headers=None):
        return self._responder(metodo, url, params=params, corpo=json, headers=headers)

    def close(self) -> None:
        self.fechada = True

    # -- internos -------------------------------------------------------

    def _responder(self, metodo, url, params=None, corpo=None, headers=None):
        chamada = Chamada(metodo, url, dict(params or {}), dict(corpo or {}), dict(headers or {}))
        self.chamadas.append(chamada)

        rota = self._encontrar_rota(url)
        if rota is None:
            raise AssertionError(f"Nenhuma rota configurada para {metodo} {url}")

        if callable(rota):
            return rota(chamada)
        if isinstance(rota, list):
            return rota.pop(0) if len(rota) > 1 else rota[0]
        return rota

    def _encontrar_rota(self, url: str):
        if url in self.rotas:
            return self.rotas[url]
        candidatas = [p for p in self.rotas if url.startswith(p)]
        if not candidatas:
            return None
        return self.rotas[max(candidatas, key=len)]

    # -- asserções ------------------------------------------------------

    def chamadas_para(self, prefixo: str) -> list[Chamada]:
        """Todas as chamadas cuja URL começa com o prefixo informado."""
        return [c for c in self.chamadas if c.url.startswith(prefixo)]


def injetar_sessao(buscador, sessao: SessaoFalsa) -> SessaoFalsa:
    """
    Faz o buscador e o seu cliente usarem a sessão falsa.

    Os dois precisam ser trocados: o cliente recebe a sessão por referência no
    construtor, então mexer apenas em `buscador._sessao` deixaria as chamadas
    da Places API indo para a rede de verdade.
    """
    buscador._sessao = sessao
    buscador._cliente._sessao = sessao
    return sessao


# ---------------------------------------------------------------------------
# Construtores de payload — Places API (New)
# ---------------------------------------------------------------------------

def lugar_novo(
    place_id: str,
    nome: str,
    lat: float,
    lng: float,
    telefone: str = "(48) 3333-0000",
    site: str = "https://exemplo.example.com",
    nota: float = 4.5,
    total_notas: int = 120,
) -> dict:
    """Monta um objeto Place no formato da Places API (New)."""
    return {
        "id": place_id,
        "displayName": {"text": nome, "languageCode": "pt-BR"},
        "formattedAddress": f"Endereço de {nome}",
        "nationalPhoneNumber": telefone,
        "websiteUri": site,
        "rating": nota,
        "userRatingCount": total_notas,
        "businessStatus": "OPERATIONAL",
        "location": {"latitude": lat, "longitude": lng},
    }


def resposta_busca_nova(lugares: list[dict], proxima_pagina: Optional[str] = None) -> dict:
    """Envelope de resposta do places:searchText."""
    corpo = {"places": lugares}
    if proxima_pagina:
        corpo["nextPageToken"] = proxima_pagina
    return corpo


def erro_novo(codigo: int, status: str, mensagem: str = "detalhe do erro") -> RespostaFalsa:
    """Resposta de erro no formato da API nova: HTTP 4xx com corpo {'error': {...}}."""
    return RespostaFalsa(
        {"error": {"code": codigo, "status": status, "message": mensagem}},
        status_code=codigo,
    )


# ---------------------------------------------------------------------------
# Construtores de payload — Places API (Legacy)
# ---------------------------------------------------------------------------

def item_legado(place_id: str, nome: str, lat: float, lng: float) -> dict:
    """Monta um item no formato devolvido pela Text Search legada."""
    return {
        "place_id": place_id,
        "name": nome,
        "formatted_address": f"Endereço de {nome}",
        "business_status": "OPERATIONAL",
        "geometry": {"location": {"lat": lat, "lng": lng}},
    }


def detalhes_legado(nome: str = "Provedor Alfa") -> dict:
    """Resposta do Place Details legado."""
    return {
        "status": "OK",
        "result": {
            "name": nome,
            "formatted_address": "Rua Um, 100 — Florianópolis, SC",
            "formatted_phone_number": "(48) 3333-0000",
            "website": "https://alfa.example.com",
            "rating": 4.5,
            "user_ratings_total": 120,
            "business_status": "OPERATIONAL",
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def urls():
    """Atalho para os endpoints usados nos testes."""
    return {
        "geocoding": URL_GEOCODING,
        "busca_nova": URL_PLACES_BUSCA,
        "detalhes_novo": URL_PLACES_DETALHES,
        "busca_legada": URL_TEXT_SEARCH,
        "detalhes_legado": URL_DETALHES,
    }


@pytest.fixture
def payload_geocoding() -> dict:
    return {
        "status": "OK",
        "results": [
            {"geometry": {"location": {"lat": LAT_CENTRO, "lng": LNG_CENTRO}}}
        ],
    }


@pytest.fixture
def sem_pausa(monkeypatch):
    """
    Neutraliza time.sleep no módulo buscador e devolve a lista de pausas pedidas.

    Além de deixar a suíte rápida, permite assertar que nenhuma pausa de rate
    limit é feita quando a resposta vem do cache.
    """
    import buscador

    pausas: list[float] = []
    monkeypatch.setattr(buscador.time, "sleep", lambda s: pausas.append(s))
    return pausas


@pytest.fixture
def montar(tmp_path):
    """
    Cria um buscador com sessão falsa e cache isolado, e o encerra ao final.

    Uso:
        buscador, sessao = montar({URL: RespostaFalsa({...})}, usar_nova=True)
    """
    from buscador import BuscadorProvedores

    criados: list = []

    def _montar(rotas: dict, usar_nova: bool = True, cache_inicial: Optional[dict] = None):
        caminho = str(tmp_path / "cache.json")
        if cache_inicial is not None:
            from cache import salvar_cache
            salvar_cache(cache_inicial, caminho)

        b = BuscadorProvedores(api_key=CHAVE, caminho_cache=caminho, usar_nova=usar_nova)
        sessao = injetar_sessao(b, SessaoFalsa(rotas))
        criados.append(b)
        return b, sessao

    yield _montar

    for b in criados:
        b.fechar()
