"""
Testes de buscador.py — geocodificação, busca, cache e normalização.

Nenhum teste toca a rede: a sessão HTTP é substituída pela SessaoFalsa
(ver conftest.py na raiz do projeto).
"""

import pytest

import buscador as mod
from buscador import BuscadorProvedores, ErroAPI, ErroLocalizacao
from conftest import LAT_CENTRO, LNG_CENTRO, RespostaFalsa, SessaoFalsa, item_bruto

CHAVE = "AIzaSyFAKE_CHAVE_DE_TESTE_123"


@pytest.fixture
def montar(tmp_path):
    """
    Devolve uma função que cria um buscador com sessão falsa e cache isolado.

    Uso:
        buscador, sessao = montar({URL_X: RespostaFalsa({...})})
    """
    criados: list[BuscadorProvedores] = []

    def _montar(rotas: dict, cache_inicial: dict | None = None):
        caminho = str(tmp_path / "cache.json")
        if cache_inicial is not None:
            from cache import salvar_cache
            salvar_cache(cache_inicial, caminho)

        b = BuscadorProvedores(api_key=CHAVE, caminho_cache=caminho)
        sessao = SessaoFalsa(rotas)
        b._sessao = sessao
        criados.append(b)
        return b, sessao

    yield _montar

    for b in criados:
        b.fechar()


# ---------------------------------------------------------------------------
# Geocodificação
# ---------------------------------------------------------------------------

def test_geocodificar_devolve_coordenadas(montar, urls, payload_geocoding):
    b, _ = montar({urls["geocoding"]: RespostaFalsa(payload_geocoding)})
    assert b.geocodificar("Florianópolis, SC") == (LAT_CENTRO, LNG_CENTRO)


def test_geocodificar_sem_resultado_levanta_erro_localizacao(montar, urls):
    b, _ = montar({urls["geocoding"]: RespostaFalsa({"status": "ZERO_RESULTS"})})
    with pytest.raises(ErroLocalizacao, match="não encontrado"):
        b.geocodificar("endereço inexistente")


def test_geocodificar_chave_invalida_levanta_erro_api(montar, urls):
    b, _ = montar({urls["geocoding"]: RespostaFalsa({"status": "REQUEST_DENIED"})})
    with pytest.raises(ErroAPI, match="inválida ou sem permissão"):
        b.geocodificar("Florianópolis, SC")


def test_geocodificar_status_desconhecido_levanta_erro_api(montar, urls):
    b, _ = montar({urls["geocoding"]: RespostaFalsa({"status": "OVER_QUERY_LIMIT"})})
    with pytest.raises(ErroAPI, match="OVER_QUERY_LIMIT"):
        b.geocodificar("Florianópolis, SC")


def test_falha_de_rede_vira_connection_error(montar, urls):
    import requests
    b, _ = montar({
        urls["geocoding"]: RespostaFalsa({}, erro=requests.ConnectionError())
    })
    with pytest.raises(ConnectionError, match="Sem conexão"):
        b.geocodificar("Florianópolis, SC")


# ---------------------------------------------------------------------------
# Cache de Place Details
# ---------------------------------------------------------------------------

def test_cache_hit_nao_chama_a_api(montar, urls, sem_pausa):
    b, sessao = montar(
        {urls["detalhes"]: RespostaFalsa({"status": "OK", "result": {"name": "X"}})},
        cache_inicial={"pid1": {"name": "Do cache"}},
    )

    assert b.obter_detalhes("pid1") == {"name": "Do cache"}
    assert sessao.chamadas == []


def test_cache_hit_nao_dorme(montar, urls, sem_pausa):
    """
    A pausa de rate limit só faz sentido antes de uma chamada real.
    Dormir em cache hit anula o ganho de desempenho do próprio cache.
    """
    b, _ = montar({}, cache_inicial={"pid1": {"name": "Do cache"}})
    b.obter_detalhes("pid1")
    assert sem_pausa == []


