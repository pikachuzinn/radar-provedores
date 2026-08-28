"""
main.py — Ponto de entrada do buscador de provedores de internet.

Responsável exclusivamente pela interface de linha de comando (CLI):
  - Parsing de argumentos
  - Modo interativo quando nenhum argumento é fornecido
  - Exibição de progresso e erros no terminal
  - Delegação da lógica de negócio para service.executar_busca()

Uso rápido:
    python main.py -e "Florianópolis, SC"
    python main.py -c -27.5954 -48.5480 -r 10000
    python main.py                         # modo interativo
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from analise_termos import formatar_relatorio
from config import RAIO_PADRAO, DIRETORIO_SAIDA
from service import executar_busca

# ---------------------------------------------------------------------------
# Carrega variáveis de ambiente do arquivo .env (se existir)
# ---------------------------------------------------------------------------
load_dotenv()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configurar_logging(verbose: bool) -> None:
    nivel = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buscador_provedores",
        description=(
            "Busca provedores de internet próximos a uma localização "
            "usando a Google Places API."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
exemplos:
  python main.py -e "Rua XV de Novembro, 100, Curitiba, PR"
  python main.py -e "São Paulo, SP" -r 10000 -f excel
  python main.py -c -23.5505 -46.6333
  python main.py -e "Joinville, SC" -f ambos -o meus_resultados
  python main.py                              # modo interativo
        """,
    )

    # ---- Localização (mutuamente exclusivos) ----
    grupo_local = parser.add_mutually_exclusive_group()
    grupo_local.add_argument(
        "-e", "--endereco",
        metavar="ENDEREÇO",
        help="Endereço para buscar provedores próximos (ex: 'Blumenau, SC')",
    )
    grupo_local.add_argument(
        "-c", "--coordenadas",
        nargs=2,
        metavar=("LAT", "LNG"),
        type=float,
        help="Coordenadas geográficas em graus decimais (ex: -27.59 -48.54)",
    )

    # ---- Parâmetros de busca ----
    parser.add_argument(
        "-r", "--raio",
        type=int,
        default=RAIO_PADRAO,
        metavar="METROS",
        help=f"Raio de busca em metros (padrão: {RAIO_PADRAO})",
    )

    # ---- Exportação ----
    parser.add_argument(
        "-f", "--formato",
        choices=["csv", "excel", "ambos"],
        default="csv",
        help="Formato do arquivo de saída (padrão: csv)",
    )
    parser.add_argument(
        "-o", "--saida",
        default=DIRETORIO_SAIDA,
        metavar="DIRETÓRIO",
        help=f"Diretório onde salvar os resultados (padrão: {DIRETORIO_SAIDA})",
    )

    # ---- API ----
    parser.add_argument(
        "--api-key",
        metavar="CHAVE",
        help=(
            "Chave da Google Maps API. Se omitida, usa GOOGLE_MAPS_API_KEY do .env. "
            "ATENÇÃO: passar a chave aqui a expõe no histórico do shell."
        ),
    )

    # ---- Diagnóstico ----
    parser.add_argument(
        "--relatorio-termos",
        action="store_true",
        help=(
            "Ao final, mostra quanto cada termo de TERMOS_DE_BUSCA contribuiu e "
            "quais são redundantes. Não custa nenhuma requisição adicional."
        ),
    )

    # ---- Debug ----
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Exibe mensagens detalhadas de depuração",
    )

    return parser


# ---------------------------------------------------------------------------
# Progresso
# ---------------------------------------------------------------------------

# Falhas por termo coletadas durante a busca. Uma busca em que todos os termos
# falharam devolve zero provedores — e sem esse registro a CLI relataria
# "nenhum provedor encontrado", escondendo um erro de API atrás de um conselho
# enganoso ("aumente o raio").
_falhas_da_busca: list[str] = []


def _imprimir_progresso(info: dict) -> None:
    """
    Exibe no terminal uma linha de progresso a partir do dict estruturado
    emitido por BuscadorProvedores.buscar_todos().

    Três situações:
      - erro preenchido        → a busca daquele termo falhou
      - novos_provedores None  → etapa em andamento
      - novos_provedores int   → etapa concluída
    """
    etapa = info["etapa"]
    total = info["total_etapas"]
    msg = info["mensagem"]
    novos = info["novos_provedores"]
    acumulado = info["total_acumulado"]
    erro = info.get("erro")

    if erro:
        _falhas_da_busca.append(erro)
        print(f"  ⚠ {msg}", file=sys.stderr)
    elif novos is None:
        # Etapa em andamento
        print(f"[{etapa}/{total}] {msg}")
    else:
        # Etapa concluída — imprime resultado indentado
        print(f"  ✔ {novos} novo(s) encontrado(s) | acumulado: {acumulado}")


# ---------------------------------------------------------------------------
# Modo interativo
# ---------------------------------------------------------------------------

