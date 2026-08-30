"""
calibrar_termos.py — Calibra TERMOS_DE_BUSCA medindo várias cidades.

A sobreposição entre os termos varia por região: um termo inútil numa capital
pode ser o único a encontrar algo no interior. Este utilitário roda a busca em
várias localizações, cruza os resultados e recomenda o menor conjunto de termos
que reproduz o resultado completo em **todas** elas.

Uso:
    python calibrar_termos.py "Itajaí, SC" "Joinville, SC" "Chapecó, SC"
    python calibrar_termos.py "Blumenau, SC" -r 15000 --exportar csv
    python calibrar_termos.py --coordenadas -26.90 -48.66 --coordenadas -26.30 -48.84

A saída inclui um bloco TERMOS_DE_BUSCA pronto para colar em config.py.

Custo: cada cidade consome 1 chamada de Geocoding e até
(termos × páginas) requisições de busca. O total estimado é exibido antes de
começar. Como a busca é paga, use --exportar para também salvar os provedores
encontrados e não desperdiçar o gasto.
"""

import argparse
import logging
import os
import re
import sys

from dotenv import load_dotenv

from analise_termos import formatar_relatorio_multi
from config import MAX_PAGINAS, RAIO_PADRAO, DIRETORIO_SAIDA, TERMOS_DE_BUSCA
from exportador import exportar_resultados
from service import calibrar_termos

load_dotenv()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calibrar_termos",
        description=(
            "Mede a sobreposição dos termos de busca em várias cidades e "
            "recomenda quais manter em config.py."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
exemplos:
  python calibrar_termos.py "Itajaí, SC" "Joinville, SC" "Chapecó, SC"
  python calibrar_termos.py "Blumenau, SC" -r 15000 --exportar csv
  python calibrar_termos.py --coordenadas -26.90 -48.66 --coordenadas -27.59 -48.54

dica: escolha cidades representativas da sua área de atuação — uma capital,
uma cidade média e uma do interior costumam revelar diferenças relevantes.
        """,
    )

    parser.add_argument(
        "enderecos",
        nargs="*",
        metavar="ENDEREÇO",
        help='Endereços a medir (ex: "Itajaí, SC" "Joinville, SC")',
    )
    parser.add_argument(
        "--coordenadas",
        nargs=2,
        type=float,
        action="append",
        metavar=("LAT", "LNG"),
        help="Par de coordenadas a medir. Pode ser repetido.",
    )
    parser.add_argument(
        "-r", "--raio",
        type=int,
        default=RAIO_PADRAO,
        metavar="METROS",
        help=f"Raio aplicado a todas as cidades (padrão: {RAIO_PADRAO})",
    )
    parser.add_argument(
        "--exportar",
        choices=["csv", "excel", "ambos"],
        help=(
            "Além do relatório, salva os provedores de cada cidade em subpastas. "
            "A busca é paga — vale aproveitar os dados."
        ),
    )
    parser.add_argument(
        "-o", "--saida",
        default=DIRETORIO_SAIDA,
        metavar="DIRETÓRIO",
        help=f"Pasta base das exportações (padrão: {DIRETORIO_SAIDA})",
    )
    parser.add_argument(
        "--api-key",
        metavar="CHAVE",
        help="Chave da Google Maps API. Se omitida, usa GOOGLE_MAPS_API_KEY do .env.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Exibe mensagens detalhadas de depuração",
    )

    return parser


# ---------------------------------------------------------------------------
# Progresso
# ---------------------------------------------------------------------------

def _imprimir_cidade(info: dict) -> None:
    """Uma linha por cidade, em cada mudança de etapa."""
    prefixo = f"[{info['indice']}/{info['total']}]"

    if info["etapa"] == "iniciando":
        print(f"\n{prefixo} {info['cidade']}...")
    elif info["etapa"] == "concluida":
        print(f"      ✔ {info['total_encontrado']} provedor(es)")
    else:
        print(f"      ⚠ ignorada: {info['erro']}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Exportação por cidade
# ---------------------------------------------------------------------------

def _apelido(cidade: str) -> str:
    """Nome de pasta seguro a partir do rótulo da cidade."""
    limpo = re.sub(r"[^\w\s-]", "", cidade, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_]+", "-", limpo) or "cidade"


def _exportar_por_cidade(provedores_por_cidade: dict, formato: str, base: str) -> list[str]:
    """
    Salva os resultados de cada cidade numa subpasta própria.

    Subpastas evitam colisão de nome: o arquivo é nomeado por timestamp com
    resolução de segundos, e várias cidades podem terminar no mesmo segundo.
    """
    caminhos = []
    for cidade, provedores in provedores_por_cidade.items():
        if not provedores:
            continue
        destino = os.path.join(base, _apelido(cidade))
        try:
            for caminho in exportar_resultados(provedores, formato, destino):
                caminhos.append(str(caminho))
        except (ImportError, PermissionError, ValueError) as exc:
            print(f"  ⚠ falha ao exportar '{cidade}': {exc}", file=sys.stderr)
    return caminhos


# ---------------------------------------------------------------------------
# Execução principal
# ---------------------------------------------------------------------------

def main() -> int:
    parser = _criar_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # ---- Localizações ----
    localizacoes = list(args.enderecos) + [tuple(c) for c in (args.coordenadas or [])]

    if not localizacoes:
        parser.print_usage(sys.stderr)
        print(
            "\n[ERRO] Informe ao menos uma localização.\n"
            '  Exemplo: python calibrar_termos.py "Itajaí, SC" "Joinville, SC"',
            file=sys.stderr,
        )
        return 1

    if len(localizacoes) < 2:
        print(
            "[AVISO] Com uma única cidade não há o que cruzar — o resultado "
            "equivale a 'main.py --relatorio-termos'. Meça 3 ou mais cidades "
            "representativas para uma recomendação confiável.\n",
            file=sys.stderr,
        )

    # ---- Chave ----
    api_key = args.api_key or os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        print(
            "\n[ERRO] Chave de API não encontrada.\n"
            "  Crie um arquivo .env com GOOGLE_MAPS_API_KEY=sua_chave\n"
            "  ou passe --api-key SUA_CHAVE.",
            file=sys.stderr,
        )
        return 1

    # ---- Estimativa de custo, antes de gastar ----
    por_cidade = len(TERMOS_DE_BUSCA) * MAX_PAGINAS
    print(f"Calibração em {len(localizacoes)} localização(ões), raio de {args.raio:,} m.")
    print(f"Termos atuais: {len(TERMOS_DE_BUSCA)}")
    print(
        f"Custo máximo estimado: {len(localizacoes)} chamadas de Geocoding + "
        f"até {len(localizacoes) * por_cidade} requisições de busca."
    )

    # ---- Execução ----
    resultado = calibrar_termos(
        api_key=api_key,
        localizacoes=localizacoes,
        raio=args.raio,
        callback_cidade=_imprimir_cidade,
    )

    if resultado["erro"]:
        print(f"\n[ERRO] {resultado['erro']}", file=sys.stderr)
        for cidade, erro in resultado["cidades_com_erro"].items():
            print(f"  {cidade}: {erro}", file=sys.stderr)
        return 1

    # ---- Relatório ----
    print(formatar_relatorio_multi(
        resultado["consolidacao"],
        cidades_com_erro=resultado["cidades_com_erro"],
    ))

    # ---- Exportação opcional ----
    if args.exportar:
        arquivos = _exportar_por_cidade(
            resultado["provedores_por_cidade"], args.exportar, args.saida
        )
        if arquivos:
            print("\nArquivo(s) gerado(s):")
            for caminho in arquivos:
                print(f"  → {caminho}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
