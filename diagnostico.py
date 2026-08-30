"""
diagnostico.py — Traduz erros da Google API em causa e correção.

A API devolve quase sempre o mesmo par para problemas de configuração:
PERMISSION_DENIED com uma mensagem em inglês. Só que as causas por trás são
bem diferentes e pedem correções diferentes — faturamento desativado, API não
ativada, chave restrita às APIs erradas — e o usuário não tem como distinguir.

O corpo de erro da API nova traz um bloco `details` com um identificador
legível por máquina em `reason`. É por ele que este módulo classifica: o texto
da mensagem é escrito em inglês e o Google o reescreve de tempos em tempos,
enquanto o `reason` é estável e documentado.

    {
      "error": {
        "code": 403,
        "status": "PERMISSION_DENIED",
        "message": "Places API (New) has not been used in project 123...",
        "details": [
          {"@type": ".../google.rpc.ErrorInfo",
           "reason": "SERVICE_DISABLED",
           "metadata": {"service": "places.googleapis.com",
                        "consumer": "projects/123"}},
          {"@type": ".../google.rpc.Help",
           "links": [{"url": "https://console.../apis/api/places.../overview?project=123"}]}
        ]
      }
    }

O bloco `Help`, quando vem, traz a página exata do projeto afetado — melhor do
que qualquer link genérico. É essa URL que aproveitamos.

Este módulo não importa nada do projeto: fica na base da pilha para poder ser
usado pelos clientes HTTP sem criar ciclo de importação.
"""

# ---------------------------------------------------------------------------
# Páginas do Console usadas nas correções
# ---------------------------------------------------------------------------

URL_PROJETO = "https://console.cloud.google.com/projectcreate"
URL_FATURAMENTO = "https://console.cloud.google.com/billing"
URL_PLACES_NOVA = "https://console.cloud.google.com/apis/library/places.googleapis.com"
URL_GEOCODING = "https://console.cloud.google.com/apis/library/geocoding-backend.googleapis.com"
URL_CREDENCIAIS = "https://console.cloud.google.com/apis/credentials"
URL_COTAS = "https://console.cloud.google.com/apis/api/places.googleapis.com/quotas"
URL_PRECOS = "https://developers.google.com/maps/billing-and-pricing/pricing"

# Nome amigável de cada serviço, para as mensagens
NOMES_DE_SERVICO = {
    "places.googleapis.com": "Places API (New)",
    "places-backend.googleapis.com": "Places API (legada)",
    "geocoding-backend.googleapis.com": "Geocoding API",
}

# Página de ativação de cada serviço
ATIVACAO_POR_SERVICO = {
    "places.googleapis.com": URL_PLACES_NOVA,
    "geocoding-backend.googleapis.com": URL_GEOCODING,
}


# ---------------------------------------------------------------------------
# Catálogo de causas
# ---------------------------------------------------------------------------

