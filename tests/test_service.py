"""
Testes de service.py — contrato da camada de serviço.

Regra central: executar_busca() nunca levanta exceção. Todo problema volta
como dict com a chave "erro" preenchida, para que qualquer interface (CLI,
Flask, GUI) trate erro do mesmo jeito.
"""

import logging

import pytest

import buscador as mod_buscador
import service
from conftest import (
    CHAVE,
    LAT_CENTRO,
    LNG_CENTRO,
    RespostaFalsa,
    SessaoFalsa,
    injetar_sessao,
    lugar_novo,
    resposta_busca_nova,
)
from config import URL_GEOCODING, URL_PLACES_BUSCA

CHAVES_DO_RETORNO = {"provedores", "arquivos", "total", "coordenadas", "erro"}


@pytest.fixture
def servico_falso(monkeypatch, tmp_path):
    """
    Devolve uma função que arma as rotas da API e o cache isolado para
    qualquer BuscadorProvedores que o service venha a criar.

    Retorna a lista de sessões criadas, para inspecionar chamadas e conferir
    que foram fechadas.
    """
    def _armar(rotas: dict):
        sessoes: list[SessaoFalsa] = []
        init_original = mod_buscador.BuscadorProvedores.__init__

        def init_falso(self, api_key, caminho_cache=None, usar_nova=None):
            init_original(self, api_key, str(tmp_path / "cache.json"), usar_nova)
            sessoes.append(injetar_sessao(self, SessaoFalsa(rotas)))

        monkeypatch.setattr(mod_buscador.BuscadorProvedores, "__init__", init_falso)
        monkeypatch.setattr(mod_buscador.time, "sleep", lambda s: None)
        monkeypatch.setattr(mod_buscador, "TERMOS_DE_BUSCA", ["provedor de internet"])
        return sessoes

    return _armar


@pytest.fixture
def api_falsa(servico_falso, payload_geocoding):
    """Cenário padrão: geocodificação e busca bem-sucedidas, um provedor."""
    lugares = [lugar_novo("pid1", "Provedor Alfa", -27.5960, -48.5490)]
    return servico_falso({
        URL_GEOCODING: RespostaFalsa(payload_geocoding),
        URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova(lugares)),
    })


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


def test_erro_de_geocodificacao_volta_no_dict(servico_falso):
    sessoes = servico_falso({URL_GEOCODING: RespostaFalsa({"status": "ZERO_RESULTS"})})

    resultado = service.executar_busca(api_key=CHAVE, endereco="lugar nenhum")

    assert "não encontrado" in resultado["erro"]
    assert resultado["provedores"] == []
    assert sessoes[0].fechada, "a sessão HTTP deve ser fechada mesmo no caminho de erro"


def test_erro_da_places_api_volta_no_dict(servico_falso, payload_geocoding):
    from conftest import erro_novo

    sessoes = servico_falso({
        URL_GEOCODING: RespostaFalsa(payload_geocoding),
        URL_PLACES_BUSCA: erro_novo(403, "PERMISSION_DENIED"),
    })

    resultado = service.executar_busca(api_key=CHAVE, endereco="Florianópolis, SC")

    # Uma falha em todos os termos não é erro fatal: a busca só volta vazia
    assert resultado["total"] == 0
    assert sessoes[0].fechada


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


def test_busca_por_coordenadas_pula_a_geocodificacao(api_falsa, tmp_path):
    resultado = service.executar_busca(
        api_key=CHAVE,
        coordenadas=(LAT_CENTRO, LNG_CENTRO),
        diretorio=str(tmp_path / "saida"),
    )

    assert resultado["erro"] is None
    assert api_falsa[0].chamadas_para(URL_GEOCODING) == []


def test_provedores_trazem_contato_distancia_e_coordenadas(api_falsa, tmp_path):
    resultado = service.executar_busca(
        api_key=CHAVE,
        coordenadas=(LAT_CENTRO, LNG_CENTRO),
        diretorio=str(tmp_path / "saida"),
    )

    provedor = resultado["provedores"][0]
    assert provedor["latitude"] == -27.5960
    assert provedor["distancia_km"] < 1        # ~100 m do centro
    assert provedor["telefone"] != ""          # veio na própria busca


def test_encerra_o_buscador_ao_final(api_falsa, tmp_path):
    """Sessão fechada e filtro de log removido — sem vazamento entre chamadas."""
    filtros_antes = len(logging.getLogger().filters)

    service.executar_busca(
        api_key=CHAVE,
        coordenadas=(LAT_CENTRO, LNG_CENTRO),
        diretorio=str(tmp_path / "saida"),
    )

    assert api_falsa[0].fechada
    assert len(logging.getLogger().filters) == filtros_antes


def test_chamadas_repetidas_nao_acumulam_filtros(api_falsa, tmp_path):
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


def test_busca_sem_resultados_nao_e_erro(servico_falso, payload_geocoding):
    sessoes = servico_falso({
        URL_GEOCODING: RespostaFalsa(payload_geocoding),
        URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([])),
    })

    resultado = service.executar_busca(api_key=CHAVE, endereco="Florianópolis, SC")

    assert resultado["erro"] is None
    assert resultado["total"] == 0
    assert resultado["arquivos"] == []
    assert sessoes[0].fechada
