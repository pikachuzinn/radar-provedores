"""
Testes de buscador.py — orquestração da busca.

O que é específico de cada geração da Places API (forma da requisição,
cabeçalhos, tradução de payload) é testado em test_clientes.py. Aqui se
verifica o que vale para as duas: geocodificação, paginação, deduplicação,
cache, distância e filtro de raio.
"""

import pytest

import buscador as mod
from buscador import BuscadorProvedores, ErroAPI, ErroLocalizacao
from conftest import (
    LAT_CENTRO,
    LNG_CENTRO,
    PREFIXO_DETALHES_NOVO,
    RespostaFalsa,
    entrada_cache,
    detalhes_legado,
    item_legado,
    lugar_novo,
    resposta_busca_nova,
)
from config import (
    URL_DETALHES,
    URL_GEOCODING,
    URL_PLACES_BUSCA,
    URL_PLACES_DETALHES,
    URL_TEXT_SEARCH,
)


def rotas_novas(lugares, paginas=None):
    """Rotas da API nova. `paginas` permite encadear respostas paginadas."""
    return {URL_PLACES_BUSCA: paginas or RespostaFalsa(resposta_busca_nova(lugares))}


def rotas_legadas(itens):
    return {
        URL_TEXT_SEARCH: RespostaFalsa({"status": "OK", "results": itens}),
        URL_DETALHES: RespostaFalsa(detalhes_legado()),
    }


# ---------------------------------------------------------------------------
# Geocodificação
# ---------------------------------------------------------------------------

def test_geocodificar_devolve_coordenadas(montar, payload_geocoding):
    b, _ = montar({URL_GEOCODING: RespostaFalsa(payload_geocoding)})
    assert b.geocodificar("Florianópolis, SC") == (LAT_CENTRO, LNG_CENTRO)


def test_geocodificar_sem_resultado_levanta_erro_localizacao(montar):
    b, _ = montar({URL_GEOCODING: RespostaFalsa({"status": "ZERO_RESULTS"})})
    with pytest.raises(ErroLocalizacao, match="não encontrado"):
        b.geocodificar("endereço inexistente")


def test_geocodificar_chave_invalida_levanta_erro_api(montar):
    b, _ = montar({URL_GEOCODING: RespostaFalsa({"status": "REQUEST_DENIED"})})
    with pytest.raises(ErroAPI, match="inválida ou sem permissão"):
        b.geocodificar("Florianópolis, SC")


def test_geocodificar_status_desconhecido_levanta_erro_api(montar):
    b, _ = montar({URL_GEOCODING: RespostaFalsa({"status": "OVER_QUERY_LIMIT"})})
    with pytest.raises(ErroAPI, match="OVER_QUERY_LIMIT"):
        b.geocodificar("Florianópolis, SC")


def test_geocodificar_sem_rede_vira_connection_error(montar):
    import requests
    b, _ = montar({URL_GEOCODING: RespostaFalsa({}, erro=requests.ConnectionError())})
    with pytest.raises(ConnectionError, match="Sem conexão"):
        b.geocodificar("Florianópolis, SC")


