"""
Testes de diagnostico.py — tradução de erros da API em causa e correção.

O que está em jogo: um mesmo HTTP 403 PERMISSION_DENIED pode ser faturamento
desativado, API não ativada ou chave restrita às APIs erradas. As três pedem
correções diferentes, e quem recebe a mensagem em inglês do Google não tem
como distinguir.
"""

from urllib.parse import urlparse

import diagnostico


def erro_com_reason(reason: str, codigo: int = 403, servico: str = "", ajuda: str = "") -> dict:
    """Monta um corpo de erro no formato da API nova."""
    detalhes = [{
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": reason,
        "domain": "googleapis.com",
        "metadata": {"service": servico} if servico else {},
    }]
    if ajuda:
        detalhes.append({
            "@type": "type.googleapis.com/google.rpc.Help",
            "links": [{"description": "Ativação", "url": ajuda}],
        })
    return {"error": {
        "code": codigo, "status": "PERMISSION_DENIED",
        "message": "mensagem do Google", "details": detalhes,
    }}


# ---------------------------------------------------------------------------
# Classificação pelo identificador estável
# ---------------------------------------------------------------------------

def test_cada_reason_conhecido_vira_a_causa_correta():
    esperado = {
        "SERVICE_DISABLED": "servico_desativado",
        "BILLING_DISABLED": "faturamento_desativado",
        "API_KEY_INVALID": "chave_invalida",
        "API_KEY_SERVICE_BLOCKED": "chave_restrita_por_api",
        "API_KEY_HTTP_REFERRER_BLOCKED": "chave_restrita_por_origem",
        "API_KEY_IP_ADDRESS_BLOCKED": "chave_restrita_por_origem",
        "RATE_LIMIT_EXCEEDED": "cota_esgotada",
        "CONSUMER_SUSPENDED": "conta_suspensa",
    }
    for reason, causa in esperado.items():
        diag = diagnostico.diagnosticar(403, erro_com_reason(reason))
        assert diag["causa"] == causa, f"{reason} classificado como {diag['causa']}"


def test_o_mesmo_403_produz_causas_diferentes():
    """
    O ponto do módulo. Sem o `reason`, os três casos abaixo chegariam ao
    usuário como a mesma mensagem genérica de permissão negada.
    """
    causas = {
        diagnostico.diagnosticar(403, erro_com_reason(r))["causa"]
        for r in ("SERVICE_DISABLED", "BILLING_DISABLED", "API_KEY_SERVICE_BLOCKED")
    }
    assert len(causas) == 3


def test_reason_prevalece_sobre_o_codigo_http():
    """Um 403 cujo reason é de cota deve ser tratado como cota."""
    diag = diagnostico.diagnosticar(403, erro_com_reason("RATE_LIMIT_EXCEEDED"))
    assert diag["causa"] == "cota_esgotada"


def test_reason_desconhecido_cai_no_codigo_http():
    """A API pode introduzir reasons novos — o programa não pode quebrar."""
    diag = diagnostico.diagnosticar(429, erro_com_reason("REASON_QUE_AINDA_NAO_EXISTE", 429))
    assert diag["causa"] == "cota_esgotada"


# ---------------------------------------------------------------------------
# Link de correção
# ---------------------------------------------------------------------------

def test_link_de_ajuda_da_api_tem_prioridade():
    """
    O link que a API manda já vem com o id do projeto afetado. Qualquer página
    genérica nossa obrigaria o usuário a achar o projeto certo sozinho.
    """
    url = "https://console.cloud.google.com/apis/api/places.googleapis.com/overview?project=99"
    diag = diagnostico.diagnosticar(403, erro_com_reason("SERVICE_DISABLED", ajuda=url))
    assert diag["url"] == url


def test_sem_link_da_api_usa_a_pagina_do_servico():
    diag = diagnostico.diagnosticar(
        403, erro_com_reason("SERVICE_DISABLED", servico="geocoding-backend.googleapis.com")
    )
    assert diag["url"] == diagnostico.URL_GEOCODING


def test_sem_servico_conhecido_usa_a_pagina_padrao_da_causa():
    diag = diagnostico.diagnosticar(403, erro_com_reason("BILLING_DISABLED"))
    assert diag["url"] == diagnostico.URL_FATURAMENTO


