"""
conftest.py — Fixtures compartilhadas pela suíte de testes.

Fica na raiz do projeto (e não em tests/) para que o pytest insira este
diretório no sys.path, tornando os módulos do projeto importáveis nos testes
sem precisar instalar o pacote.

Nenhum teste toca a rede: a sessão HTTP do buscador é substituída pela
SessaoFalsa, que devolve respostas pré-programadas e registra cada chamada.
"""

import pytest

from config import URL_DETALHES, URL_GEOCODING, URL_TEXT_SEARCH


# ---------------------------------------------------------------------------
# Dublês de requests
# ---------------------------------------------------------------------------

class RespostaFalsa:
    """Imita requests.Response com apenas o que o buscador consome."""

    def __init__(self, payload: dict, status_code: int = 200, erro: Exception | None = None):
        self._payload = payload
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

    Roteia por URL e registra todas as chamadas, permitindo assertar
    quantas vezes a API foi (ou não foi) consultada.
    """

    def __init__(self, rotas: dict):
        # rotas: {url: RespostaFalsa} ou {url: [RespostaFalsa, ...]} para
        # respostas sequenciais (ex.: paginação).
        self.rotas = rotas
        self.chamadas: list[tuple[str, dict]] = []
        self.headers: dict = {}
        self.fechada = False

    def get(self, url, params=None, timeout=None):
        self.chamadas.append((url, dict(params or {})))
        resposta = self.rotas[url]
        if isinstance(resposta, list):
            # Mantém a última resposta caso a lista se esgote
            return resposta.pop(0) if len(resposta) > 1 else resposta[0]
        return resposta

    def close(self) -> None:
        self.fechada = True

    def chamadas_para(self, url: str) -> list[dict]:
        """Parâmetros de todas as chamadas feitas à URL informada."""
        return [params for u, params in self.chamadas if u == url]


# ---------------------------------------------------------------------------
# Payloads de exemplo
# ---------------------------------------------------------------------------

# Centro de referência usado nos testes: Florianópolis, SC
LAT_CENTRO, LNG_CENTRO = -27.5954, -48.5480


def item_bruto(place_id: str, nome: str, lat: float, lng: float) -> dict:
    """Monta um item no formato devolvido pela Places Text Search."""
    return {
        "place_id": place_id,
        "name": nome,
        "formatted_address": f"Endereço de {nome}",
        "business_status": "OPERATIONAL",
        "geometry": {"location": {"lat": lat, "lng": lng}},
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
def payload_detalhes() -> dict:
    return {
        "status": "OK",
        "result": {
            "name": "Provedor Alfa",
            "formatted_address": "Rua Um, 100 — Florianópolis, SC",
            "formatted_phone_number": "(48) 3333-0000",
            "website": "https://alfa.example.com",
            "rating": 4.5,
            "user_ratings_total": 120,
            "business_status": "OPERATIONAL",
        },
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
def urls():
    """Atalho para as três URLs da API nos testes."""
    return {
        "geocoding": URL_GEOCODING,
        "busca": URL_TEXT_SEARCH,
        "detalhes": URL_DETALHES,
    }
