"""
Testes de clientes.py — protocolo das duas gerações da Places API.

Aqui se verifica o que é específico de cada geração: forma da requisição,
cabeçalhos, tradução dos payloads e mapeamento de erros. A orquestração
(deduplicação, cache, distância) é testada em test_buscador.py.
"""

import pytest

from clientes import (
    ClienteLegado,
    ClienteNovo,
    ErroAPI,
    criar_cliente,
    mesclar,
    registro_vazio,
)
from conftest import (
    CHAVE,
    LAT_CENTRO,
    LNG_CENTRO,
    RespostaFalsa,
    SessaoFalsa,
    detalhes_legado,
    erro_novo,
    item_legado,
    lugar_novo,
    resposta_busca_nova,
)
from config import URL_DETALHES, URL_PLACES_BUSCA, URL_PLACES_DETALHES, URL_TEXT_SEARCH


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------

def test_registro_vazio_tem_todas_as_chaves_de_saida():
    from config import COLUNAS_SAIDA
    assert set(registro_vazio()) == set(COLUNAS_SAIDA)


def test_mesclar_ignora_campos_vazios_do_complemento():
    """Detalhes incompletos não podem apagar o que a busca já trouxe."""
    base = {"nome": "Da busca", "telefone": "(48) 1111-1111"}
    resultado = mesclar(base, {"nome": "Dos detalhes", "telefone": "", "site": None})

    assert resultado["nome"] == "Dos detalhes"
    assert resultado["telefone"] == "(48) 1111-1111"


def test_fabrica_escolhe_a_geracao():
    sessao = SessaoFalsa()
    assert isinstance(criar_cliente(CHAVE, sessao, usar_nova=True), ClienteNovo)
    assert isinstance(criar_cliente(CHAVE, sessao, usar_nova=False), ClienteLegado)


# ---------------------------------------------------------------------------
# Places API (New) — requisição
# ---------------------------------------------------------------------------

@pytest.fixture
def cliente_novo():
    def _montar(rotas):
        sessao = SessaoFalsa(rotas)
        return ClienteNovo(CHAVE, sessao), sessao
    return _montar


def test_busca_nova_usa_post_no_endpoint_v1(cliente_novo):
    cliente, sessao = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([]))})
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)

    chamada = sessao.chamadas[0]
    assert chamada.metodo == "POST"
    assert chamada.url == "https://places.googleapis.com/v1/places:searchText"


def test_chave_vai_no_cabecalho_e_nunca_na_url(cliente_novo):
    """
    Regressão de segurança: na API nova a chave viaja em X-Goog-Api-Key.
    Colocá-la na query string a exporia em logs de proxy e histórico de rede.
    """
    cliente, sessao = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([]))})
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)

    chamada = sessao.chamadas[0]
    assert chamada.cabecalhos["X-Goog-Api-Key"] == CHAVE
    assert CHAVE not in chamada.url
    assert CHAVE not in str(chamada.params)
    assert CHAVE not in str(chamada.corpo)


def test_field_mask_da_busca_usa_prefixo_places(cliente_novo):
    """Sem field mask a API retorna erro; na busca, cada campo leva 'places.'."""
    cliente, sessao = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([]))})
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)

    mascara = sessao.chamadas[0].cabecalhos["X-Goog-FieldMask"]
    campos = mascara.split(",")

    assert all(c.startswith("places.") for c in campos)
    assert "places.nationalPhoneNumber" in campos
    assert "places.location" in campos


def test_corpo_da_busca_tem_viés_de_localizacao_circular(cliente_novo):
    cliente, sessao = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([]))})
    cliente.buscar_pagina("provedor de internet", LAT_CENTRO, LNG_CENTRO, 8000)

    corpo = sessao.chamadas[0].corpo
    circulo = corpo["locationBias"]["circle"]

    assert corpo["textQuery"] == "provedor de internet"
    assert circulo["center"] == {"latitude": LAT_CENTRO, "longitude": LNG_CENTRO}
    assert circulo["radius"] == 8000.0
    assert corpo["languageCode"] == "pt-BR"
    assert corpo["regionCode"] == "BR"
    assert corpo["pageSize"] == 20


def test_raio_e_limitado_ao_maximo_da_api(cliente_novo):
    """A API rejeita raio acima de 50.000 m — limitamos antes de enviar."""
    cliente, sessao = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([]))})
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 120_000)

    assert sessao.chamadas[0].corpo["locationBias"]["circle"]["radius"] == 50_000.0