# Cada entrada: título de uma linha, por que acontece, como corrigir e a página
# de correção. A URL aqui é o padrão — quando a API manda a dela, ela ganha.
CAUSAS: dict[str, dict] = {
    "servico_desativado": {
        "titulo": "A API não está ativada neste projeto do Google Cloud",
        "explicacao": (
            "A chave é válida, mas o projeto ao qual ela pertence não tem a API "
            "ativada. Atenção ao nome: \"Places API\" e \"Places API (New)\" são "
            "produtos diferentes no Console, e este programa usa a (New)."
        ),
        "correcao": [
            "Abra a página de ativação da API.",
            "Confira, no topo, se o projeto selecionado é o mesmo da sua chave.",
            "Clique em ATIVAR e aguarde alguns instantes.",
        ],
        "url": URL_PLACES_NOVA,
    },
    "faturamento_desativado": {
        "titulo": "O projeto não tem faturamento ativo",
        "explicacao": (
            "O Google exige uma conta de faturamento vinculada ao projeto mesmo "
            "para quem vai usar somente a cota gratuita. Sem ela, todas as "
            "chamadas são recusadas. Ficando dentro da cota, não há cobrança."
        ),
        "correcao": [
            "Abra a página de faturamento do Google Cloud.",
            "Vincule uma conta de faturamento ao projeto da sua chave.",
            "Repita a busca — a liberação costuma valer em poucos minutos.",
        ],
        "url": URL_FATURAMENTO,
    },
    "chave_invalida": {
        "titulo": "A chave de API não é válida",
        "explicacao": (
            "O Google não reconheceu a chave. Costuma ser colagem incompleta, "
            "espaço sobrando, ou uma chave que foi apagada do projeto. Uma chave "
            "do Google Maps começa com \"AIza\" e tem 39 caracteres."
        ),
        "correcao": [
            "Abra a página de credenciais e copie a chave de novo, inteira.",
            "Cole no campo de chave e clique em Testar.",
            "Se ela não estiver mais na lista, crie uma nova.",
        ],
        "url": URL_CREDENCIAIS,
    },
    "chave_restrita_por_api": {
        "titulo": "A chave está restrita a outras APIs",
        "explicacao": (
            "A chave existe e o projeto está certo, mas nas Restrições de API "
            "ela não inclui a API que este programa usa. O erro é o mesmo de uma "
            "chave inválida, o que costuma despistar."
        ),
        "correcao": [
            "Abra a página de credenciais e clique na sua chave.",
            "Em Restrições de API, marque Places API (New) e Geocoding API.",
            "Salve e repita a busca.",
        ],
        "url": URL_CREDENCIAIS,
    },
    "chave_restrita_por_origem": {
        "titulo": "A chave está restrita a outros sites ou endereços de IP",
        "explicacao": (
            "A chave tem restrição de aplicativo por referenciador HTTP ou por "
            "endereço IP, e a máquina que fez a chamada está fora da lista. "
            "Restrições desse tipo servem a sites e servidores fixos, não a um "
            "programa instalado em vários computadores."
        ),
        "correcao": [
            "Abra a página de credenciais e clique na sua chave.",
            "Em Restrições de aplicativo, escolha Nenhuma.",
            "Mantenha as Restrições de API — são elas que protegem a chave aqui.",
        ],
        "url": URL_CREDENCIAIS,
    },
    "cota_esgotada": {
        "titulo": "A cota da API foi esgotada",
        "explicacao": (
            "O limite de chamadas do projeto foi atingido. Pode ser a cota "
            "gratuita mensal ou um teto definido por você no Console."
        ),
        "correcao": [
            "Reduza TERMOS_DE_BUSCA ou MAX_PAGINAS em config.py.",
            "Use a aba Calibrar termos para descobrir quais termos são dispensáveis.",
            "Se o limite for seu, ajuste-o na página de cotas do projeto.",
        ],
        "url": URL_COTAS,
    },
    "conta_suspensa": {
        "titulo": "A conta ou o projeto está suspenso",
        "explicacao": (
            "O Google bloqueou o projeto ou a conta de faturamento. Costuma ser "
            "pagamento pendente ou verificação de identidade em aberto."
        ),
        "correcao": [
            "Abra a página de faturamento e verifique os avisos.",
            "Regularize o que estiver pendente.",
        ],
        "url": URL_FATURAMENTO,
    },
    "requisicao_invalida": {
        "titulo": "A API recusou a requisição",
        "explicacao": (
            "Algum parâmetro foi rejeitado. Se você alterou config.py "
            "recentemente, o valor novo é o suspeito mais provável."
        ),
        "correcao": [
            "Confira as alterações recentes em config.py.",
            "Verifique se o raio está entre 1 e 50.000 metros.",
        ],
        "url": "",
    },
    "sem_conexao": {
        "titulo": "Sem conexão com a internet",
        "explicacao": "Não foi possível alcançar os servidores do Google.",
        "correcao": [
            "Verifique sua conexão.",
            "Se estiver em rede corporativa, confirme com o TI se "
            "googleapis.com está liberado.",
        ],
        "url": "",
    },
    "desconhecido": {
        "titulo": "Erro não identificado na API do Google",
        "explicacao": (
            "Este programa não reconheceu a causa. A mensagem original do "
            "Google, abaixo, é o melhor ponto de partida."
        ),
        "correcao": [
            "Confira a mensagem original.",
            "Rode pelo terminal com -v para ver os detalhes da chamada.",
        ],
        "url": "",
    },
}

