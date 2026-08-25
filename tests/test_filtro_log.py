"""
Testes do mascaramento da chave de API nos logs.

Regressão de dois bugs reais:
  1. O filtro instalado apenas no logger raiz não alcançava os loggers filhos
     (getLogger(__name__)), então a chave nunca era mascarada de fato.
  2. O mascaramento convertia todo argumento de formatação em str, quebrando
     mensagens com %d e %f ("%d format: a real number is required, not str").
"""

import logging

import pytest

from buscador import BuscadorProvedores, _FiltroChaveAPI, _instalar_filtro_chave

CHAVE = "AIzaSyFAKE_CHAVE_DE_TESTE_123"


@pytest.fixture
def raiz_limpa():
    """Isola o logger raiz: instala um handler próprio e desfaz tudo ao final."""
    raiz = logging.getLogger()
    handlers_originais = raiz.handlers[:]
    filtros_originais = raiz.filters[:]
    nivel_original = raiz.level

    raiz.handlers = []
    raiz.filters = []
    raiz.setLevel(logging.DEBUG)

    class Coletor(logging.Handler):
        def __init__(self):
            super().__init__()
            self.linhas: list[str] = []

        def emit(self, record):
            # format() dispara a interpolação %d/%f — é aqui que o bug 2 estourava
            self.linhas.append(self.format(record))

    coletor = Coletor()
    raiz.addHandler(coletor)

    yield raiz, coletor

    raiz.handlers = handlers_originais
    raiz.filters = filtros_originais
    raiz.setLevel(nivel_original)


def test_mascara_chave_vinda_de_logger_filho(raiz_limpa):
    """Bug 1: mensagens de loggers filhos precisam ser mascaradas."""
    raiz, coletor = raiz_limpa
    _instalar_filtro_chave(_FiltroChaveAPI(CHAVE))

    logging.getLogger("buscador").debug("chamando url?key=%s", CHAVE)

    assert CHAVE not in coletor.linhas[0]
    assert "***API_KEY***" in coletor.linhas[0]


def test_mascara_chave_vinda_do_logger_raiz(raiz_limpa):
    raiz, coletor = raiz_limpa
    _instalar_filtro_chave(_FiltroChaveAPI(CHAVE))

    logging.getLogger().debug("chave literal: " + CHAVE)

    assert CHAVE not in coletor.linhas[0]


def test_nao_quebra_formatacao_numerica(raiz_limpa):
    """Bug 2: argumentos numéricos devem chegar intactos ao formatador."""
    raiz, coletor = raiz_limpa
    _instalar_filtro_chave(_FiltroChaveAPI(CHAVE))

    logging.getLogger("buscador").debug(
        "Página %d: %d resultado(s) — lat=%.4f", 1, 20, -27.5954
    )

    assert coletor.linhas == ["Página 1: 20 resultado(s) — lat=-27.5954"]


def test_mascara_argumentos_em_dicionario(raiz_limpa):
    raiz, coletor = raiz_limpa
    _instalar_filtro_chave(_FiltroChaveAPI(CHAVE))

    logging.getLogger("buscador").debug("params: %(key)s", {"key": CHAVE})

    assert CHAVE not in coletor.linhas[0]


def test_fechar_remove_o_filtro(raiz_limpa, tmp_path):
    """
    Bug 2 (vazamento): sem remoção, cada instância deixa um filtro pendurado
    no logging global — num servidor web isso cresce a cada requisição.
    """
    raiz, _ = raiz_limpa
    filtros_antes = len(raiz.filters)

    buscador = BuscadorProvedores(
        api_key=CHAVE, caminho_cache=str(tmp_path / "cache.json")
    )
    assert len(raiz.filters) == filtros_antes + 1

    buscador.fechar()
    assert len(raiz.filters) == filtros_antes


def test_context_manager_remove_o_filtro(raiz_limpa, tmp_path):
    raiz, _ = raiz_limpa
    filtros_antes = len(raiz.filters)

    with BuscadorProvedores(api_key=CHAVE, caminho_cache=str(tmp_path / "c.json")):
        assert len(raiz.filters) == filtros_antes + 1

    assert len(raiz.filters) == filtros_antes


def test_instancias_repetidas_nao_acumulam_filtros(raiz_limpa, tmp_path):
    """Cem ciclos de vida completos não devem deixar resíduo."""
    raiz, _ = raiz_limpa
    filtros_antes = len(raiz.filters)

    for i in range(100):
        with BuscadorProvedores(api_key=CHAVE, caminho_cache=str(tmp_path / "c.json")):
            pass

    assert len(raiz.filters) == filtros_antes


def test_chave_vazia_e_rejeitada():
    with pytest.raises(ValueError):
        BuscadorProvedores(api_key="")