def test_token_de_pagina_e_repassado(cliente_novo):
    cliente, sessao = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([]))})
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000, token="TOKEN123")

    assert sessao.chamadas[0].corpo["pageToken"] == "TOKEN123"


def test_primeira_pagina_nao_manda_token(cliente_novo):
    cliente, sessao = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([]))})
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)

    assert "pageToken" not in sessao.chamadas[0].corpo


# ---------------------------------------------------------------------------
# Places API (New) — resposta
# ---------------------------------------------------------------------------

def test_busca_nova_normaliza_os_lugares(cliente_novo):
    lugar = lugar_novo("pid1", "Fibra Litoral", -27.60, -48.55,
                       telefone="(47) 3344-0011", site="https://fibra.example.com",
                       nota=4.2, total_notas=30)
    cliente, _ = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([lugar]))})

    registros, token = cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)
    registro = registros[0]

    assert token is None
    assert registro["place_id"] == "pid1"
    assert registro["nome"] == "Fibra Litoral"           # displayName.text
    assert registro["telefone"] == "(47) 3344-0011"      # nationalPhoneNumber
    assert registro["site"] == "https://fibra.example.com"  # websiteUri
    assert registro["avaliacao"] == 4.2                  # rating
    assert registro["total_avaliacoes"] == 30            # userRatingCount
    assert registro["status"] == "Operacional"           # businessStatus traduzido
    assert registro["latitude"] == -27.60                # location.latitude
    assert registro["longitude"] == -48.55


def test_busca_nova_devolve_token_da_proxima_pagina(cliente_novo):
    cliente, _ = cliente_novo({
        URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([], proxima_pagina="ABC"))
    })
    _, token = cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)
    assert token == "ABC"


def test_campos_ausentes_viram_string_vazia(cliente_novo):
    """Campos Enterprise podem ser removidos do field mask para baixar o custo."""
    minimo = {"id": "pid1", "displayName": {"text": "Sem contato"}}
    cliente, _ = cliente_novo({URL_PLACES_BUSCA: RespostaFalsa(resposta_busca_nova([minimo]))})

    registro = cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)[0][0]

    assert registro["telefone"] == ""
    assert registro["latitude"] == ""
    assert registro["nome"] == "Sem contato"


def test_a_busca_nova_dispensa_place_details():
    """
    O ganho central da migração: o field mask traz telefone e site já na busca,
    então não é preciso uma chamada de Place Details por estabelecimento.
    """
    assert ClienteNovo.requer_detalhes is False
    assert ClienteLegado.requer_detalhes is True


def test_api_nova_nao_exige_espera_entre_paginas():
    """A espera de 2s do next_page_token era uma limitação da API legada."""
    assert ClienteNovo.intervalo_paginacao == 0.0
    assert ClienteLegado.intervalo_paginacao > 0


# ---------------------------------------------------------------------------
# Places API (New) — erros
# ---------------------------------------------------------------------------

def test_erro_403_explica_como_ativar_a_api(cliente_novo):
    """A causa mais comum: projeto sem 'Places API (New)' habilitada."""
    cliente, _ = cliente_novo({URL_PLACES_BUSCA: erro_novo(403, "PERMISSION_DENIED")})

    with pytest.raises(ErroAPI, match="Places API \\(New\\) não ativada"):
        cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)


def test_erro_429_fala_em_cota(cliente_novo):
    cliente, _ = cliente_novo({URL_PLACES_BUSCA: erro_novo(429, "RESOURCE_EXHAUSTED")})
    with pytest.raises(ErroAPI, match="Cota"):
        cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)


def test_erro_400_repassa_a_mensagem_da_api(cliente_novo):
    cliente, _ = cliente_novo({
        URL_PLACES_BUSCA: erro_novo(400, "INVALID_ARGUMENT", "pageToken expirado")
    })
    with pytest.raises(ErroAPI, match="pageToken expirado"):
        cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)


def test_erro_500_sem_corpo_json_nao_quebra(cliente_novo):
    class SemJson(RespostaFalsa):
        def json(self):
            raise ValueError("não é json")

    cliente, _ = cliente_novo({URL_PLACES_BUSCA: SemJson({}, status_code=500)})
    with pytest.raises(ErroAPI, match="Erro HTTP 500"):
        cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)


def test_falha_de_rede_vira_connection_error(cliente_novo):
    import requests

    def estourar(chamada):
        raise requests.ConnectionError()

    cliente, _ = cliente_novo({URL_PLACES_BUSCA: estourar})
    with pytest.raises(ConnectionError, match="Sem conexão"):
        cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)


