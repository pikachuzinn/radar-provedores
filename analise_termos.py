"""
analise_termos.py — Mede a sobreposição entre os termos de busca.

Cada termo em TERMOS_DE_BUSCA custa requisições à Places API, mas vários deles
tendem a encontrar as mesmas empresas. Um termo que só devolve resultados que
outros já trouxeram é custo puro, sem ganho de cobertura.

Este módulo é só cálculo e formatação — não faz rede. Os dados vêm de graça da
busca normal: BuscadorProvedores registra quais place_ids cada termo trouxe e
quantas requisições gastou, sem nenhuma chamada adicional à API.

────────────────────────────────────────────────────────────────────────
Por que "novos por termo" não serve como métrica

O contador de novos que aparece no progresso é dependente da ordem: o primeiro
termo leva o crédito por tudo que encontra, e os seguintes só ficam com as
sobras. Trocar a ordem dos termos mudaria completamente os números.

A métrica correta é de conjunto: quantos estabelecimentos existiriam APENAS
graças àquele termo — os que nenhum outro termo encontrou. Essa contagem não
depende da ordem, e é exatamente o que se perde ao remover o termo.
────────────────────────────────────────────────────────────────────────
"""


def analisar(
    ids_por_termo: dict[str, set[str]],
    requisicoes_por_termo: dict[str, int] | None = None,
) -> dict:
    """
    Calcula a contribuição e a redundância de cada termo de busca.

    Args:
        ids_por_termo: {termo: conjunto de place_ids que o termo encontrou}.
        requisicoes_por_termo: {termo: nº de requisições gastas}, opcional.

    Returns:
        Dict com:
            "universo"      (list) — place_ids encontrados, ordenados
                (lista, e não set, para que o retorno seja serializável em JSON)
            "total_unico"   (int) — tamanho do universo
            "total_bruto"   (int) — soma dos resultados por termo, com repetição
            "redundancia"   (float) — fração do esforço gasta em repetição (0 a 1)
            "termos"        (list[dict]) — uma entrada por termo, ordenada por
                exclusivos (desc). Cada entrada traz:
                    termo, encontrados, exclusivos, redundancia,
                    requisicoes, redundante_isolado
            "cobertura"     (list[dict]) — ordem gulosa de maior ganho marginal:
                    termo, ganho, acumulado, cobertura (fração do universo)
            "minimo_para_cobertura_total" (int) — quantos termos bastam para
                reunir todo o universo
            "essenciais"    (list[str]) — termos da cobertura gulosa
            "dispensaveis"  (list[str]) — os demais; podem sair TODOS DE UMA VEZ
                sem perder nenhum estabelecimento

    Cuidado com a diferença entre `redundante_isolado` e `dispensaveis`:
    um termo sem nenhum resultado exclusivo pode ser removido sozinho sem
    perda, mas remover vários desses ao mesmo tempo pode, sim, custar
    estabelecimentos — basta que uma empresa apareça só nesses termos e em
    mais nenhum. Para decidir o que cortar em bloco use `dispensaveis`, que
    é derivado da cobertura e por construção preserva o universo inteiro.
    """
    universo: set[str] = set().union(*ids_por_termo.values()) if ids_por_termo else set()
    requisicoes = requisicoes_por_termo or {}

    # --- Contribuição exclusiva: o que se perde ao remover cada termo ---
    linhas = []
    for termo, ids in ids_por_termo.items():
        outros: set[str] = set().union(
            *(v for t, v in ids_por_termo.items() if t != termo)
        ) if len(ids_por_termo) > 1 else set()

        exclusivos = ids - outros
        encontrados = len(ids)

        linhas.append({
            "termo": termo,
            "encontrados": encontrados,
            "exclusivos": len(exclusivos),
            # Fração dos resultados do termo que outro termo também traria
            "redundancia": 1 - (len(exclusivos) / encontrados) if encontrados else 0.0,
            "requisicoes": requisicoes.get(termo, 0),
            # Sozinho, não sustenta nenhum estabelecimento. Removê-lo
            # isoladamente é seguro; removê-lo junto com outros na mesma
            # condição, não necessariamente — ver "dispensaveis".
            "redundante_isolado": len(exclusivos) == 0 and encontrados > 0,
        })

    linhas.sort(key=lambda l: (-l["exclusivos"], -l["encontrados"]))

    total_bruto = sum(l["encontrados"] for l in linhas)

    # --- Cobertura gulosa: menor conjunto de termos que cobre o universo ---
    # A cada passo escolhe o termo que adiciona mais estabelecimentos ainda não
    # cobertos. Não garante o mínimo absoluto (o problema é NP-difícil), mas dá
    # uma ordem de prioridade prática e honesta.
    cobertura = []
    restante = set(universo)
    disponiveis = dict(ids_por_termo)

    while restante and disponiveis:
        melhor = max(disponiveis, key=lambda t: (len(disponiveis[t] & restante), t))
        ganho = len(disponiveis[melhor] & restante)
        if ganho == 0:
            break

        restante -= disponiveis[melhor]
        del disponiveis[melhor]
        cobertos = len(universo) - len(restante)

        cobertura.append({
            "termo": melhor,
            "ganho": ganho,
            "acumulado": cobertos,
            "cobertura": cobertos / len(universo) if universo else 0.0,
        })

    # Termos fora da cobertura gulosa. Como a cobertura já reúne todo o
    # universo, este conjunto inteiro pode ser cortado de uma vez sem perda.
    essenciais = [c["termo"] for c in cobertura]
    dispensaveis = [t for t in ids_por_termo if t not in essenciais]

    return {
        # Lista ordenada em vez de set: mantém o retorno serializável em JSON,
        # para que a camada de serviço possa devolvê-lo por uma API web.
        "universo": sorted(universo),
        "total_unico": len(universo),
        "total_bruto": total_bruto,
        "redundancia": 1 - (len(universo) / total_bruto) if total_bruto else 0.0,
        "termos": linhas,
        "cobertura": cobertura,
        "minimo_para_cobertura_total": len(cobertura),
        "essenciais": essenciais,
        "dispensaveis": dispensaveis,
    }