def test_chamada_real_respeita_a_pausa(montar, urls, sem_pausa, payload_detalhes):
    b, _ = montar({urls["detalhes"]: RespostaFalsa(payload_detalhes)})
    b.obter_detalhes("pid_novo")
    assert sem_pausa == [mod.INTERVALO_ENTRE_CHAMADAS]


def test_gravacao_do_cache_e_em_lote(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    """
    Gravar a cada place_id reescreveria o JSON inteiro N vezes (custo O(n²)).
    Com 3 consultas e intervalo de 25, o disco só é tocado na gravação final.
    """
    gravacoes: list[int] = []
    monkeypatch.setattr(mod, "salvar_cache", lambda dados, caminho: gravacoes.append(len(dados)))
    monkeypatch.setattr(mod, "INTERVALO_GRAVACAO_CACHE", 25)

    b, _ = montar({urls["detalhes"]: RespostaFalsa(payload_detalhes)})
    for i in range(3):
        b.obter_detalhes(f"pid{i}")

    assert gravacoes == []          # nada gravado ainda
    b.gravar_cache()
    assert gravacoes == [3]         # uma única gravação, com as 3 entradas


def test_gravacao_periodica_dispara_no_intervalo(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    """Buscas longas não podem perder o cache inteiro se forem interrompidas."""
    gravacoes: list[int] = []
    monkeypatch.setattr(mod, "salvar_cache", lambda dados, caminho: gravacoes.append(len(dados)))
    monkeypatch.setattr(mod, "INTERVALO_GRAVACAO_CACHE", 2)

    b, _ = montar({urls["detalhes"]: RespostaFalsa(payload_detalhes)})
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


def test_detalhes_com_status_de_erro_devolve_dict_vazio(montar, urls, sem_pausa):
    b, _ = montar({urls["detalhes"]: RespostaFalsa({"status": "NOT_FOUND"})})
    assert b.obter_detalhes("pid_ruim") == {}


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def test_normalizar_prefere_detalhes_e_cai_para_o_bruto():
    bruto = item_bruto("pid1", "Nome Bruto", -27.60, -48.55)
    detalhes = {"name": "Nome Detalhado", "formatted_phone_number": "(48) 1111-2222"}

    registro = BuscadorProvedores._normalizar(bruto, detalhes, "pid1", 1.5)

    assert registro["nome"] == "Nome Detalhado"          # veio dos detalhes
    assert registro["endereco"] == "Endereço de Nome Bruto"  # fallback do bruto
    assert registro["telefone"] == "(48) 1111-2222"


def test_normalizar_traduz_o_status_do_negocio():
    bruto = item_bruto("pid1", "Alfa", -27.60, -48.55)
    registro = BuscadorProvedores._normalizar(
        bruto, {"business_status": "CLOSED_PERMANENTLY"}, "pid1"
    )
    assert registro["status"] == "Fechado permanentemente"


def test_normalizar_inclui_coordenadas_e_distancia():
    bruto = item_bruto("pid1", "Alfa", -27.60, -48.55)
    registro = BuscadorProvedores._normalizar(bruto, {}, "pid1", 2.75)

    assert registro["latitude"] == -27.60
    assert registro["longitude"] == -48.55
    assert registro["distancia_km"] == 2.75


def test_sem_geometria_distancia_fica_vazia_e_nao_zero():
    """Zero numa planilha seria lido como 'no mesmo ponto do centro da busca'."""
    registro = BuscadorProvedores._normalizar({"name": "Sem geo"}, {}, "pid1", None)
    assert registro["distancia_km"] == ""
    assert registro["latitude"] == ""


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def _rotas_busca(itens, urls, payload_detalhes):
    return {
        urls["busca"]: RespostaFalsa({"status": "OK", "results": itens}),
        urls["detalhes"]: RespostaFalsa(payload_detalhes),
    }


def test_buscar_todos_deduplica_por_place_id(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    """O mesmo provedor aparece em vários termos — deve entrar uma única vez."""
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo a", "termo b"])

    itens = [item_bruto("pid1", "Alfa", -27.60, -48.55)]
    b, _ = montar(_rotas_busca(itens, urls, payload_detalhes))

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)
    assert len(provedores) == 1


def test_buscar_todos_calcula_distancia_do_centro(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    itens = [item_bruto("pid1", "Alfa", -26.3044, -48.8487)]  # Joinville
    b, _ = montar(_rotas_busca(itens, urls, payload_detalhes))

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)
    assert provedores[0]["distancia_km"] == pytest.approx(146.6, abs=2.0)


def test_raio_estrito_descarta_resultados_distantes(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    """
    O `radius` da Text Search é viés de relevância, não filtro: a API devolve
    resultados muito além do raio pedido.
    """
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "RAIO_ESTRITO", True)

    itens = [
        item_bruto("perto", "Alfa", -27.5960, -48.5490),    # ~100 m
        item_bruto("longe", "Beta", -26.3044, -48.8487),    # ~146 km
    ]
    b, sessao = montar(_rotas_busca(itens, urls, payload_detalhes))

    provedores = b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)

    assert [p["place_id"] for p in provedores] == ["perto"]
    # E o descarte acontece ANTES do Place Details — uma chamada paga a menos
    assert len(sessao.chamadas_para(urls["detalhes"])) == 1


def test_sem_raio_estrito_mantem_tudo(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])
    monkeypatch.setattr(mod, "RAIO_ESTRITO", False)

    itens = [
        item_bruto("perto", "Alfa", -27.5960, -48.5490),
        item_bruto("longe", "Beta", -26.3044, -48.8487),
    ]
    b, _ = montar(_rotas_busca(itens, urls, payload_detalhes))

    assert len(b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000)) == 2


