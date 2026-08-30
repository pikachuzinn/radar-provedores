"""
Testes do assistente de primeira execução.

As etapas são dados, separados da janela, justamente para poderem ser
conferidas aqui. O que se protege: os links levarem à página certa e os textos
não perderem os três avisos que evitam a maior parte do suporte — faturamento
obrigatório, "Places API (New)" e não "Places API", e restrição da chave.
"""

from urllib.parse import urlparse

import assistente


def todos_os_links():
    return [(rotulo, url) for passo in assistente.PASSOS for rotulo, url in passo["links"]]


# ---------------------------------------------------------------------------
# Estrutura
# ---------------------------------------------------------------------------

def test_todo_passo_tem_titulo_texto_e_links():
    for passo in assistente.PASSOS:
        assert passo["titulo"].strip()
        assert passo["texto"].strip()
        assert isinstance(passo["links"], list)
        assert "confirmacao" in passo


def test_so_o_ultimo_passo_pede_a_chave():
    """O campo de chave vem no fim, depois de a chave existir de fato."""
    com_campo = [i for i, p in enumerate(assistente.PASSOS) if p.get("campo_chave")]

    assert com_campo == [len(assistente.PASSOS) - 1]
    assert assistente.passo_final() == com_campo[0]


def test_passo_da_chave_nao_pede_confirmacao():
    """Ali a confirmação é a verificação da chave, não uma caixa de seleção."""
    assert assistente.PASSOS[assistente.passo_final()]["confirmacao"] is None


def test_passos_intermediarios_pedem_confirmacao():
    """Marcar a caixa força a leitura antes de avançar — é o ponto do assistente."""
    intermediarios = assistente.PASSOS[1:-1]
    assert intermediarios
    assert all(p["confirmacao"] for p in intermediarios)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def test_todos_os_links_sao_https():
    for rotulo, url in todos_os_links():
        assert urlparse(url).scheme == "https", f"{rotulo} não usa https"


def test_links_apontam_para_dominios_do_google():
    permitidos = {"console.cloud.google.com", "developers.google.com"}
    for rotulo, url in todos_os_links():
        assert urlparse(url).netloc in permitidos, f"{rotulo} aponta para fora: {url}"


def test_link_de_places_leva_a_api_nova_e_nao_a_legada():
    """
    No Console, "Places API" e "Places API (New)" são serviços distintos:
    places-backend.googleapis.com é a legada; places.googleapis.com é a nova.
    Mandar o usuário ativar a errada produz exatamente o erro de permissão que
    o assistente existe para evitar.
    """
    assert assistente.URL_PLACES_NOVA.endswith("/places.googleapis.com")
    assert "places-backend" not in assistente.URL_PLACES_NOVA

    urls = [url for _, url in todos_os_links()]
    assert assistente.URL_PLACES_NOVA in urls


def test_link_de_geocoding_usa_o_nome_de_servico_correto():
    assert assistente.URL_GEOCODING.endswith("/geocoding-backend.googleapis.com")
    assert assistente.URL_GEOCODING in [url for _, url in todos_os_links()]


def test_links_de_projeto_faturamento_e_credenciais_estao_presentes():
    urls = [url for _, url in todos_os_links()]
    for url in (assistente.URL_PROJETO, assistente.URL_FATURAMENTO, assistente.URL_CREDENCIAIS):
        assert url in urls


# ---------------------------------------------------------------------------
# Conteúdo: os avisos que evitam suporte
# ---------------------------------------------------------------------------

def texto_completo() -> str:
    return " ".join(p["texto"] for p in assistente.PASSOS)


def test_avisa_que_o_faturamento_e_obrigatorio():
    """
    Tropeço mais comum: sem conta de faturamento o Google recusa tudo, mesmo
    quem só vai usar a cota gratuita.
    """
    texto = texto_completo().lower()
    assert "faturamento" in texto
    assert "obrigat" in texto


def test_avisa_a_diferenca_entre_places_api_e_places_api_new():
    texto = texto_completo()
    assert "Places API (New)" in texto
    assert "diferentes" in texto or "distintos" in texto


def test_orienta_a_restringir_a_chave():
    texto = texto_completo().lower()
    assert "restri" in texto


def test_explica_que_a_chave_e_individual_e_fica_local():
    texto = texto_completo().lower()
    assert "própria" in texto or "individual" in texto
    assert "computador" in texto or "seu usuário" in texto


def test_informa_a_cota_gratuita_antes_de_pedir_cartao():
    """Quem vai cadastrar faturamento precisa saber que não será cobrado."""
    primeiro = assistente.PASSOS[0]["texto"].lower()
    assert "gratuit" in primeiro
