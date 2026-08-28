"""
service.py — Camada de serviço que orquestra busca e exportação.

Não depende de nenhum I/O interativo (sem print, input ou argparse).
Pode ser chamado diretamente por qualquer interface: CLI, API web, GUI
ou testes automatizados.

────────────────────────────────────────────────────────────────────────
Exemplo de uso em Flask:

    from flask import Flask, request, jsonify
    from service import executar_busca
    import os

    app = Flask(__name__)

    @app.route("/buscar")
    def buscar():
        resultado = executar_busca(
            api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
            endereco=request.args.get("endereco"),
            raio=int(request.args.get("raio", 5000)),
            formato="csv",
        )
        if resultado["erro"]:
            return jsonify({"erro": resultado["erro"]}), 400
        return jsonify({
            "total":      resultado["total"],
            "provedores": resultado["provedores"],
            "arquivos":   resultado["arquivos"],
        })

────────────────────────────────────────────────────────────────────────
Exemplo de uso em GUI (tkinter):

    from service import executar_busca

    def ao_clicar_buscar():
        def progresso(info: dict) -> None:
            if info["novos_provedores"] is not None:
                label_status.config(
                    text=f"[{info['etapa']}/{info['total_etapas']}] "
                         f"{info['novos_provedores']} novo(s) | "
                         f"total: {info['total_acumulado']}"
                )
                janela.update_idletasks()

        resultado = executar_busca(
            api_key=entry_api_key.get(),
            endereco=entry_endereco.get(),
            raio=int(entry_raio.get() or 5000),
            callback_progresso=progresso,
        )
        label_resultado.config(
            text=f"{resultado['total']} provedores encontrados."
                 if not resultado["erro"]
                 else f"Erro: {resultado['erro']}"
        )
────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Callable, Optional

from analise_termos import analisar
from buscador import BuscadorProvedores, ErroAPI, ErroLocalizacao
from config import DIRETORIO_SAIDA, RAIO_PADRAO
from exportador import exportar_resultados

logger = logging.getLogger(__name__)


def executar_busca(
    api_key: str,
    endereco: Optional[str] = None,
    coordenadas: Optional[tuple[float, float]] = None,
    raio: int = RAIO_PADRAO,
    formato: str = "csv",
    diretorio: str = DIRETORIO_SAIDA,
    callback_progresso: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    Executa a busca de provedores de internet e exporta os resultados.

    Não usa print() nem input() — adequado para qualquer interface.

    Args:
        api_key: Chave da Google Maps API.
        endereco: Endereço textual (alternativo a coordenadas).
        coordenadas: Tupla (lat, lng) em graus decimais.
        raio: Raio de busca em metros.
        formato: "csv", "excel" ou "ambos".
        diretorio: Pasta onde salvar os arquivos exportados.
        callback_progresso: Função chamada a cada atualização de progresso.
            Recebe um dict com as chaves: etapa, total_etapas, mensagem,
            novos_provedores, total_acumulado e erro.
            Ver BuscadorProvedores.buscar_todos.

    Returns:
        Dict com:
            "provedores"  : list[dict] — dados de cada provedor encontrado
                            (inclui latitude, longitude e distancia_km)
            "arquivos"    : list[str]  — caminhos absolutos dos arquivos gerados
            "total"       : int        — quantidade de provedores encontrados
            "coordenadas" : tuple[float, float] | None — lat/lng usadas na busca
            "erro"        : str | None — mensagem de erro, ou None se bem-sucedido
            "analise_termos" : dict — sobreposição entre os termos de busca,
                            calculada a partir dos dados que a própria busca já
                            produziu, sem nenhuma requisição extra à API.
                            Ver analise_termos.analisar().
    """
    # Toda condição de erro sai como dict com a chave "erro" preenchida —
    # esta camada nunca levanta exceção para quem a chama.
    if not api_key:
        return _erro("Chave de API não fornecida.")

    if not endereco and not coordenadas:
        return _erro("Nenhuma localização fornecida (informe 'endereco' ou 'coordenadas').")

    # O context manager garante a gravação do cache, o fechamento da sessão HTTP
    # e a remoção do filtro de log ao final. Sem ele, um servidor que chama esta
    # função a cada requisição acumula filtros no logging global indefinidamente.
    with BuscadorProvedores(api_key=api_key) as buscador:
        # --- Geocodificação ---
        if endereco:
            try:
                lat, lng = buscador.geocodificar(endereco)
                logger.info("Geocodificação concluída: (%.6f, %.6f)", lat, lng)
            except (ErroLocalizacao, ErroAPI, ConnectionError) as exc:
                return _erro(str(exc))
        else:
            lat, lng = coordenadas  # type: ignore[misc]

        # --- Busca ---
        try:
            provedores = buscador.buscar_todos(
                lat=lat,
                lng=lng,
                raio=raio,
                callback_progresso=callback_progresso,
            )
        except (ConnectionError, ErroAPI) as exc:
            return _erro(str(exc))

        # Colhido ainda dentro do bloco: são atributos da instância, que sai
        # de escopo ao fim do with.
        analise = analisar(buscador.ids_por_termo, buscador.requisicoes_por_termo)

    if not provedores:
        return {
            "provedores": [],
            "arquivos": [],
            "total": 0,
            "coordenadas": (lat, lng),
            "erro": None,
            "analise_termos": analise,
        }

    # --- Exportação ---
    try:
        caminhos = exportar_resultados(
            dados=provedores,
            formato=formato,
            diretorio=diretorio,
        )
        arquivos = [str(c) for c in caminhos]
    except (ImportError, PermissionError, ValueError) as exc:
        logger.error("Falha na exportação: %s", exc)
        # Retorna os dados mesmo sem os arquivos, com erro descritivo
        return {
            "provedores": provedores,
            "arquivos": [],
            "total": len(provedores),
            "coordenadas": (lat, lng),
            "erro": f"Busca concluída, mas falha ao exportar: {exc}",
            "analise_termos": analise,
        }

    return {
        "provedores": provedores,
        "arquivos": arquivos,
        "total": len(provedores),
        "coordenadas": (lat, lng),
        "erro": None,
        "analise_termos": analise,
    }


def _erro(mensagem: str) -> dict:
    """
    Monta um dict de resultado padronizado para situações de erro.

    O registro é feito em DEBUG, e não em ERROR, de propósito: a mensagem já
    volta na chave "erro" para quem chamou, e é dessa camada a responsabilidade
    de exibi-la. Registrar em ERROR fazia o mesmo texto aparecer duas vezes no
    terminal — uma como log e outra como mensagem formatada da CLI.
    """
    logger.debug("executar_busca encerrado com erro: %s", mensagem)
    return {
        "provedores": [],
        "arquivos": [],
        "total": 0,
        "coordenadas": None,
        "erro": mensagem,
        "analise_termos": {},
    }
