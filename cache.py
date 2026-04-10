"""
cache.py — Cache local de Place Details para reduzir chamadas à API.

Os dados são persistidos em um arquivo JSON indexado por place_id.
Falhas de leitura ou gravação nunca interrompem a execução — apenas
geram um aviso de log, garantindo que o cache seja transparente para
o restante da aplicação.
"""

import json
import logging
from pathlib import Path

from config import CAMINHO_CACHE

logger = logging.getLogger(__name__)


def carregar_cache(caminho: str = CAMINHO_CACHE) -> dict:
    """
    Lê o arquivo de cache do disco e retorna um dict indexado por place_id.

    Se o arquivo não existir ou estiver corrompido, retorna um dict vazio
    sem lançar exceção.

    Args:
        caminho: Caminho do arquivo JSON de cache.

    Returns:
        Dict {place_id: dados_do_lugar} ou {} em caso de falha.
    """
    arquivo = Path(caminho)
    if not arquivo.exists():
        logger.debug("Arquivo de cache '%s' não encontrado. Iniciando vazio.", caminho)
        return {}

    try:
        with open(arquivo, encoding="utf-8") as arq:
            dados = json.load(arq)

        if not isinstance(dados, dict):
            logger.warning(
                "Cache '%s' tem formato inesperado (esperado dict). Ignorando.", caminho
            )
            return {}

        logger.debug("Cache carregado: %d entrada(s) em '%s'.", len(dados), caminho)
        return dados

    except json.JSONDecodeError as exc:
        logger.warning(
            "Cache '%s' está corrompido e será ignorado: %s", caminho, exc
        )
        return {}
    except OSError as exc:
        logger.warning("Falha ao ler cache '%s': %s", caminho, exc)
        return {}


def salvar_cache(dados: dict, caminho: str = CAMINHO_CACHE) -> None:
    """
    Persiste o dict de cache no disco em formato JSON.

    Falhas de gravação são registradas como aviso mas não interrompem
    a execução.

    Args:
        dados: Dict completo {place_id: dados_do_lugar} a ser salvo.
        caminho: Caminho do arquivo JSON de cache.
    """
    try:
        with open(caminho, "w", encoding="utf-8") as arq:
            json.dump(dados, arq, ensure_ascii=False, indent=2)
        logger.debug("Cache salvo: %d entrada(s) em '%s'.", len(dados), caminho)
    except OSError as exc:
        logger.warning("Falha ao salvar cache '%s': %s", caminho, exc)
