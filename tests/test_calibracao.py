"""
Testes do modo multi-cidade — consolidação entre regiões e orquestração.

A pergunta que este modo responde: qual conjunto de termos posso fixar em
config.py sem perder resultado em NENHUMA das regiões onde trabalho?
"""

import pytest

import buscador as mod_buscador
import service
from analise_termos import consolidar, formatar_relatorio_multi
from conftest import (
    CHAVE,
    RespostaFalsa,
    SessaoFalsa,
    injetar_sessao,
    lugar_novo,
    resposta_busca_nova,
)
from config import URL_GEOCODING, URL_PLACES_BUSCA


# ---------------------------------------------------------------------------
# Consolidação (funções puras)
# ---------------------------------------------------------------------------

def test_termo_essencial_em_uma_so_cidade_nao_e_cortado():
    """
    O caso que justifica o modo multi-cidade. Na capital, "fibra" é redundante:
    tudo que ele acha, o termo genérico também acha. No interior, é o único que
    encontra a empresa local. Medir só a capital levaria a cortá-lo por engano.
    """
    consolidacao = consolidar({
        "Capital": {"generico": {"a", "b", "c"}, "fibra": {"a", "b"}},
        "Interior": {"generico": {"d"}, "fibra": {"e"}},
    })

    assert "fibra" in consolidacao["essenciais"]
    assert "fibra" not in consolidacao["dispensaveis"]

    # E na análise isolada da capital ele apareceria como dispensável
    assert "fibra" in consolidacao["cidades"]["Capital"]["dispensaveis"]


def test_termo_redundante_em_todas_as_cidades_e_dispensavel():
    consolidacao = consolidar({
        "A": {"generico": {"1", "2"}, "extra": {"1"}},
        "B": {"generico": {"3", "4"}, "extra": {"3"}},
    })

    assert consolidacao["dispensaveis"] == ["extra"]
    assert consolidacao["essenciais"] == ["generico"]


def test_recomendacao_cobre_todas_as_cidades_e_nao_a_media():
    """
    Invariante central: manter apenas os essenciais precisa reproduzir o
    universo de CADA cidade, isoladamente. Uma recomendação que acerta a soma
    mas perde resultado numa das regiões seria inútil na prática.
    """
    cenarios = [
        {"A": {"t1": {"1", "2"}, "t2": {"2"}}, "B": {"t1": {"3"}, "t2": {"4"}}},
        {"A": {"t1": {"1"}, "t2": {"1"}, "t3": {"1"}},
         "B": {"t1": {"2"}, "t2": {"3"}, "t3": {"2", "3"}}},
        {"A": {"t1": set(), "t2": {"1"}}, "B": {"t1": {"2"}, "t2": set()}},
        {"Só uma": {"t1": {"1", "2"}, "t2": {"1"}}},
    ]

    for dados in cenarios:
        consolidacao = consolidar(dados)
        mantidos = set(consolidacao["essenciais"])

        for cidade, por_termo in dados.items():
            universo = set().union(*por_termo.values()) if por_termo else set()
            coberto = set().union(
                *(ids for termo, ids in por_termo.items() if termo in mantidos)
            ) if mantidos else set()
            assert coberto == universo, f"perdeu resultado em {cidade}: {dados}"


def test_conta_em_quantas_cidades_cada_termo_foi_essencial():
    consolidacao = consolidar({
        "A": {"sempre": {"1"}, "asvezes": {"2"}},
        "B": {"sempre": {"3"}, "asvezes": {"3"}},
    })

    por_termo = {l["termo"]: l for l in consolidacao["termos"]}

    assert por_termo["sempre"]["cidades_essencial"] == 2
    assert por_termo["asvezes"]["cidades_essencial"] == 1
    assert por_termo["asvezes"]["cidades_presente"] == 2


def test_soma_requisicoes_entre_cidades():
    consolidacao = consolidar(
        {"A": {"t": {"1"}}, "B": {"t": {"2"}}},
        {"A": {"t": 3}, "B": {"t": 2}},
    )
    assert consolidacao["termos"][0]["requisicoes_total"] == 5


def test_mesmo_place_id_em_cidades_diferentes_nao_se_confunde():
    """
    Os elementos cobertos são pares (cidade, place_id). Sem essa separação,
    uma empresa encontrada na cidade A poderia ser contada como já coberta
    na cidade B, e a recomendação passaria a perder resultado.
    """
    consolidacao = consolidar({
        "A": {"t1": {"repetido"}},
        "B": {"t2": {"repetido"}},
    })

    # Nenhum dos dois pode sair: cada um cobre o estabelecimento na sua cidade
    assert set(consolidacao["essenciais"]) == {"t1", "t2"}
    assert consolidacao["dispensaveis"] == []
    assert consolidacao["global"]["total_unico"] == 2   # dois pares distintos


def test_consolidacao_e_serializavel_em_json():
    import json
    json.dumps(consolidar({"A": {"t": {"1"}}}))


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------