def formatar_relatorio(analise: dict, requisicoes_totais: int | None = None) -> str:
    """
    Monta o relatório em texto para exibição no terminal.

    Args:
        analise: Saída de analisar().
        requisicoes_totais: Total de requisições da busca, para estimar economia.
    """
    if not analise["termos"]:
        return "Nenhum termo analisado."

    linhas = []
    a = analise

    linhas.append("")
    linhas.append("─" * 72)
    linhas.append("ANÁLISE DE SOBREPOSIÇÃO DOS TERMOS DE BUSCA")
    linhas.append("─" * 72)
    linhas.append(
        f"{a['total_unico']} estabelecimentos únicos a partir de "
        f"{a['total_bruto']} resultados somados entre os termos "
        f"({a['redundancia']:.0%} de repetição)."
    )
    linhas.append("")

    # ---- Contribuição por termo ----
    largura = max(len(l["termo"]) for l in a["termos"])
    largura = min(largura, 42)

    linhas.append(f"{'TERMO'.ljust(largura)}  {'ACHOU':>6} {'SÓ ELE':>7} {'REPET.':>7} {'REQS':>5}")
    linhas.append(f"{'-' * largura}  {'-' * 6} {'-' * 7} {'-' * 7} {'-' * 5}")

    for l in a["termos"]:
        termo = l["termo"][:largura].ljust(largura)
        marca = "  ← dispensável" if l["termo"] in a["dispensaveis"] else ""
        linhas.append(
            f"{termo}  {l['encontrados']:>6} {l['exclusivos']:>7} "
            f"{l['redundancia']:>6.0%} {l['requisicoes']:>5}{marca}"
        )

    linhas.append("")
    linhas.append("  ACHOU  = estabelecimentos que o termo trouxe")
    linhas.append("  SÓ ELE = os que NENHUM outro termo encontrou")
    linhas.append("  REPET. = fração dos resultados que outro termo também traria")

    # ---- Ordem de prioridade ----
    linhas.append("")
    linhas.append("Cobertura acumulada, por ganho marginal:")
    for i, c in enumerate(a["cobertura"], start=1):
        linhas.append(
            f"  {i}. +{c['ganho']:>3} → {c['acumulado']:>3}/{a['total_unico']} "
            f"({c['cobertura']:.0%})  {c['termo']}"
        )

    # ---- Recomendação ----
    # Baseada na cobertura, e não na lista de termos sem resultado exclusivo:
    # vários termos individualmente redundantes podem ser coletivamente
    # necessários, quando uma empresa aparece só na combinação deles.
    linhas.append("")
    reqs_por_termo = {l["termo"]: l["requisicoes"] for l in a["termos"]}

    if a["dispensaveis"]:
        economia = sum(reqs_por_termo.get(t, 0) for t in a["dispensaveis"])
        linhas.append(
            f"RECOMENDAÇÃO: {len(a['essenciais'])} dos {len(a['termos'])} termos "
            "bastam para os mesmos resultados nesta região."
        )
        linhas.append("  Manter:")
        for termo in a["essenciais"]:
            linhas.append(f"    ✓ {termo}")
        linhas.append("  Remover:")
        for termo in a["dispensaveis"]:
            linhas.append(f"    ✗ {termo}")
        if requisicoes_totais and economia:
            linhas.append(
                f"  Economia: {economia} de {requisicoes_totais} requisições "
                f"({economia / requisicoes_totais:.0%}) sem perder nenhum resultado."
            )
    else:
        linhas.append("RECOMENDAÇÃO: todos os termos são necessários à cobertura. Mantenha.")

    # Alerta contra a leitura ingênua da coluna "SÓ ELE"
    presos = [l["termo"] for l in a["termos"]
              if l["redundante_isolado"] and l["termo"] in a["essenciais"]]
    if presos:
        linhas.append("")
        linhas.append(
            "Observação: os termos abaixo não têm resultado exclusivo, mas NÃO "
            "podem ser cortados — há empresas que aparecem apenas na combinação "
            "deles com outros termos redundantes:"
        )
        for termo in presos:
            linhas.append(f"    ! {termo}")

    linhas.append("")
    linhas.append(
        "Atenção: a sobreposição varia por região. Meça em algumas cidades "
        "representativas antes de cortar termos em config.py."
    )
    linhas.append("─" * 72)

    return "\n".join(linhas)