def test_titulo_nomeia_o_servico_desativado():
    diag = diagnostico.diagnosticar(
        403, erro_com_reason("SERVICE_DISABLED", servico="places.googleapis.com")
    )
    assert "Places API (New)" in diag["titulo"]


def test_link_malformado_e_ignorado():
    corpo = {"error": {"code": 403, "details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED"},
        {"@type": "type.googleapis.com/google.rpc.Help", "links": [{"url": "javascript:alert(1)"}]},
    ]}}
    diag = diagnostico.diagnosticar(403, corpo)
    assert diag["url"].startswith("https://")


# ---------------------------------------------------------------------------
# Corpo ausente ou incompleto
# ---------------------------------------------------------------------------

def test_sem_corpo_algum_usa_o_codigo_http():
    assert diagnostico.diagnosticar(403, None)["causa"] == "servico_desativado"
    assert diagnostico.diagnosticar(429, None)["causa"] == "cota_esgotada"
    assert diagnostico.diagnosticar(400, None)["causa"] == "requisicao_invalida"
    assert diagnostico.diagnosticar(418, None)["causa"] == "desconhecido"


def test_detalhes_malformados_nao_quebram():
    for detalhes in ([], None, ["texto solto"], [{"sem": "tipo"}]):
        corpo = {"error": {"code": 403, "message": "x", "details": detalhes}}
        assert diagnostico.diagnosticar(403, corpo)["causa"]


def test_texto_da_mensagem_e_o_ultimo_recurso():
    """
    A API nem sempre manda `details`. Nesses casos o texto é tudo que há —
    usado só como desempate, nunca como critério principal.
    """
    def so_mensagem(msg, codigo=400):
        return {"error": {"code": codigo, "message": msg}}

    assert diagnostico.diagnosticar(
        400, so_mensagem("API key not valid. Please pass a valid API key.")
    )["causa"] == "chave_invalida"

    assert diagnostico.diagnosticar(
        403, so_mensagem("This API method requires billing to be enabled.")
    )["causa"] == "faturamento_desativado"


def test_mensagem_original_e_sempre_preservada():
    corpo = {"error": {"code": 400, "message": "detalhe cru do Google"}}
    assert diagnostico.diagnosticar(400, corpo)["mensagem_original"] == "detalhe cru do Google"


# ---------------------------------------------------------------------------
# API legada e Geocoding
# ---------------------------------------------------------------------------

def test_legado_classifica_pelo_texto_disponivel():
    assert diagnostico.diagnosticar_legado(
        "REQUEST_DENIED", "You must enable Billing on the project"
    )["causa"] == "faturamento_desativado"

    assert diagnostico.diagnosticar_legado(
        "REQUEST_DENIED", "This API project is not authorized to use this API"
    )["causa"] == "servico_desativado"

    assert diagnostico.diagnosticar_legado("OVER_QUERY_LIMIT")["causa"] == "cota_esgotada"
    assert diagnostico.diagnosticar_legado("INVALID_REQUEST")["causa"] == "requisicao_invalida"


def test_request_denied_sem_texto_assume_chave():
    """Sem detalhe não há como distinguir; a chave é o mais barato de conferir."""
    assert diagnostico.diagnosticar_legado("REQUEST_DENIED")["causa"] == "chave_invalida"


def test_nota_da_places_legada_e_acrescentada_quando_pedida():
    com_nota = diagnostico.diagnosticar_legado("REQUEST_DENIED", places_legada=True)
    sem_nota = diagnostico.diagnosticar_legado("REQUEST_DENIED", places_legada=False)

    assert "USAR_PLACES_NOVA" in " ".join(com_nota["correcao"])
    assert "USAR_PLACES_NOVA" not in " ".join(sem_nota["correcao"])


def test_status_desconhecido_preserva_o_valor_recebido():
    diag = diagnostico.diagnosticar_legado("ALGO_NOVO")
    assert diag["causa"] == "desconhecido"
    assert "ALGO_NOVO" in diag["mensagem_original"]


# ---------------------------------------------------------------------------
# A partir de exceções
# ---------------------------------------------------------------------------

def test_de_excecao_reaproveita_o_diagnostico_do_erro_api():
    from clientes import ErroAPI

    original = diagnostico.diagnosticar(403, erro_com_reason("BILLING_DISABLED"))
    assert diagnostico.de_excecao(ErroAPI("x", original)) is original


def test_de_excecao_classifica_falha_de_rede():
    assert diagnostico.de_excecao(ConnectionError("sem rede"))["causa"] == "sem_conexao"


