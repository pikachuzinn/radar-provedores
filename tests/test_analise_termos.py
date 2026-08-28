"""
Testes de analise_termos.py — medição da sobreposição entre termos de busca.

Funções puras, sem rede: recebem os conjuntos de place_ids que cada termo
trouxe e devolvem contribuição, redundância e ordem de cobertura.
"""

from analise_termos import analisar, formatar_relatorio


def test_termos_disjuntos_nao_tem_redundancia():
    analise = analisar({"a": {"1", "2"}, "b": {"3", "4"}})

    assert analise["total_unico"] == 4
    assert analise["total_bruto"] == 4
    assert analise["redundancia"] == 0.0
    assert all(l["exclusivos"] == l["encontrados"] for l in analise["termos"])
    assert analise["dispensaveis"] == []


def test_termo_totalmente_contido_em_outro_e_descartavel():
    """Um termo cujos resultados outro já traz é custo puro, sem ganho."""
    analise = analisar({"amplo": {"1", "2", "3"}, "contido": {"1", "2"}})

    por_termo = {l["termo"]: l for l in analise["termos"]}

    assert por_termo["contido"]["exclusivos"] == 0
    assert por_termo["contido"]["redundante_isolado"] is True
    assert por_termo["amplo"]["exclusivos"] == 1
    assert por_termo["amplo"]["redundante_isolado"] is False
    assert analise["dispensaveis"] == ["contido"]


def test_exclusivos_nao_dependem_da_ordem():
    """
    A razão de existir da métrica: o contador de novos do progresso dá todo o
    crédito ao primeiro termo. A contribuição exclusiva é de conjunto, e não
    muda se os termos forem reordenados.
    """
    dados = {"a": {"1", "2", "3"}, "b": {"2", "3", "4"}, "c": {"3", "5"}}
    invertido = {"c": dados["c"], "b": dados["b"], "a": dados["a"]}

    def exclusivos(analise):
        return {l["termo"]: l["exclusivos"] for l in analise["termos"]}

    assert exclusivos(analisar(dados)) == exclusivos(analisar(invertido))
    assert exclusivos(analisar(dados)) == {"a": 1, "b": 1, "c": 1}   # 1, 4 e 5


def test_redundancia_global_mede_o_esforco_repetido():
    # 3 resultados únicos a partir de 6 encontrados = metade do esforço repetida
    analise = analisar({"a": {"1", "2", "3"}, "b": {"1", "2", "3"}})

    assert analise["total_unico"] == 3
    assert analise["total_bruto"] == 6
    assert analise["redundancia"] == 0.5


def test_cobertura_gulosa_prioriza_o_maior_ganho():
    analise = analisar({
        "grande": {"1", "2", "3", "4"},
        "medio": {"4", "5"},
        "pequeno": {"1"},
    })

    ordem = [c["termo"] for c in analise["cobertura"]]

    assert ordem[0] == "grande"          # maior ganho inicial
    assert ordem[1] == "medio"           # acrescenta o "5"
    assert "pequeno" not in ordem        # não acrescenta nada
    assert analise["cobertura"][-1]["cobertura"] == 1.0
    assert analise["minimo_para_cobertura_total"] == 2


def test_universo_e_serializavel_em_json():
    """A camada de serviço devolve isto por API web — set quebraria o jsonify."""
    import json

    analise = analisar({"a": {"1", "2"}})
    json.dumps(analise)                       # não deve levantar
    assert analise["universo"] == ["1", "2"]  # lista ordenada, não set


def test_requisicoes_sao_repassadas():
    analise = analisar({"a": {"1"}, "b": {"1"}}, {"a": 3, "b": 2})
    por_termo = {l["termo"]: l["requisicoes"] for l in analise["termos"]}
    assert por_termo == {"a": 3, "b": 2}


def test_entrada_vazia_nao_quebra():
    analise = analisar({})
    assert analise["total_unico"] == 0
    assert analise["redundancia"] == 0.0
    assert analise["termos"] == []
    assert formatar_relatorio(analise) == "Nenhum termo analisado."


def test_termo_sem_resultado_nao_e_marcado_descartavel():
    """Zero resultados pode ser característica da região, não do termo."""
    analise = analisar({"a": {"1"}, "vazio": set()})
    por_termo = {l["termo"]: l for l in analise["termos"]}

    assert por_termo["vazio"]["encontrados"] == 0
    assert por_termo["vazio"]["redundante_isolado"] is False


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def test_relatorio_aponta_os_termos_dispensaveis():
    analise = analisar({"amplo": {"1", "2"}, "redundante": {"1"}}, {"amplo": 2, "redundante": 1})
    texto = formatar_relatorio(analise, requisicoes_totais=3)

    assert "dispensável" in texto
    assert "✗ redundante" in texto
    assert "✓ amplo" in texto
    assert "1 de 3 requisições" in texto


def test_relatorio_reconhece_quando_todos_contribuem():
    analise = analisar({"a": {"1"}, "b": {"2"}})
    assert "Mantenha" in formatar_relatorio(analise)


def test_relatorio_alerta_que_a_medida_varia_por_regiao():
    """Cortar termos com base numa única cidade seria generalizar demais."""
    analise = analisar({"a": {"1"}, "b": {"1"}})
    assert "varia por região" in formatar_relatorio(analise)


# ---------------------------------------------------------------------------
# A armadilha do set cover
# ---------------------------------------------------------------------------

def test_redundantes_isolados_podem_ser_coletivamente_necessarios():
    """
    Cada termo abaixo é redundante sozinho — nenhum tem resultado exclusivo,
    porque toda empresa aparece em dois deles. Mas remover os três de uma vez
    perderia tudo. Recomendar o corte em bloco a partir da coluna "só ele"
    seria um erro caro: a busca continuaria rodando e devolvendo menos.
    """
    analise = analisar({"a": {"1", "2"}, "b": {"1", "3"}, "c": {"2", "3"}})

    # Todos são individualmente redundantes...
    assert all(l["redundante_isolado"] for l in analise["termos"])

    # ...mas apenas um pode sair, e os que ficam ainda cobrem tudo
    assert len(analise["dispensaveis"]) == 1
    ainda_coberto = set().union(*(
        {"a": {"1", "2"}, "b": {"1", "3"}, "c": {"2", "3"}}[t]
        for t in analise["essenciais"]
    ))
    assert ainda_coberto == set(analise["universo"])


def test_relatorio_alerta_sobre_o_termo_que_parece_cortavel():
    analise = analisar({"a": {"1", "2"}, "b": {"1", "3"}, "c": {"2", "3"}})
    texto = formatar_relatorio(analise)

    assert "NÃO podem ser cortados" in texto.replace("\n", " ")


def test_essenciais_sempre_reproduzem_o_universo_inteiro():
    """Invariante do corte recomendado: manter os essenciais não perde nada."""
    cenarios = [
        {"a": {"1", "2", "3"}, "b": {"2"}, "c": {"4"}},
        {"a": {"1"}, "b": {"1"}, "c": {"1"}},
        {"a": {"1", "2"}, "b": {"3", "4"}, "c": {"1", "3"}, "d": {"2", "4"}},
        {"unico": {"1", "2", "3"}},
        {"a": set(), "b": {"1"}},
    ]

    for dados in cenarios:
        analise = analisar(dados)
        coberto = set().union(*(dados[t] for t in analise["essenciais"])) \
            if analise["essenciais"] else set()
        assert coberto == set(analise["universo"]), f"falhou em {dados}"
