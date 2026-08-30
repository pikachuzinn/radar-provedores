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


# ---------------------------------------------------------------------------
# Consolidação entre cidades
# ---------------------------------------------------------------------------

# Separador usado para compor a chave (cidade, place_id). O caractere de
# controle "unit separator" não aparece em nomes de cidade nem em place_ids
# do Google, então não há risco de colisão com os dados reais.
_SEPARADOR = "\x1f"


def consolidar(
    ids_por_cidade: dict[str, dict[str, set[str]]],
    requisicoes_por_cidade: dict[str, dict[str, int]] | None = None,
) -> dict:
    """
    Cruza a análise de várias cidades numa recomendação única e segura.

    A sobreposição entre termos varia por região: um termo inútil numa capital
    pode ser o único a encontrar algo no interior. Recomendar cortes a partir de
    uma cidade só seria generalizar demais.

    A consolidação trata cada par **(cidade, estabelecimento)** como um elemento
    distinto a cobrir. Um termo só cobre uma empresa na cidade em que realmente
    a encontrou — então o mesmo algoritmo de cobertura usado em analisar()
    passa a garantir, por construção, que o conjunto recomendado reproduz o
    resultado completo em **todas** as cidades medidas, e não só na média.

    Args:
        ids_por_cidade: {cidade: {termo: conjunto de place_ids}}.
        requisicoes_por_cidade: {cidade: {termo: requisições}}, opcional.

    Returns:
        Dict com:
            "cidades"      (dict) — {cidade: saída de analisar()}
            "global"       (dict) — análise sobre os pares (cidade, place_id)
            "termos"       (list[dict]) — visão agregada por termo:
                termo, cidades_presente, cidades_essencial, cidades_dispensavel,
                encontrados_total, exclusivos_total, requisicoes_total, dispensavel
            "essenciais"   (list[str]) — termos a manter em config.py
            "dispensaveis" (list[str]) — termos que podem sair, sem perda em
                nenhuma das cidades medidas
            "total_cidades" (int)
    """
    requisicoes_por_cidade = requisicoes_por_cidade or {}

    # --- Análise individual, cidade a cidade ---
    por_cidade = {
        cidade: analisar(ids, requisicoes_por_cidade.get(cidade))
        for cidade, ids in ids_por_cidade.items()
    }

    # --- Universo combinado: um elemento por (cidade, estabelecimento) ---
    combinado: dict[str, set[str]] = {}
    requisicoes_totais: dict[str, int] = {}

    for cidade, ids_por_termo in ids_por_cidade.items():
        reqs_da_cidade = requisicoes_por_cidade.get(cidade, {})
        for termo, ids in ids_por_termo.items():
            combinado.setdefault(termo, set()).update(
                f"{cidade}{_SEPARADOR}{place_id}" for place_id in ids
            )
            requisicoes_totais[termo] = (
                requisicoes_totais.get(termo, 0) + reqs_da_cidade.get(termo, 0)
            )

    analise_global = analisar(combinado, requisicoes_totais)

    # --- Visão agregada por termo ---
    essenciais = analise_global["essenciais"]
    linhas = []

    for termo in combinado:
        presente = sum(
            1 for a in por_cidade.values()
            for l in a["termos"] if l["termo"] == termo and l["encontrados"] > 0
        )
        essencial_em = sum(1 for a in por_cidade.values() if termo in a["essenciais"])

        # Dispensável ali é diferente de ausente ali. Em analisar(), um termo
        # que não achou nada entra em "dispensaveis" — e está certo, no escopo
        # daquela cidade cortá-lo não custa nada. Mas para sinalizar a armadilha
        # do "medi uma cidade só" interessa apenas o caso em que o termo TROUXE
        # resultado e mesmo assim ficou fora da cobertura; caso contrário o
        # relatório alertaria sobre termos que nunca foram descartados de fato.
        dispensavel_em = sum(
            1 for a in por_cidade.values()
            if termo in a["dispensaveis"]
            and any(l["termo"] == termo and l["encontrados"] > 0 for l in a["termos"])
        )
        exclusivos = sum(
            l["exclusivos"] for a in por_cidade.values()
            for l in a["termos"] if l["termo"] == termo
        )
        encontrados = sum(
            l["encontrados"] for a in por_cidade.values()
            for l in a["termos"] if l["termo"] == termo
        )

        linhas.append({
            "termo": termo,
            "cidades_presente": presente,
            "cidades_essencial": essencial_em,
            "cidades_dispensavel": dispensavel_em,
            "encontrados_total": encontrados,
            "exclusivos_total": exclusivos,
            "requisicoes_total": requisicoes_totais.get(termo, 0),
            "dispensavel": termo in analise_global["dispensaveis"],
        })

    linhas.sort(key=lambda l: (-l["cidades_essencial"], -l["exclusivos_total"], l["termo"]))

    return {
        "cidades": por_cidade,
        "global": analise_global,
        "termos": linhas,
        "essenciais": essenciais,
        "dispensaveis": analise_global["dispensaveis"],
        "total_cidades": len(ids_por_cidade),
    }