def test_de_excecao_com_erro_qualquer_preserva_o_texto():
    diag = diagnostico.de_excecao(ValueError("algo estranho"))
    assert diag["causa"] == "desconhecido"
    assert "algo estranho" in diag["mensagem_original"]


# ---------------------------------------------------------------------------
# Consistência do catálogo
# ---------------------------------------------------------------------------

def test_toda_causa_tem_titulo_explicacao_correcao():
    for nome, causa in diagnostico.CAUSAS.items():
        assert causa["titulo"].strip(), nome
        assert causa["explicacao"].strip(), nome
        assert causa["correcao"], nome
        assert all(passo.strip() for passo in causa["correcao"]), nome


def test_todo_reason_mapeado_aponta_para_uma_causa_existente():
    for reason, causa in diagnostico.POR_REASON.items():
        assert causa in diagnostico.CAUSAS, f"{reason} aponta para causa inexistente"


def test_todo_fallback_http_aponta_para_uma_causa_existente():
    for codigo, causa in diagnostico.POR_STATUS_HTTP.items():
        assert causa in diagnostico.CAUSAS, f"HTTP {codigo} aponta para causa inexistente"


def test_urls_das_causas_sao_https_e_do_google():
    permitidos = {"console.cloud.google.com", "developers.google.com"}
    for nome, causa in diagnostico.CAUSAS.items():
        if not causa["url"]:
            continue
        endereco = urlparse(causa["url"])
        assert endereco.scheme == "https", nome
        assert endereco.netloc in permitidos, nome


def test_correcao_nunca_modifica_o_catalogo():
    """
    A nota da API legada é acrescentada à lista de correção. Se a lista fosse
    a do catálogo, a nota grudaria em todos os diagnósticos seguintes.
    """
    antes = len(diagnostico.CAUSAS["chave_invalida"]["correcao"])
    diagnostico.diagnosticar_legado("REQUEST_DENIED", places_legada=True)
    diagnostico.diagnosticar_legado("REQUEST_DENIED", places_legada=True)
    assert len(diagnostico.CAUSAS["chave_invalida"]["correcao"]) == antes


# ---------------------------------------------------------------------------
# Apresentação
# ---------------------------------------------------------------------------

def test_texto_completo_traz_passos_pagina_e_mensagem_original():
    diag = diagnostico.diagnosticar(
        403, erro_com_reason("SERVICE_DISABLED", servico="places.googleapis.com")
    )
    texto = diagnostico.texto_completo(diag)

    assert diag["titulo"] in texto
    assert "Como corrigir:" in texto
    assert "1. " in texto
    assert diag["url"] in texto
    assert "mensagem do Google" in texto


def test_resumo_e_uma_linha():
    diag = diagnostico.diagnosticar(403, erro_com_reason("BILLING_DISABLED"))
    assert "\n" not in diagnostico.resumo(diag)


def test_pagina_de_ativacao_so_vale_para_a_causa_de_ativacao():
    """
    O campo metadata.service vem preenchido em praticamente todo erro da API,
    inclusive nos de chave inválida. Usá-lo sem condição mandava o usuário para
    a página de ativação da API enquanto os passos falavam em credenciais.
    """
    diag = diagnostico.diagnosticar(
        400, erro_com_reason("API_KEY_INVALID", 400, servico="places.googleapis.com")
    )

    assert diag["causa"] == "chave_invalida"
    assert diag["url"] == diagnostico.URL_CREDENCIAIS
    assert diag["url"] != diagnostico.URL_PLACES_NOVA


def test_pagina_acompanha_os_passos_de_correcao_em_toda_causa():
    """A página aberta pelo botão precisa ser onde os passos mandam ir."""
    esperado = {
        "servico_desativado": diagnostico.URL_PLACES_NOVA,
        "faturamento_desativado": diagnostico.URL_FATURAMENTO,
        "chave_invalida": diagnostico.URL_CREDENCIAIS,
        "chave_restrita_por_api": diagnostico.URL_CREDENCIAIS,
        "chave_restrita_por_origem": diagnostico.URL_CREDENCIAIS,
        "cota_esgotada": diagnostico.URL_COTAS,
        "conta_suspensa": diagnostico.URL_FATURAMENTO,
    }
    for causa, url in esperado.items():
        assert diagnostico.CAUSAS[causa]["url"] == url, causa