# ---------------------------------------------------------------------------
# Places API (New) — Place Details
# ---------------------------------------------------------------------------

def test_detalhes_novos_usam_get_com_id_no_caminho(cliente_novo):
    cliente, sessao = cliente_novo({
        URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Alfa", -27.6, -48.5))
    })
    cliente.obter_detalhes("pid1")

    chamada = sessao.chamadas[0]
    assert chamada.metodo == "GET"
    assert chamada.url == "https://places.googleapis.com/v1/places/pid1"


def test_field_mask_dos_detalhes_nao_usa_prefixo(cliente_novo):
    """No Place Details o field mask é sem 'places.' — com prefixo, a API recusa."""
    cliente, sessao = cliente_novo({
        URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Alfa", -27.6, -48.5))
    })
    cliente.obter_detalhes("pid1")

    mascara = sessao.chamadas[0].cabecalhos["X-Goog-FieldMask"]
    assert "places." not in mascara
    assert "nationalPhoneNumber" in mascara


def test_detalhes_novos_com_erro_devolvem_dict_vazio(cliente_novo):
    cliente, _ = cliente_novo({URL_PLACES_DETALHES: erro_novo(404, "NOT_FOUND")})
    assert cliente.obter_detalhes("pid_inexistente") == {}


# ---------------------------------------------------------------------------
# Places API (Legacy)
# ---------------------------------------------------------------------------

@pytest.fixture
def cliente_legado():
    def _montar(rotas):
        sessao = SessaoFalsa(rotas)
        return ClienteLegado(CHAVE, sessao), sessao
    return _montar


def test_busca_legada_usa_get_com_chave_na_query(cliente_legado):
    cliente, sessao = cliente_legado({
        URL_TEXT_SEARCH: RespostaFalsa({"status": "OK", "results": []})
    })
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)

    chamada = sessao.chamadas[0]
    assert chamada.metodo == "GET"
    assert chamada.params["key"] == CHAVE
    assert chamada.params["location"] == f"{LAT_CENTRO},{LNG_CENTRO}"
    assert chamada.params["radius"] == 5000


def test_busca_legada_normaliza_sem_telefone_nem_site(cliente_legado):
    """A Text Search legada não devolve contato — daí a necessidade do Details."""
    itens = [item_legado("pid1", "Alfa", -27.60, -48.55)]
    cliente, _ = cliente_legado({URL_TEXT_SEARCH: RespostaFalsa({"status": "OK", "results": itens})})

    registro = cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)[0][0]

    assert registro["nome"] == "Alfa"
    assert registro["latitude"] == -27.60
    assert registro["telefone"] == ""
    assert registro["site"] == ""


def test_zero_results_devolve_lista_vazia(cliente_legado):
    cliente, _ = cliente_legado({URL_TEXT_SEARCH: RespostaFalsa({"status": "ZERO_RESULTS"})})
    assert cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000) == ([], None)


def test_request_denied_sugere_migrar_para_a_api_nova(cliente_legado):
    """
    Projetos do Cloud criados a partir de 01/03/2025 não conseguem ativar a
    API legada — a mensagem precisa apontar a saída.
    """
    cliente, _ = cliente_legado({URL_TEXT_SEARCH: RespostaFalsa({"status": "REQUEST_DENIED"})})

    with pytest.raises(ErroAPI, match="USAR_PLACES_NOVA"):
        cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000)


def test_pagetoken_substitui_os_demais_parametros(cliente_legado):
    cliente, sessao = cliente_legado({
        URL_TEXT_SEARCH: RespostaFalsa({"status": "OK", "results": []})
    })
    cliente.buscar_pagina("provedor", LAT_CENTRO, LNG_CENTRO, 5000, token="TOK")

    params = sessao.chamadas[0].params
    assert params["pagetoken"] == "TOK"
    assert "query" not in params


def test_detalhes_legados_normalizam_contato(cliente_legado):
    cliente, _ = cliente_legado({URL_DETALHES: RespostaFalsa(detalhes_legado())})

    registro = cliente.obter_detalhes("pid1")

    assert registro["telefone"] == "(48) 3333-0000"     # formatted_phone_number
    assert registro["site"] == "https://alfa.example.com"  # website
    assert registro["total_avaliacoes"] == 120          # user_ratings_total
    assert registro["place_id"] == "pid1"


def test_detalhes_legados_com_status_ruim_devolvem_vazio(cliente_legado):
    cliente, _ = cliente_legado({URL_DETALHES: RespostaFalsa({"status": "NOT_FOUND"})})
    assert cliente.obter_detalhes("pid1") == {}
