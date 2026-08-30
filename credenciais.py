"""
credenciais.py — Localização e guarda da chave de API.

Ao distribuir o programa para outras pessoas, cada usuário precisa da PRÓPRIA
chave do Google Cloud. Embutir uma chave única no executável não funciona:
qualquer pessoa com o arquivo consegue extraí-la, e todo o consumo — inclusive
o de quem não deveria ter acesso — cai na fatura de uma conta só, sem forma de
identificar quem gastou ou de revogar o acesso de um usuário específico.

A chave é procurada nesta ordem:
  1. Variável de ambiente GOOGLE_MAPS_API_KEY
  2. Arquivo .env no diretório atual (prático durante o desenvolvimento)
  3. Arquivo de configuração do usuário (usado pela interface gráfica)

O arquivo do usuário fica na pasta de configuração do sistema operacional, e
não junto do executável: em instalações no "Program Files" ou equivalentes a
pasta do programa costuma ser somente leitura.
"""

import os
import stat
from pathlib import Path

NOME_VARIAVEL = "GOOGLE_MAPS_API_KEY"
PASTA_APLICACAO = "buscador-provedores"

# Chaves do Google Maps começam com "AIza" e têm 39 caracteres. Serve apenas
# para avisar sobre erros de digitação — não substitui a validação real, que
# só a API pode fazer.
_PREFIXO_ESPERADO = "AIza"
_COMPRIMENTO_ESPERADO = 39


def caminho_config() -> Path:
    """
    Caminho do arquivo de configuração do usuário.

    Windows: %APPDATA%\\buscador-provedores\\.env
    Linux/macOS: ~/.config/buscador-provedores/.env
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / PASTA_APLICACAO / ".env"


def _ler_de_arquivo(caminho: Path) -> str:
    """Extrai o valor da variável de um arquivo .env, ou "" se não houver."""
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""

    for linha in linhas:
        limpa = linha.strip()
        if limpa.startswith("#") or "=" not in limpa:
            continue
        nome, _, valor = limpa.partition("=")
        if nome.strip() == NOME_VARIAVEL:
            # Aspas são comuns em arquivos .env escritos à mão
            return valor.strip().strip('"').strip("'")
    return ""


def carregar_chave(caminho_local: Path | None = None) -> tuple[str, str]:
    """
    Procura a chave nas origens conhecidas, na ordem de prioridade.

    Args:
        caminho_local: Sobrepõe o ".env" do diretório atual. Usado nos testes.

    Returns:
        Tupla (chave, origem). A origem é um texto curto para exibir na
        interface. Ambos vêm vazios quando nenhuma chave é encontrada.
    """
    da_variavel = os.environ.get(NOME_VARIAVEL, "").strip()
    if da_variavel:
        return da_variavel, "variável de ambiente"

    local = caminho_local if caminho_local is not None else Path(".env")
    for caminho in (local, caminho_config()):
        chave = _ler_de_arquivo(caminho)
        if chave:
            return chave, str(caminho)

    return "", ""


def salvar_chave(chave: str, caminho: Path | None = None) -> Path:
    """
    Grava a chave no arquivo de configuração, preservando as demais variáveis.

    No Linux e no macOS o arquivo recebe permissão 600 (leitura e escrita
    apenas para o dono). A chave fica em texto puro — este arquivo não deve ser
    versionado, anexado em e-mail nem copiado para pastas compartilhadas.

    Args:
        chave: Valor a gravar.
        caminho: Destino. Quando omitido, usa caminho_config().

    Returns:
        O caminho efetivamente gravado.

    Raises:
        ValueError: Se a chave estiver vazia.
        OSError: Se não for possível criar a pasta ou gravar o arquivo.
    """
    chave = chave.strip()
    if not chave:
        raise ValueError("A chave de API não pode ser vazia.")

    destino = caminho or caminho_config()
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Preserva as outras variáveis já presentes no arquivo
    linhas: list[str] = []
    substituida = False
    try:
        linhas = destino.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        linhas = []

    for i, linha in enumerate(linhas):
        nome = linha.split("=", 1)[0].strip()
        if nome == NOME_VARIAVEL and not linha.strip().startswith("#"):
            linhas[i] = f"{NOME_VARIAVEL}={chave}"
            substituida = True
            break

    if not substituida:
        linhas.append(f"{NOME_VARIAVEL}={chave}")

    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    if os.name != "nt":
        destino.chmod(stat.S_IRUSR | stat.S_IWUSR)   # 600

    # Passa a valer para o processo atual, sem exigir reinício
    os.environ[NOME_VARIAVEL] = chave
    return destino


def formato_plausivel(chave: str) -> bool:
    """
    Confere se a chave tem a cara de uma chave do Google Maps.

    Serve para avisar sobre erro de digitação ou colagem incompleta antes de
    gastar uma requisição. Uma chave com formato válido ainda pode ser recusada
    pela API — só ela sabe se a chave existe e tem as APIs ativadas.
    """
    chave = chave.strip()
    return chave.startswith(_PREFIXO_ESPERADO) and len(chave) == _COMPRIMENTO_ESPERADO


def mascarar(chave: str) -> str:
    """
    Versão da chave segura para exibir em tela ou relatório.

    Mantém o início e o fim, que bastam para o usuário reconhecer qual chave
    está em uso, e esconde o miolo.
    """
    chave = chave.strip()
    if not chave:
        return "(nenhuma)"
    if len(chave) <= 12:
        return "•" * len(chave)
    return f"{chave[:6]}{'•' * 8}{chave[-4:]}"