# Identificadores de `reason` da API, mapeados para as causas acima.
# São valores documentados e estáveis — ao contrário do texto da mensagem.
POR_REASON = {
    "SERVICE_DISABLED": "servico_desativado",
    "BILLING_DISABLED": "faturamento_desativado",
    "API_KEY_INVALID": "chave_invalida",
    "API_KEY_SERVICE_BLOCKED": "chave_restrita_por_api",
    "API_KEY_HTTP_REFERRER_BLOCKED": "chave_restrita_por_origem",
    "API_KEY_IP_ADDRESS_BLOCKED": "chave_restrita_por_origem",
    "API_KEY_ANDROID_APP_BLOCKED": "chave_restrita_por_origem",
    "API_KEY_IOS_APP_BLOCKED": "chave_restrita_por_origem",
    "RATE_LIMIT_EXCEEDED": "cota_esgotada",
    "RESOURCE_QUOTA_EXCEEDED": "cota_esgotada",
    "CONSUMER_SUSPENDED": "conta_suspensa",
    "ACCOUNT_STATE_INVALID": "conta_suspensa",
    "CONSUMER_INVALID": "conta_suspensa",
}

# Último recurso, quando não veio `reason` algum no corpo do erro.
POR_STATUS_HTTP = {
    400: "requisicao_invalida",
    401: "chave_invalida",
    403: "servico_desativado",
    429: "cota_esgotada",
}


# ---------------------------------------------------------------------------
# Montagem do diagnóstico
# ---------------------------------------------------------------------------

def _montar(causa: str, mensagem_original: str = "", url: str = "", servico: str = "") -> dict:
    """Compõe o diagnóstico a partir do catálogo, aplicando os ajustes do caso."""
    base = CAUSAS.get(causa, CAUSAS["desconhecido"])

    titulo = base["titulo"]
    if causa == "servico_desativado" and servico:
        nome = NOMES_DE_SERVICO.get(servico, servico)
        titulo = f"A {nome} não está ativada neste projeto do Google Cloud"

    # A URL vinda da própria API aponta para o projeto exato; a nossa é genérica.
    # A página de ativação do serviço só serve quando o problema É a ativação:
    # o campo metadata.service vem preenchido em praticamente todo erro, e usá-lo
    # sem essa condição mandava quem tinha chave inválida para a página de
    # ativação da API, em desacordo com os próprios passos de correção.
    if url:
        pagina = url
    elif causa == "servico_desativado" and servico in ATIVACAO_POR_SERVICO:
        pagina = ATIVACAO_POR_SERVICO[servico]
    else:
        pagina = base["url"]

    return {
        "causa": causa,
        "titulo": titulo,
        "explicacao": base["explicacao"],
        "correcao": list(base["correcao"]),
        "url": pagina,
        "mensagem_original": mensagem_original,
    }


def _extrair_detalhes(erro: dict) -> tuple[str, str, str]:
    """
    Lê o bloco `details` do erro.

    Returns:
        (reason, servico, url_de_ajuda) — cada um "" quando ausente.
    """
    reason = servico = url_ajuda = ""

    for detalhe in erro.get("details", []) or []:
        if not isinstance(detalhe, dict):
            continue
        tipo = str(detalhe.get("@type", ""))

        if tipo.endswith("ErrorInfo"):
            reason = str(detalhe.get("reason", "")) or reason
            metadados = detalhe.get("metadata") or {}
            if isinstance(metadados, dict):
                servico = str(metadados.get("service", "")) or servico

        elif tipo.endswith("Help"):
            for link in detalhe.get("links", []) or []:
                if isinstance(link, dict) and str(link.get("url", "")).startswith("https://"):
                    url_ajuda = link["url"]
                    break

    return reason, servico, url_ajuda