def test_relatorio_traz_bloco_pronto_para_o_config():
    consolidacao = consolidar({
        "A": {"manter": {"1", "2"}, "cortar": {"1"}},
        "B": {"manter": {"3"}, "cortar": {"3"}},
    })
    texto = formatar_relatorio_multi(consolidacao)

    assert "TERMOS_DE_BUSCA: list[str] = [" in texto
    assert '    "manter",' in texto
    assert '    "cortar",' not in texto
    assert "✗ cortar" in texto


def test_relatorio_destaca_termo_essencial_so_em_algumas_cidades():
    consolidacao = consolidar({
        "Capital": {"generico": {"a", "b"}, "fibra": {"a"}},
        "Interior": {"generico": {"c"}, "fibra": {"d"}},
    })
    texto = formatar_relatorio_multi(consolidacao)

    assert "essencial em 1, dispensável em 1 de 2" in texto
    assert "dispensáveis em uma região e essenciais em outra" in texto


def test_relatorio_lista_as_cidades_ignoradas():
    consolidacao = consolidar({"A": {"t": {"1"}}})
    texto = formatar_relatorio_multi(consolidacao, {"B": "Endereço não encontrado"})

    assert "IGNORADA" in texto
    assert "só vale para as que foram medidas" in texto


def test_relatorio_reconhece_quando_nada_pode_sair():
    consolidacao = consolidar({"A": {"t1": {"1"}, "t2": {"2"}}})
    assert "Mantenha a lista como está" in formatar_relatorio_multi(consolidacao)


# ---------------------------------------------------------------------------
# Orquestração (service.calibrar_termos)
# ---------------------------------------------------------------------------

# Cada cidade tem coordenadas próprias e um catálogo próprio
CIDADES = {
    "Itajaí, SC":    ((-26.9077, -48.6618), {"provedor de internet": ["itj1", "itj2"],
                                             "internet fibra": ["itj1"]}),
    "Chapecó, SC":   ((-27.0965, -52.6182), {"provedor de internet": ["cha1"],
                                             "internet fibra": ["cha2"]}),
}


@pytest.fixture
def api_multicidade(monkeypatch, tmp_path):
    """Geocodificação e busca respondendo de acordo com a cidade consultada."""
    sessoes: list[SessaoFalsa] = []

    def geocodificar(chamada):
        endereco = chamada.params["address"]
        if endereco not in CIDADES:
            return RespostaFalsa({"status": "ZERO_RESULTS"})
        lat, lng = CIDADES[endereco][0]
        return RespostaFalsa({
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": lat, "lng": lng}}}],
        })

    def buscar(chamada):
        centro = chamada.corpo["locationBias"]["circle"]["center"]
        termo = chamada.corpo["textQuery"]
        for (lat, lng), catalogo in CIDADES.values():
            if (lat, lng) == (centro["latitude"], centro["longitude"]):
                ids = catalogo.get(termo, [])
                return RespostaFalsa(resposta_busca_nova(
                    [lugar_novo(i, i.upper(), lat, lng) for i in ids]
                ))
        return RespostaFalsa(resposta_busca_nova([]))

    rotas = {URL_GEOCODING: geocodificar, URL_PLACES_BUSCA: buscar}
    init_original = mod_buscador.BuscadorProvedores.__init__

    def init_falso(self, api_key, caminho_cache=None, usar_nova=None):
        init_original(self, api_key, str(tmp_path / "cache.json"), usar_nova)
        sessoes.append(injetar_sessao(self, SessaoFalsa(rotas)))

    monkeypatch.setattr(mod_buscador.BuscadorProvedores, "__init__", init_falso)
    monkeypatch.setattr(mod_buscador.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        mod_buscador, "TERMOS_DE_BUSCA", ["provedor de internet", "internet fibra"]
    )
    return sessoes


def test_calibracao_mede_cada_cidade_separadamente(api_multicidade):
    resultado = service.calibrar_termos(
        api_key=CHAVE, localizacoes=["Itajaí, SC", "Chapecó, SC"], raio=5000
    )

    consolidacao = resultado["consolidacao"]

    assert resultado["erro"] is None
    assert consolidacao["total_cidades"] == 2
    assert set(consolidacao["cidades"]) == {"Itajaí, SC", "Chapecó, SC"}
    assert consolidacao["cidades"]["Itajaí, SC"]["total_unico"] == 2
    assert consolidacao["cidades"]["Chapecó, SC"]["total_unico"] == 2


def test_termo_redundante_em_uma_cidade_e_unico_em_outra_e_mantido(api_multicidade):
    """
    Em Itajaí, "internet fibra" só devolve o que o termo genérico já traz.
    Em Chapecó, é o único a encontrar cha2. Não pode ser cortado.
    """
    resultado = service.calibrar_termos(
        api_key=CHAVE, localizacoes=["Itajaí, SC", "Chapecó, SC"], raio=5000
    )
    consolidacao = resultado["consolidacao"]

    assert "internet fibra" in consolidacao["cidades"]["Itajaí, SC"]["dispensaveis"]
    assert "internet fibra" in consolidacao["essenciais"]
    assert consolidacao["dispensaveis"] == []