def _ler_localizacao_interativa() -> tuple[str | None, tuple[float, float] | None]:
    """
    Solicita ao usuário endereço ou coordenadas via input.

    Returns:
        Tupla (endereco, coordenadas) — apenas um dos dois é preenchido.
    """
    print("\n┌─────────────────────────────────────────────────┐")
    print("│   Buscador de Provedores de Internet             │")
    print("└─────────────────────────────────────────────────┘\n")
    print("Como deseja informar a localização?")
    print("  [1] Endereço (ex: Itajaí, SC)")
    print("  [2] Coordenadas (ex: -26.90, -48.66)")

    while True:
        escolha = input("\nEscolha [1/2]: ").strip()
        if escolha == "1":
            endereco = input("Digite o endereço: ").strip()
            if endereco:
                return endereco, None
            print("  Endereço não pode ser vazio.")
        elif escolha == "2":
            try:
                lat = float(input("Latitude:  ").strip().replace(",", "."))
                lng = float(input("Longitude: ").strip().replace(",", "."))
                return None, (lat, lng)
            except ValueError:
                print("  Coordenadas inválidas. Use números decimais.")
        else:
            print("  Opção inválida. Digite 1 ou 2.")


def _ler_raio_interativo() -> int:
    """Solicita o raio de busca interativamente, com valor padrão."""
    entrada = input(f"\nRaio de busca em metros [padrão: {RAIO_PADRAO}]: ").strip()
    if not entrada:
        return RAIO_PADRAO
    try:
        raio = int(entrada)
        if raio <= 0:
            raise ValueError
        return raio
    except ValueError:
        print(f"  Valor inválido. Usando o padrão: {RAIO_PADRAO} m.")
        return RAIO_PADRAO


# ---------------------------------------------------------------------------
# Execução principal
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Ponto de entrada principal.

    Returns:
        0 em caso de sucesso, 1 em caso de erro.
    """
    parser = _criar_parser()
    args = parser.parse_args()
    _configurar_logging(args.verbose)

    # ---- Resolve a chave de API ----
    api_key = args.api_key or os.getenv("GOOGLE_MAPS_API_KEY", "")

    if not api_key:
        print(
            "\n[ERRO] Chave de API não encontrada.\n"
            "  Opção 1: crie um arquivo .env com GOOGLE_MAPS_API_KEY=sua_chave\n"
            "  Opção 2: passe --api-key SUA_CHAVE na linha de comando\n"
            "\nConsulte o README.md para obter sua chave.",
            file=sys.stderr,
        )
        return 1

    # ---- Aviso de segurança quando a chave é passada via CLI ----
    if args.api_key:
        print(
            "\n[AVISO DE SEGURANÇA] Você está passando a chave via --api-key.\n"
            "  A chave pode ficar exposta no histórico do shell (~/.bash_history)\n"
            "  e na lista de processos (ps aux) em máquinas compartilhadas.\n"
            "  Prefira usar o arquivo .env para maior segurança.\n",
            file=sys.stderr,
        )

    # ---- Resolve a localização ----
    endereco: str | None = args.endereco
    coordenadas: tuple[float, float] | None = (
        tuple(args.coordenadas) if args.coordenadas else None  # type: ignore[arg-type]
    )
    raio: int = args.raio

    # Modo interativo: acionado quando nenhuma localização é passada
    if not endereco and not coordenadas:
        try:
            endereco, coordenadas = _ler_localizacao_interativa()
            raio = _ler_raio_interativo()
        except (KeyboardInterrupt, EOFError):
            print("\n\nOperação cancelada pelo usuário.")
            return 0

    # ---- Exibe parâmetros da busca ----
    if endereco:
        print(f"\nLocalização: {endereco}")
    else:
        lat_c, lng_c = coordenadas  # type: ignore[misc]
        print(f"\nLocalização: {lat_c:.6f}, {lng_c:.6f}")
    print(f"Raio: {raio:,} m | Formato: {args.formato}\n")

    # ---- Delega toda a lógica ao serviço ----
    resultado = executar_busca(
        api_key=api_key,
        endereco=endereco,
        coordenadas=coordenadas,
        raio=raio,
        formato=args.formato,
        diretorio=args.saida,
        callback_progresso=_imprimir_progresso,
    )

    # ---- Trata erro retornado pelo serviço ----
    if resultado["erro"]:
        print(f"\n[ERRO] {resultado['erro']}", file=sys.stderr)
        return 1

    # ---- Exibe resumo ----
    total = resultado["total"]
    print(f"\n{'─' * 50}")

    if total == 0:
        # Zero resultados por falha de API é um caso diferente de zero
        # resultados por ausência de cadastro — e pede orientação diferente.
        # (O relatório de termos não se aplica: não há sobreposição a medir.)
        if _falhas_da_busca:
            print("Nenhum provedor encontrado: todas as buscas falharam.", file=sys.stderr)
            print(f"\nCausa: {_falhas_da_busca[0]}", file=sys.stderr)
            return 1

        print("Nenhum provedor de internet encontrado para esta localização.")
        print("Sugestões:")
        print("  • Aumente o raio com -r (ex: -r 20000)")
        print("  • Verifique se o endereço está correto")
        print("  • A região pode ter pouco cadastro no Google Maps")
        return 0

    print(f"Total de provedores encontrados: {total}")

    if resultado["arquivos"]:
        print("\nArquivo(s) gerado(s):")
        for arq in resultado["arquivos"]:
            print(f"  → {arq}")

    # ---- Relatório de sobreposição dos termos ----
    if args.relatorio_termos and resultado["analise_termos"]:
        analise = resultado["analise_termos"]
        total_reqs = sum(l["requisicoes"] for l in analise["termos"])
        print(formatar_relatorio(analise, requisicoes_totais=total_reqs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