def diagnosticar(codigo_http: int, corpo: dict | None) -> dict:
    """
    Classifica um erro da Places API (New).

    Args:
        codigo_http: Código HTTP da resposta.
        corpo: JSON decodificado, ou None se a resposta não era JSON.

    Returns:
        Dict com causa, titulo, explicacao, correcao, url e mensagem_original.
    """
    erro = (corpo or {}).get("error") or {}
    mensagem = str(erro.get("message", "")).strip()

    reason, servico, url_ajuda = _extrair_detalhes(erro)

    if reason in POR_REASON:
        return _montar(POR_REASON[reason], mensagem, url_ajuda, servico)

    # Sem `reason` utilizável: o texto vira o último indício disponível.
    # Usado só nesta posição, como desempate, e não como critério principal.
    minuscula = mensagem.lower()
    if "billing" in minuscula:
        return _montar("faturamento_desativado", mensagem, url_ajuda, servico)
    if "api key not valid" in minuscula or "api key expired" in minuscula:
        return _montar("chave_invalida", mensagem, url_ajuda, servico)
    if "has not been used in project" in minuscula or "is disabled" in minuscula:
        return _montar("servico_desativado", mensagem, url_ajuda, servico)

    causa = POR_STATUS_HTTP.get(codigo_http, "desconhecido")
    return _montar(causa, mensagem, url_ajuda, servico)


NOTA_PLACES_LEGADA = (
    "Se o projeto do Google Cloud foi criado a partir de 01/03/2025, ele não "
    "consegue ativar a Places API legada. Defina USAR_PLACES_NOVA = True em "
    "config.py."
)


def diagnosticar_legado(
    status: str, mensagem: str = "", places_legada: bool = False
) -> dict:
    """
    Classifica um erro da API legada e da Geocoding API.

    Essas devolvem HTTP 200 com um campo "status" no corpo e, às vezes, um
    "error_message" explicativo. Não há `details` nem `reason`: a classificação
    depende do texto, que é o que existe.

    Args:
        status: Valor do campo "status" da resposta.
        mensagem: Conteúdo de "error_message", quando presente.
    """
    minuscula = (mensagem or "").lower()

    if status == "REQUEST_DENIED":
        if "billing" in minuscula:
            diag = _montar("faturamento_desativado", mensagem)
        elif "not authorized" in minuscula or "not enabled" in minuscula:
            diag = _montar("servico_desativado", mensagem)
        else:
            # Sem detalhe, chave e ativação produzem a mesma resposta; a chave
            # é a hipótese mais provável e a mais barata de verificar.
            diag = _montar("chave_invalida", mensagem)

        if places_legada:
            diag["correcao"].append(NOTA_PLACES_LEGADA)
        return diag

    if status == "OVER_QUERY_LIMIT":
        return _montar("cota_esgotada", mensagem)
    if status == "INVALID_REQUEST":
        return _montar("requisicao_invalida", mensagem)

    return _montar("desconhecido", mensagem or f"Status retornado: {status}")


def de_falha_de_rede(mensagem: str) -> dict:
    """Diagnóstico para falha de conexão, que nem chega a produzir resposta."""
    return _montar("sem_conexao", mensagem)


def de_excecao(exc: BaseException) -> dict:
    """
    Extrai o diagnóstico de uma exceção, seja qual for a origem.

    ErroAPI já carrega o seu; falhas de conexão nunca chegaram a produzir
    resposta e são classificadas aqui; o resto vira "desconhecido", preservando
    o texto original.
    """
    diag = getattr(exc, "diagnostico", None)
    if diag:
        return diag
    if isinstance(exc, ConnectionError):
        return de_falha_de_rede(str(exc))
    return _montar("desconhecido", str(exc))


# ---------------------------------------------------------------------------
# Apresentação
# ---------------------------------------------------------------------------

def resumo(diag: dict) -> str:
    """Uma linha, para mensagem de exceção e log."""
    return diag["titulo"]


def texto_completo(diag: dict) -> str:
    """Bloco explicativo para exibir no terminal ou numa caixa de diálogo."""
    linhas = [diag["titulo"], "", diag["explicacao"], "", "Como corrigir:"]
    linhas += [f"  {i}. {passo}" for i, passo in enumerate(diag["correcao"], start=1)]

    if diag["url"]:
        linhas += ["", f"Página: {diag['url']}"]
    if diag["mensagem_original"]:
        linhas += ["", f"Mensagem original do Google: {diag['mensagem_original']}"]

    return "\n".join(linhas)