def formatar_relatorio_multi(consolidacao: dict, cidades_com_erro: dict | None = None) -> str:
    """
    Monta o relatório consolidado de várias cidades para exibição no terminal.

    Args:
        consolidacao: Saída de consolidar().
        cidades_com_erro: {cidade: mensagem}, para relatar o que ficou de fora.
    """
    c = consolidacao
    cidades_com_erro = cidades_com_erro or {}

    if not c["termos"]:
        return "Nenhum dado para consolidar."

    linhas = []
    linhas.append("")
    linhas.append("═" * 76)
    linhas.append(f"CALIBRAÇÃO DE TERMOS — {c['total_cidades']} cidade(s) medida(s)")
    linhas.append("═" * 76)

    # ---- Resumo por cidade ----
    linhas.append("")
    linhas.append("Por cidade:")
    for cidade, analise in c["cidades"].items():
        linhas.append(
            f"  {cidade:<28} {analise['total_unico']:>4} empresas  "
            f"{analise['redundancia']:>4.0%} de repetição  "
            f"{len(analise['essenciais'])}/{len(analise['termos'])} termos essenciais"
        )

    for cidade, erro in cidades_com_erro.items():
        linhas.append(f"  {cidade:<28} IGNORADA — {erro}")

    # ---- Visão por termo ----
    largura = min(max(len(l["termo"]) for l in c["termos"]), 42)
    total = c["total_cidades"]

    linhas.append("")
    linhas.append(f"{'TERMO'.ljust(largura)}  {'ESSENC.':>8} {'ACHOU':>6} {'SÓ ELE':>7} {'REQS':>5}")
    linhas.append(f"{'-' * largura}  {'-' * 8} {'-' * 6} {'-' * 7} {'-' * 5}")

    for l in c["termos"]:
        termo = l["termo"][:largura].ljust(largura)
        marca = "  ← dispensável" if l["dispensavel"] else ""
        linhas.append(
            f"{termo}  {l['cidades_essencial']:>4}/{total:<3} "
            f"{l['encontrados_total']:>6} {l['exclusivos_total']:>7} "
            f"{l['requisicoes_total']:>5}{marca}"
        )

    linhas.append("")
    linhas.append(f"  ESSENC. = em quantas das {total} cidades o termo entrou na cobertura mínima")
    linhas.append("  ACHOU   = estabelecimentos trazidos, somando todas as cidades")
    linhas.append("  SÓ ELE  = os que nenhum outro termo encontrou, somando as cidades")

    # ---- Recomendação ----
    linhas.append("")
    if c["dispensaveis"]:
        economia = sum(l["requisicoes_total"] for l in c["termos"] if l["dispensavel"])
        total_reqs = sum(l["requisicoes_total"] for l in c["termos"])

        linhas.append(
            f"RECOMENDAÇÃO: manter {len(c['essenciais'])} dos "
            f"{len(c['termos'])} termos."
        )
        linhas.append("")
        linhas.append("TERMOS_DE_BUSCA: list[str] = [")
        for termo in c["essenciais"]:
            linhas.append(f'    "{termo}",')
        linhas.append("]")
        linhas.append("")
        linhas.append("  Removidos:")
        for termo in c["dispensaveis"]:
            linhas.append(f"    ✗ {termo}")
        if total_reqs:
            linhas.append(
                f"  Economia: {economia} de {total_reqs} requisições "
                f"({economia / total_reqs:.0%}) nas cidades medidas."
            )
        linhas.append("")
        linhas.append(
            "  Este conjunto reproduz TODOS os estabelecimentos encontrados em "
            "TODAS as cidades medidas — não é uma média."
        )
    else:
        linhas.append(
            "RECOMENDAÇÃO: todos os termos são necessários em pelo menos uma "
            "das cidades. Mantenha a lista como está."
        )

    # ---- Termos que uma medição de cidade única cortaria por engano ----
    # Critério exato: trouxe resultado e ficou fora da cobertura em pelo menos
    # uma cidade, mas foi essencial em outra. Não basta ter cidades_essencial
    # abaixo do total — o termo pode simplesmente não ter achado nada lá, o
    # que é uma informação diferente.
    enganosos = sorted(
        (l for l in c["termos"]
         if l["cidades_essencial"] >= 1 and l["cidades_dispensavel"] >= 1),
        key=lambda l: l["cidades_essencial"],
    )
    if enganosos:
        linhas.append("")
        linhas.append(
            "Cuidado ao medir uma cidade só — estes termos apareceram como "
            "dispensáveis em uma região e essenciais em outra:"
        )
        for l in enganosos:
            linhas.append(
                f"    ! {l['termo']} — essencial em {l['cidades_essencial']}, "
                f"dispensável em {l['cidades_dispensavel']} de {total}"
            )

    if cidades_com_erro:
        linhas.append("")
        linhas.append(
            f"Atenção: {len(cidades_com_erro)} cidade(s) ficaram de fora da "
            "consolidação. A recomendação só vale para as que foram medidas."
        )

    linhas.append("═" * 76)
    return "\n".join(linhas)
