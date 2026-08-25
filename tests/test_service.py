"""
Testes de service.py — contrato da camada de serviço.

Regra central: executar_busca() nunca levanta exceção. Todo problema volta
como dict com a chave "erro" preenchida, para que qualquer interface (CLI,
Flask, GUI) trate erro do mesmo jeito.
"""

import pytest

import buscador as mod_buscador
import service
from conftest import LAT_CENTRO, LNG_CENTRO, RespostaFalsa, SessaoFalsa, item_bruto

CHAVE = "AIzaSyFAKE_CHAVE_DE_TESTE_123"
CHAVES_DO_RETORNO = {"provedores", "arquivos", "total", "coordenadas", "erro"}


@pytest.fixture
def api_falsa(monkeypatch, tmp_path, payload_geocoding, payload_detalhes, urls):
    """
    Substitui a sessão HTTP de qualquer BuscadorProvedores criado pelo service
    e isola o cache em tmp_path. Devolve a lista de sessões criadas.
    """
    sessoes: list[SessaoFalsa] = []
    itens = [item_bruto("pid1", "Provedor Alfa", -27.5960, -48.5490)]
    rotas = {
        urls["geocoding"]: RespostaFalsa(payload_geocoding),
        urls["busca"]: RespostaFalsa({"status": "OK", "results": itens}),
        urls["detalhes"]: RespostaFalsa(payload_detalhes),
    }

    init_original = mod_buscador.BuscadorProvedores.__init__

    def init_falso(self, api_key, caminho_cache=None):
        init_original(self, api_key, str(tmp_path / "cache.json"))
        sessao = SessaoFalsa(rotas)
        self._sessao = sessao
        sessoes.append(sessao)

    monkeypatch.setattr(mod_buscador.BuscadorProvedores, "__init__", init_falso)
    monkeypatch.setattr(mod_buscador.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod_buscador, "TERMOS_DE_BUSCA", ["provedor de internet"])
    return sessoes


# ---------------------------------------------------------------------------
# Validação de entrada
# ---------------------------------------------------------------------------

def test_sem_chave_retorna_erro_em_vez_de_levantar():
    resultado = service.executar_busca(api_key="", endereco="Florianópolis, SC")
    assert resultado["erro"] == "Chave de API não fornecida."
    assert set(resultado) == CHAVES_DO_RETORNO


def test_sem_localizacao_retorna_erro():
    resultado = service.executar_busca(api_key=CHAVE)
    assert "Nenhuma localização fornecida" in resultado["erro"]
    assert resultado["total"] == 0


def test_erro_de_geocodificacao_volta_no_dict(monkeypatch, tmp_path, urls):
    sessao = SessaoFalsa({urls["geocoding"]: RespostaFalsa({"status": "ZERO_RESULTS"})})
    init_original = mod_buscador.BuscadorProvedores.__init__

    def init_falso(self, api_key, caminho_cache=None):
        init_original(self, api_key, str(tmp_path / "cache.json"))
        self._sessao = sessao

    monkeypatch.setattr(mod_buscador.BuscadorProvedores, "__init__", init_falso)

    resultado = service.executar_busca(api_key=CHAVE, endereco="lugar nenhum")

    assert "não encontrado" in resultado["erro"]
    assert resultado["provedores"] == []
    assert sessao.fechada, "a sessão HTTP deve ser fechada mesmo no caminho de erro"


# ---------------------------------------------------------------------------
# Caminho feliz
# ---------------------------------------------------------------------------

def test_busca_por_endereco_gera_csv(api_falsa, tmp_path):
    resultado = service.executar_busca(
        api_key=CHAVE,
        endereco="Florianópolis, SC",
        raio=5000,
        formato="csv",
        diretorio=str(tmp_path / "saida"),
    )

    assert resultado["erro"] is None
    assert resultado["total"] == 1
    assert resultado["coordenadas"] == (LAT_CENTRO, LNG_CENTRO)
    assert len(resultado["arquivos"]) == 1
    assert resultado["arquivos"][0].endswith(".csv")


def test_busca_por_coordenadas_pula_a_geocodificacao(api_falsa, tmp_path, urls):
    resultado = service.executar_busca(
        api_key=CHAVE,
        coordenadas=(LAT_CENTRO, LNG_CENTRO),
        diretorio=str(tmp_path / "saida"),
    )

    assert resultado["erro"] is None
    assert api_falsa[0].chamadas_para(urls["geocoding"]) == []


def test_provedores_trazem_distancia_e_coordenadas(api_falsa, tmp_path):
    resultado = service.executar_busca(
        api_key=CHAVE,
        coordenadas=(LAT_CENTRO, LNG_CENTRO),
        diretorio=str(tmp_path / "saida"),
    )

    provedor = resultado["provedores"][0]
    assert provedor["latitude"] == -27.5960
    assert provedor["distancia_km"] < 1  # ~100 m do centro


def test_encerra_o_buscador_ao_final(api_falsa, tmp_path):
    """Sessão fechada e filtro de log removido — sem vazamento entre chamadas."""
    import logging
    filtros_antes = len(logging.getLogger().filters)

    service.executar_busca(
        api_key=CHAVE,
        coordenadas=(LAT_CENTRO, LNG_CENTRO),
        diretorio=str(tmp_path / "saida"),
    )

    assert api_falsa[0].fechada
    assert len(logging.getLogger().filters) == filtros_antes


def test_chamadas_repetidas_nao_acumulam_filtros(api_falsa, tmp_path):
    import logging
    filtros_antes = len(logging.getLogger().filters)

    for _ in range(10):
        service.executar_busca(
            api_key=CHAVE,
            coordenadas=(LAT_CENTRO, LNG_CENTRO),
            diretorio=str(tmp_path / "saida"),
        )

    assert len(logging.getLogger().filters) == filtros_antes


def test_formato_invalido_devolve_dados_mesmo_sem_arquivo(api_falsa, tmp_path):
    """A busca custou dinheiro em API — os dados não podem se perder por erro de exportação."""
    resultado = service.executar_busca(
        api_key=CHAVE,
        coordenadas=(LAT_CENTRO, LNG_CENTRO),
        formato="pdf",
        diretorio=str(tmp_path / "saida"),
    )

    assert "falha ao exportar" in resultado["erro"]
    assert resultado["total"] == 1
    assert resultado["provedores"] != []
    assert resultado["arquivos"] == []


def test_busca_sem_resultados_nao_e_erro(monkeypatch, tmp_path, urls, payload_geocoding):
    sessao = SessaoFalsa({
        urls["geocoding"]: RespostaFalsa(payload_geocoding),
        urls["busca"]: RespostaFalsa({"status": "ZERO_RESULTS"}),
    })
    init_original = mod_buscador.BuscadorProvedores.__init__

    def init_falso(self, api_key, caminho_cache=None):
        init_original(self, api_key, str(tmp_path / "cache.json"))
        self._sessao = sessao

    monkeypatch.setattr(mod_buscador.BuscadorProvedores, "__init__", init_falso)
    monkeypatch.setattr(mod_buscador.time, "sleep", lambda s: None)

    resultado = service.executar_busca(api_key=CHAVE, endereco="Florianópolis, SC")

    assert resultado["erro"] is None
    assert resultado["total"] == 0
    assert resultado["arquivos"] == []