def test_uma_cidade_com_erro_nao_aborta_as_demais(api_multicidade):
    resultado = service.calibrar_termos(
        api_key=CHAVE,
        localizacoes=["Itajaí, SC", "Cidade Inexistente", "Chapecó, SC"],
        raio=5000,
    )

    assert resultado["erro"] is None
    assert resultado["consolidacao"]["total_cidades"] == 2
    assert "Cidade Inexistente" in resultado["cidades_com_erro"]
    assert "não encontrado" in resultado["cidades_com_erro"]["Cidade Inexistente"]


def test_todas_as_cidades_falhando_devolve_erro(api_multicidade):
    resultado = service.calibrar_termos(
        api_key=CHAVE, localizacoes=["Lugar Nenhum", "Outro Lugar"], raio=5000
    )

    assert resultado["consolidacao"] is None
    assert "Nenhuma cidade pôde ser medida" in resultado["erro"]
    assert len(resultado["cidades_com_erro"]) == 2


def test_aceita_coordenadas_alem_de_enderecos(api_multicidade):
    resultado = service.calibrar_termos(
        api_key=CHAVE,
        localizacoes=["Itajaí, SC", (-27.0965, -52.6182)],
        raio=5000,
    )

    assert resultado["erro"] is None
    assert "-27.0965, -52.6182" in resultado["consolidacao"]["cidades"]


def test_reutiliza_um_unico_buscador_entre_as_cidades(api_multicidade):
    """Uma sessão HTTP e um cache para todas as cidades, não um por cidade."""
    service.calibrar_termos(
        api_key=CHAVE, localizacoes=["Itajaí, SC", "Chapecó, SC"], raio=5000
    )

    assert len(api_multicidade) == 1
    assert api_multicidade[0].fechada


def test_provedores_de_cada_cidade_sao_devolvidos(api_multicidade):
    """A busca é paga — os dados não podem se perder junto com o relatório."""
    resultado = service.calibrar_termos(
        api_key=CHAVE, localizacoes=["Itajaí, SC", "Chapecó, SC"], raio=5000
    )

    por_cidade = resultado["provedores_por_cidade"]
    assert len(por_cidade["Itajaí, SC"]) == 2
    assert len(por_cidade["Chapecó, SC"]) == 2


def test_sem_chave_e_sem_localizacao_retornam_erro():
    assert "Chave de API" in service.calibrar_termos(api_key="", localizacoes=["X"])["erro"]
    assert "Nenhuma localização" in service.calibrar_termos(api_key=CHAVE, localizacoes=[])["erro"]


def test_callback_de_cidade_reporta_cada_etapa(api_multicidade):
    eventos: list[dict] = []
    service.calibrar_termos(
        api_key=CHAVE,
        localizacoes=["Itajaí, SC", "Cidade Inexistente"],
        raio=5000,
        callback_cidade=eventos.append,
    )

    etapas = [(e["cidade"], e["etapa"]) for e in eventos]
    assert ("Itajaí, SC", "iniciando") in etapas
    assert ("Itajaí, SC", "concluida") in etapas
    assert ("Cidade Inexistente", "erro") in etapas
    assert all({"indice", "total", "cidade", "etapa"} <= set(e) for e in eventos)


def test_ausente_numa_cidade_nao_conta_como_dispensavel_ali():
    """
    Um termo que não achou nada numa cidade é diferente de um termo que achou
    e foi descartado. Confundir os dois geraria alertas falsos no relatório.
    """
    consolidacao = consolidar({
        "A": {"generico": {"1", "2"}, "raro": set()},   # raro não achou nada
        "B": {"generico": {"3"}, "raro": {"4"}},        # raro é o único a achar
    })

    por_termo = {l["termo"]: l for l in consolidacao["termos"]}

    assert por_termo["raro"]["cidades_presente"] == 1
    assert por_termo["raro"]["cidades_essencial"] == 1
    assert por_termo["raro"]["cidades_dispensavel"] == 0

    # Não é um caso de "cortaria por engano" — nunca foi descartado em lugar nenhum
    assert "dispensáveis em uma região" not in formatar_relatorio_multi(consolidacao)


# ---------------------------------------------------------------------------
# CLI de calibração
# ---------------------------------------------------------------------------

def test_apelido_gera_nome_de_pasta_seguro():
    """Cada cidade exporta numa subpasta — o rótulo vira caminho de arquivo."""
    from calibrar_termos import _apelido

    assert _apelido("Itajaí, SC") == "itajaí-sc"
    assert _apelido("-26.9077, -48.6618") == "-269077--486618"
    assert _apelido("São Joaquim / SC") == "são-joaquim-sc"
    assert _apelido("///") == "cidade"          # nunca devolve vazio


def test_apelido_nao_produz_travessia_de_diretorio():
    """Rótulo vem de entrada do usuário e vira caminho: não pode escapar da pasta."""
    from calibrar_termos import _apelido

    for entrada in ["../../etc", "a/../../b", "..", "./x"]:
        apelido = _apelido(entrada)
        assert "/" not in apelido
        assert ".." not in apelido