def test_chave_vazia_e_rejeitada():
    with pytest.raises(ValueError):
        BuscadorProvedores(api_key="")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_cache_hit_nao_chama_a_api(montar, sem_pausa):
    b, sessao = montar(
        {URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Da API", -27.6, -48.5))},
        cache_inicial={"novo:pid1": entrada_cache({"nome": "Do cache"})},
    )

    assert b.obter_detalhes("pid1") == {"nome": "Do cache"}
    assert sessao.chamadas == []


def test_cache_hit_nao_dorme(montar, sem_pausa):
    """
    A pausa de rate limit só faz sentido antes de uma chamada real.
    Dormir em cache hit anula o ganho de desempenho do próprio cache.
    """
    b, _ = montar({}, cache_inicial={"novo:pid1": entrada_cache({"nome": "Do cache"})})
    b.obter_detalhes("pid1")
    assert sem_pausa == []


def test_chamada_real_respeita_a_pausa(montar, sem_pausa):
    b, _ = montar({URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Alfa", -27.6, -48.5))})
    b.obter_detalhes("pid1")
    assert sem_pausa == [mod.INTERVALO_ENTRE_CHAMADAS]


def test_cache_antigo_nao_e_lido_como_registro_normalizado(montar, sem_pausa):
    """
    Cenário real da migração: um .cache_detalhes.json gravado pela versão
    anterior guarda o payload CRU do Google sob o place_id sem prefixo. Servir
    esse conteúdo como registro normalizado produziria lixo — o payload cru
    tem "name"/"website", e não "nome"/"site". A chave do cache passou a
    incluir a geração da API justamente para invalidar essas entradas.
    """
    cache_da_versao_antiga = {"pid1": {"name": "Payload cru legado", "website": "https://x"}}

    b, sessao = montar(
        {URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Da API nova", -27.6, -48.5))},
        usar_nova=True,
        cache_inicial=cache_da_versao_antiga,
    )

    registro = b.obter_detalhes("pid1")

    assert registro["nome"] == "Da API nova"   # veio da API, não do cache velho
    assert "name" not in registro              # nenhum campo cru vazou
    assert len(sessao.chamadas) == 1


def test_cache_novo_e_reaproveitado(montar, sem_pausa):
    """Contraprova: com a chave da geração correta, o cache é usado."""
    b, sessao = montar(
        {URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Da API nova", -27.6, -48.5))},
        usar_nova=True,
        cache_inicial={"novo:pid1": entrada_cache({"nome": "Do cache novo"})},
    )

    assert b.obter_detalhes("pid1")["nome"] == "Do cache novo"
    assert sessao.chamadas == []


def test_gravacao_do_cache_e_em_lote(montar, sem_pausa, monkeypatch):
    """
    Gravar a cada place_id reescreveria o JSON inteiro N vezes (custo O(n²)).
    Com 3 consultas e intervalo de 25, o disco só é tocado na gravação final.
    """
    gravacoes: list[int] = []
    monkeypatch.setattr(mod, "salvar_cache", lambda dados, caminho: gravacoes.append(len(dados)))
    monkeypatch.setattr(mod, "INTERVALO_GRAVACAO_CACHE", 25)

    b, _ = montar({URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid", "Alfa", -27.6, -48.5))})
    for i in range(3):
        b.obter_detalhes(f"pid{i}")

    assert gravacoes == []          # nada gravado ainda
    b.gravar_cache()
    assert gravacoes == [3]         # uma única gravação, com as 3 entradas


def test_gravacao_periodica_dispara_no_intervalo(montar, sem_pausa, monkeypatch):
    """Buscas longas não podem perder o cache inteiro se forem interrompidas."""
    gravacoes: list[int] = []
    monkeypatch.setattr(mod, "salvar_cache", lambda dados, caminho: gravacoes.append(len(dados)))
    monkeypatch.setattr(mod, "INTERVALO_GRAVACAO_CACHE", 2)

    b, _ = montar({URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid", "Alfa", -27.6, -48.5))})
    for i in range(5):
        b.obter_detalhes(f"pid{i}")

    assert gravacoes == [2, 4]


def test_gravar_cache_sem_pendencia_nao_escreve(montar, monkeypatch):
    gravacoes: list = []
    monkeypatch.setattr(mod, "salvar_cache", lambda d, c: gravacoes.append(d))

    b, _ = montar({})
    b.gravar_cache()
    b.gravar_cache()

    assert gravacoes == []


def test_falha_nos_detalhes_nao_interrompe(montar, sem_pausa):
    """Um registro empobrecido é melhor do que uma busca abortada."""
    from conftest import erro_novo
    b, _ = montar({URL_PLACES_DETALHES: erro_novo(500, "INTERNAL")})
    assert b.obter_detalhes("pid1") == {}


# ---------------------------------------------------------------------------
# Place Details: a diferença central entre as duas gerações
# ---------------------------------------------------------------------------

def test_api_nova_nao_chama_place_details_durante_a_busca(montar, sem_pausa, monkeypatch):
    """
    O ganho da migração. Na API legada, cada estabelecimento custava uma
    chamada extra de Place Details; na nova, o field mask já traz tudo.
    """
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    lugares = [lugar_novo(f"pid{i}", f"Provedor {i}", -27.60, -48.55) for i in range(10)]
    b, sessao = montar(rotas_novas(lugares), usar_nova=True)

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert len(provedores) == 10
    assert sessao.chamadas_para(PREFIXO_DETALHES_NOVO) == []
    assert len(sessao.chamadas_para(URL_PLACES_BUSCA)) == 1
    # E o contato veio junto na busca, sem chamada extra
    assert provedores[0]["telefone"] != ""


def test_api_legada_precisa_de_uma_chamada_por_estabelecimento(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    itens = [item_legado(f"pid{i}", f"Provedor {i}", -27.60, -48.55) for i in range(10)]
    b, sessao = montar(rotas_legadas(itens), usar_nova=False)

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert len(provedores) == 10
    assert len(sessao.chamadas_para(URL_DETALHES)) == 10
    assert provedores[0]["telefone"] == "(48) 3333-0000"


def test_detalhes_legados_nao_apagam_dados_da_busca(montar, sem_pausa, monkeypatch):
    """A mesclagem preserva o que veio da busca quando o Details vem incompleto."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    itens = [item_legado("pid1", "Nome Da Busca", -27.60, -48.55)]
    rotas = {
        URL_TEXT_SEARCH: RespostaFalsa({"status": "OK", "results": itens}),
        # Details sem nome nem coordenadas
        URL_DETALHES: RespostaFalsa({"status": "OK", "result": {"website": "https://x.example.com"}}),
    }
    b, _ = montar(rotas, usar_nova=False)

    provedor = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)[0]

    assert provedor["nome"] == "Nome Da Busca"
    assert provedor["site"] == "https://x.example.com"
    assert provedor["latitude"] == -27.60


# ---------------------------------------------------------------------------
# Paginação
# ---------------------------------------------------------------------------

def test_paginacao_segue_o_token_ate_acabar(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    paginas = [
        RespostaFalsa(resposta_busca_nova([lugar_novo("a", "A", -27.6, -48.5)], "TOKEN1")),
        RespostaFalsa(resposta_busca_nova([lugar_novo("b", "B", -27.6, -48.5)])),
    ]
    b, sessao = montar(rotas_novas(None, paginas=paginas), usar_nova=True)

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert [p["place_id"] for p in provedores] == ["a", "b"]
    assert sessao.chamadas[1].corpo["pageToken"] == "TOKEN1"


def test_paginacao_respeita_o_maximo_de_paginas(montar, sem_pausa, monkeypatch):
    """A API devolve no máximo 60 resultados (3 páginas de 20)."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "MAX_PAGINAS", 3)

    # Token infinito: sem o teto, o laço nunca terminaria
    sempre_com_token = RespostaFalsa(
        resposta_busca_nova([lugar_novo("pid", "Alfa", -27.6, -48.5)], "TOKEN")
    )
    b, sessao = montar({URL_PLACES_BUSCA: sempre_com_token}, usar_nova=True)

    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert len(sessao.chamadas_para(URL_PLACES_BUSCA)) == 3


def test_api_nova_nao_espera_entre_paginas(montar, sem_pausa, monkeypatch):
    """A espera de 2s antes de usar o token era exigência da API legada."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    paginas = [
        RespostaFalsa(resposta_busca_nova([lugar_novo("a", "A", -27.6, -48.5)], "TOKEN1")),
        RespostaFalsa(resposta_busca_nova([lugar_novo("b", "B", -27.6, -48.5)])),
    ]
    b, _ = montar(rotas_novas(None, paginas=paginas), usar_nova=True)
    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert sem_pausa == []   # nenhuma pausa: nem paginação, nem Place Details


def test_api_legada_espera_antes_de_usar_o_token(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    paginas = [
        RespostaFalsa({"status": "OK", "results": [item_legado("a", "A", -27.6, -48.5)],
                       "next_page_token": "TOKEN1"}),
        RespostaFalsa({"status": "OK", "results": [item_legado("b", "B", -27.6, -48.5)]}),
    ]
    b, _ = montar({URL_TEXT_SEARCH: paginas, URL_DETALHES: RespostaFalsa(detalhes_legado())},
                  usar_nova=False)
    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert mod.BuscadorProvedores  # sanidade
    assert 2.0 in sem_pausa


# ---------------------------------------------------------------------------
# Deduplicação, distância e raio
# ---------------------------------------------------------------------------

def test_deduplica_por_place_id(montar, sem_pausa, monkeypatch):
    """O mesmo provedor aparece em vários termos — deve entrar uma única vez."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo a", "termo b"])

    b, _ = montar(rotas_novas([lugar_novo("pid1", "Alfa", -27.60, -48.55)]))
    assert len(b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)) == 1


def test_calcula_distancia_do_centro(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    b, _ = montar(rotas_novas([lugar_novo("pid1", "Alfa", -26.3044, -48.8487)]))  # Joinville
    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert provedores[0]["distancia_km"] == pytest.approx(146.6, abs=2.0)


def test_sem_coordenadas_distancia_fica_vazia_e_nao_zero(montar, sem_pausa, monkeypatch):
    """Zero numa planilha seria lido como 'no mesmo ponto do centro da busca'."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    sem_geo = {"id": "pid1", "displayName": {"text": "Sem geo"}}
    b, _ = montar(rotas_novas([sem_geo]))

    assert b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)[0]["distancia_km"] == ""


def test_raio_estrito_descarta_resultados_distantes(montar, sem_pausa, monkeypatch):
    """
    O raio da Places API é viés de relevância, não filtro: mesmo na API nova,
    locationBias.circle não impede resultados muito além do raio pedido.
    """
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "RAIO_ESTRITO", True)

    lugares = [
        lugar_novo("perto", "Alfa", -27.5960, -48.5490),   # ~100 m
        lugar_novo("longe", "Beta", -26.3044, -48.8487),   # ~146 km
    ]
    b, _ = montar(rotas_novas(lugares))

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)
    assert [p["place_id"] for p in provedores] == ["perto"]


def test_raio_estrito_descarta_antes_do_place_details(montar, sem_pausa, monkeypatch):
    """Na API legada, descartar antes do Details é economia direta de custo."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "RAIO_ESTRITO", True)

    itens = [
        item_legado("perto", "Alfa", -27.5960, -48.5490),
        item_legado("longe", "Beta", -26.3044, -48.8487),
    ]
    b, sessao = montar(rotas_legadas(itens), usar_nova=False)

    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert len(sessao.chamadas_para(URL_DETALHES)) == 1


def test_sem_raio_estrito_mantem_tudo(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "RAIO_ESTRITO", False)

    lugares = [
        lugar_novo("perto", "Alfa", -27.5960, -48.5490),
        lugar_novo("longe", "Beta", -26.3044, -48.8487),
    ]
    b, _ = montar(rotas_novas(lugares))

    assert len(b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)) == 2


# ---------------------------------------------------------------------------
# Resiliência e progresso
# ---------------------------------------------------------------------------

def test_falha_em_um_termo_nao_aborta_a_busca(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["ok", "quebrado"])

    from conftest import erro_novo
    contador = {"n": 0}
    ok = RespostaFalsa(resposta_busca_nova([lugar_novo("pid1", "Alfa", -27.6, -48.5)]))

    def alternar(chamada):
        contador["n"] += 1
        return ok if contador["n"] == 1 else erro_novo(429, "RESOURCE_EXHAUSTED")

    b, _ = montar({URL_PLACES_BUSCA: alternar})

    eventos: list[dict] = []
    provedores = b.buscar_todos(
        LAT_CENTRO, LNG_CENTRO, raio=5000, callback_progresso=eventos.append,
    )

    assert len(provedores) == 1
    assert any("Aviso ao buscar" in e["mensagem"] for e in eventos)

    # A interface precisa distinguir "nada encontrado" de "a busca falhou":
    # sem o campo `erro`, um problema de API viraria um silencioso zero.
    falhas = [e["erro"] for e in eventos if e["erro"]]
    assert len(falhas) == 1
    assert "Cota" in falhas[0]


def test_callback_de_progresso_recebe_todas_as_chaves(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    b, _ = montar(rotas_novas([lugar_novo("pid1", "Alfa", -27.6, -48.5)]))

    eventos: list[dict] = []
    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000, callback_progresso=eventos.append)

    esperadas = {"etapa", "total_etapas", "mensagem", "novos_provedores",
                 "total_acumulado", "erro"}
    assert all(esperadas <= set(e) for e in eventos)
    assert eventos[0]["novos_provedores"] is None   # etapa iniciando
    assert eventos[-1]["novos_provedores"] == 1     # etapa concluída
    assert all(e["erro"] is None for e in eventos)  # nenhuma falha neste cenário


def test_fecha_a_sessao_http(montar):
    b, sessao = montar({})
    b.fechar()
    assert sessao.fechada


# ---------------------------------------------------------------------------
# Instrumentação da sobreposição entre termos
# ---------------------------------------------------------------------------

def test_registra_os_ids_que_cada_termo_trouxe(montar, sem_pausa, monkeypatch):
    """
    O conjunto por termo precisa incluir os repetidos. Registrar só os inéditos
    daria todo o crédito ao primeiro termo e tornaria a medida dependente
    da ordem — exatamente o defeito que a análise existe para evitar.
    """
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo a", "termo b"])

    compartilhado = lugar_novo("comum", "Comum", -27.60, -48.55)
    exclusivo_b = lugar_novo("so_b", "Só do B", -27.61, -48.56)

    respostas = [
        RespostaFalsa(resposta_busca_nova([compartilhado])),
        RespostaFalsa(resposta_busca_nova([compartilhado, exclusivo_b])),
    ]
    b, _ = montar({URL_PLACES_BUSCA: respostas})

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert len(provedores) == 2                          # deduplicado no resultado
    assert b.ids_por_termo["termo a"] == {"comum"}
    assert b.ids_por_termo["termo b"] == {"comum", "so_b"}   # o repetido conta


def test_conta_as_requisicoes_gastas_por_termo(montar, sem_pausa, monkeypatch):
    """Sem isso não dá para estimar a economia de cortar um termo."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "MAX_PAGINAS", 3)

    paginas = [
        RespostaFalsa(resposta_busca_nova([lugar_novo("a", "A", -27.6, -48.5)], "T1")),
        RespostaFalsa(resposta_busca_nova([lugar_novo("b", "B", -27.6, -48.5)], "T2")),
        RespostaFalsa(resposta_busca_nova([lugar_novo("c", "C", -27.6, -48.5)])),
    ]
    b, _ = montar({URL_PLACES_BUSCA: paginas})
    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert b.requisicoes_por_termo == {"termo": 3}


def test_descartados_pelo_raio_nao_entram_na_analise(montar, sem_pausa, monkeypatch):
    """Não faz sentido creditar a um termo um resultado que foi jogado fora."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "RAIO_ESTRITO", True)

    lugares = [
        lugar_novo("perto", "Alfa", -27.5960, -48.5490),
        lugar_novo("longe", "Beta", -26.3044, -48.8487),
    ]
    b, _ = montar(rotas_novas(lugares))
    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert b.ids_por_termo["termo"] == {"perto"}


def test_instrumentacao_reinicia_a_cada_busca(montar, sem_pausa, monkeypatch):
    """Uma segunda busca não pode herdar os números da primeira."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    b, _ = montar(rotas_novas([lugar_novo("pid1", "Alfa", -27.6, -48.5)]))
    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)
    primeira = dict(b.ids_por_termo)

    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert b.ids_por_termo == primeira
    assert len(b.ids_por_termo) == 1


# ---------------------------------------------------------------------------
# Validade do cache
# ---------------------------------------------------------------------------

def test_entrada_de_cache_vencida_e_reconsultada(montar, sem_pausa):
    """
    As políticas da Places API isentam apenas o place_id das restrições de
    cache; nome, telefone e site não podem ser retidos sem prazo.
    """
    b, sessao = montar(
        {URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Da API", -27.6, -48.5))},
        cache_inicial={"novo:pid1": entrada_cache(
            {"nome": "Antigo"}, dias_atras=mod.CACHE_VALIDADE_DIAS + 1
        )},
    )

    assert b.obter_detalhes("pid1")["nome"] == "Da API"
    assert len(sessao.chamadas) == 1


def test_entrada_dentro_do_prazo_e_reaproveitada(montar, sem_pausa):
    b, sessao = montar(
        {URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Da API", -27.6, -48.5))},
        cache_inicial={"novo:pid1": entrada_cache(
            {"nome": "Ainda válido"}, dias_atras=mod.CACHE_VALIDADE_DIAS - 1
        )},
    )

    assert b.obter_detalhes("pid1")["nome"] == "Ainda válido"
    assert sessao.chamadas == []


def test_cache_sem_carimbo_de_tempo_e_descartado(montar, sem_pausa):
    """Entradas de versões anteriores não têm idade conhecida — não dá para confiar."""
    b, sessao = montar(
        {URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Da API", -27.6, -48.5))},
        cache_inicial={"novo:pid1": {"nome": "Sem carimbo"}},
    )

    assert b.obter_detalhes("pid1")["nome"] == "Da API"


def test_carimbo_corrompido_nao_quebra(montar, sem_pausa):
    b, _ = montar(
        {URL_PLACES_DETALHES: RespostaFalsa(lugar_novo("pid1", "Da API", -27.6, -48.5))},
        cache_inicial={"novo:pid1": {"salvo_em": "data-invalida", "dados": {"nome": "X"}}},
    )

    assert b.obter_detalhes("pid1")["nome"] == "Da API"


# ---------------------------------------------------------------------------
# Cancelamento cooperativo
# ---------------------------------------------------------------------------

def test_cancelar_interrompe_entre_termos_e_devolve_o_parcial(montar, sem_pausa, monkeypatch):
    """
    Numa interface gráfica o usuário desiste no meio. Parar entre termos evita
    gastar cota à toa, e o que já foi coletado continua válido.
    """
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["a", "b", "c"])

    b, sessao = montar(rotas_novas([lugar_novo("pid1", "Alfa", -27.6, -48.5)]))

    # Imita o clique em "Cancelar": a desistência chega enquanto a busca roda,
    # aqui logo depois que o primeiro termo termina.
    desistiu = {"sim": False}

    def ao_progredir(info):
        if info["novos_provedores"] is not None:
            desistiu["sim"] = True

    provedores = b.buscar_todos(
        LAT_CENTRO, LNG_CENTRO, raio=5000,
        callback_progresso=ao_progredir,
        deve_cancelar=lambda: desistiu["sim"],
    )

    assert b.cancelado is True
    assert len(provedores) == 1                                  # resultado parcial
    assert len(sessao.chamadas_para(URL_PLACES_BUSCA)) == 1      # só o primeiro termo


def test_cancelar_interrompe_entre_paginas(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "MAX_PAGINAS", 3)

    sempre_com_token = RespostaFalsa(
        resposta_busca_nova([lugar_novo("pid", "Alfa", -27.6, -48.5)], "TOKEN")
    )
    b, sessao = montar({URL_PLACES_BUSCA: sempre_com_token})

    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000, deve_cancelar=lambda: True)

    assert b.cancelado is True
    assert sessao.chamadas_para(URL_PLACES_BUSCA) == []


def test_sem_cancelamento_a_busca_roda_inteira(montar, sem_pausa, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["a", "b"])
    b, sessao = montar(rotas_novas([lugar_novo("pid1", "Alfa", -27.6, -48.5)]))

    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert b.cancelado is False
    assert len(sessao.chamadas_para(URL_PLACES_BUSCA)) == 2