def test_falha_em_um_termo_nao_aborta_a_busca(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["ok", "quebrado"])

    chamadas = {"n": 0}
    itens = [item_bruto("pid1", "Alfa", -27.60, -48.55)]

    def get_falso(url, params=None, timeout=None):
        if url == urls["busca"]:
            chamadas["n"] += 1
            if chamadas["n"] == 2:
                raise __import__("requests").ConnectionError()
            return RespostaFalsa({"status": "OK", "results": itens})
        return RespostaFalsa(payload_detalhes)

    b, sessao = montar({})
    sessao.get = get_falso

    mensagens: list[str] = []
    provedores = b.buscar_todos(
        LAT_CENTRO, LNG_CENTRO, raio=5000,
        callback_progresso=lambda info: mensagens.append(info["mensagem"]),
    )

    assert len(provedores) == 1
    assert any("Aviso ao buscar" in m for m in mensagens)


def test_callback_de_progresso_recebe_todas_as_chaves(montar, urls, sem_pausa, payload_detalhes, monkeypatch):
    monkeypatch.setattr(mod, "TERMOS_DE_BUSCA", ["termo"])

    itens = [item_bruto("pid1", "Alfa", -27.60, -48.55)]
    b, _ = montar(_rotas_busca(itens, urls, payload_detalhes))

    eventos: list[dict] = []
    b.buscar_todos(LAT_CENTRO, LNG_CENTRO, raio=5000, callback_progresso=eventos.append)

    esperadas = {"etapa", "total_etapas", "mensagem", "novos_provedores", "total_acumulado"}
    assert all(esperadas <= set(e) for e in eventos)
    assert eventos[0]["novos_provedores"] is None   # etapa iniciando
    assert eventos[-1]["novos_provedores"] == 1     # etapa concluída


def test_fecha_a_sessao_http_ao_sair_do_contexto(montar, urls):
    b, sessao = montar({})
    b.fechar()
    assert sessao.fechada
