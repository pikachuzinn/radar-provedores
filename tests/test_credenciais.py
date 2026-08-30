"""
Testes de credenciais.py — descoberta e guarda da chave de API.

Distribuir o programa significa que cada usuário traz a própria chave. O que
está em jogo aqui: encontrar a chave onde ela estiver, gravá-la sem destruir o
resto do arquivo, e nunca exibi-la inteira na tela.
"""

import os
import stat

import pytest

import credenciais


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """
    A variável de ambiente tem prioridade — remove para não mascarar os testes.

    A limpeza no final é necessária: salvar_chave() define a variável no
    processo, para que a chave valha de imediato sem reiniciar. Sem remover
    depois, ela vazaria para os testes seguintes.
    """
    monkeypatch.delenv(credenciais.NOME_VARIAVEL, raising=False)
    yield
    os.environ.pop(credenciais.NOME_VARIAVEL, None)


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def test_variavel_de_ambiente_tem_prioridade(monkeypatch, tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text("GOOGLE_MAPS_API_KEY=do-arquivo\n", encoding="utf-8")
    monkeypatch.setenv(credenciais.NOME_VARIAVEL, "do-ambiente")

    chave, origem = credenciais.carregar_chave(caminho_local=arquivo)

    assert chave == "do-ambiente"
    assert origem == "variável de ambiente"


def test_le_do_arquivo_local(tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text("GOOGLE_MAPS_API_KEY=abc123\n", encoding="utf-8")

    chave, origem = credenciais.carregar_chave(caminho_local=arquivo)

    assert chave == "abc123"
    assert str(arquivo) in origem


def test_ignora_comentarios_e_outras_variaveis(tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "# GOOGLE_MAPS_API_KEY=comentada\n"
        "OUTRA_COISA=valor\n"
        "GOOGLE_MAPS_API_KEY=a-verdadeira\n",
        encoding="utf-8",
    )
    assert credenciais.carregar_chave(caminho_local=arquivo)[0] == "a-verdadeira"


def test_remove_aspas_do_valor(tmp_path):
    """Arquivos .env escritos à mão costumam vir com aspas."""
    arquivo = tmp_path / ".env"
    arquivo.write_text('GOOGLE_MAPS_API_KEY="com-aspas"\n', encoding="utf-8")
    assert credenciais.carregar_chave(caminho_local=arquivo)[0] == "com-aspas"


def test_sem_chave_em_lugar_nenhum(tmp_path, monkeypatch):
    monkeypatch.setattr(credenciais, "caminho_config", lambda: tmp_path / "nada" / ".env")
    assert credenciais.carregar_chave(caminho_local=tmp_path / "ausente") == ("", "")


def test_arquivo_ilegivel_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setattr(credenciais, "caminho_config", lambda: tmp_path / "nada" / ".env")
    # Um diretório no lugar do arquivo: a leitura falha, mas sem exceção
    pasta = tmp_path / ".env"
    pasta.mkdir()
    assert credenciais.carregar_chave(caminho_local=pasta) == ("", "")


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------

def test_grava_e_le_de_volta(tmp_path):
    destino = tmp_path / "config" / ".env"
    credenciais.salvar_chave("minha-chave", destino)

    assert credenciais._ler_de_arquivo(destino) == "minha-chave"
    assert os.environ[credenciais.NOME_VARIAVEL] == "minha-chave"


def test_preserva_as_outras_variaveis(tmp_path):
    """O .env pode ter outras configurações — salvar a chave não pode apagá-las."""
    destino = tmp_path / ".env"
    destino.write_text("OUTRA=preservar\nGOOGLE_MAPS_API_KEY=antiga\nMAIS_UMA=tambem\n",
                       encoding="utf-8")

    credenciais.salvar_chave("nova", destino)
    conteudo = destino.read_text(encoding="utf-8")

    assert "OUTRA=preservar" in conteudo
    assert "MAIS_UMA=tambem" in conteudo
    assert "GOOGLE_MAPS_API_KEY=nova" in conteudo
    assert "antiga" not in conteudo


def test_acrescenta_quando_a_variavel_nao_existe(tmp_path):
    destino = tmp_path / ".env"
    destino.write_text("OUTRA=valor\n", encoding="utf-8")

    credenciais.salvar_chave("nova", destino)

    assert "OUTRA=valor" in destino.read_text(encoding="utf-8")
    assert credenciais._ler_de_arquivo(destino) == "nova"


def test_nao_reativa_linha_comentada(tmp_path):
    destino = tmp_path / ".env"
    destino.write_text("# GOOGLE_MAPS_API_KEY=desativada\n", encoding="utf-8")

    credenciais.salvar_chave("nova", destino)
    linhas = destino.read_text(encoding="utf-8").splitlines()

    assert "# GOOGLE_MAPS_API_KEY=desativada" in linhas
    assert "GOOGLE_MAPS_API_KEY=nova" in linhas


@pytest.mark.skipif(os.name == "nt", reason="permissões POSIX")
def test_arquivo_fica_legivel_so_pelo_dono(tmp_path):
    """A chave fica em texto puro — outros usuários da máquina não devem lê-la."""
    destino = tmp_path / ".env"
    credenciais.salvar_chave("segredo", destino)

    modo = stat.S_IMODE(destino.stat().st_mode)
    assert modo == 0o600


def test_chave_vazia_e_recusada(tmp_path):
    with pytest.raises(ValueError):
        credenciais.salvar_chave("   ", tmp_path / ".env")


def test_caminho_config_respeita_o_sistema(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert credenciais.caminho_config() == tmp_path / "buscador-provedores" / ".env"


# ---------------------------------------------------------------------------
# Formato e exibição
# ---------------------------------------------------------------------------

def test_reconhece_formato_de_chave_do_google():
    assert credenciais.formato_plausivel("AIza" + "b" * 35)      # 39 caracteres
    assert not credenciais.formato_plausivel("AIza" + "b" * 10)  # curta demais
    assert not credenciais.formato_plausivel("XYza" + "b" * 35)  # prefixo errado
    assert not credenciais.formato_plausivel("")


def test_mascarar_nunca_revela_o_miolo():
    chave = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"
    mascarada = credenciais.mascarar(chave)

    assert chave not in mascarada
    assert mascarada.startswith("AIzaSy")
    assert mascarada.endswith(chave[-4:])
    assert "•" in mascarada


def test_mascarar_chave_curta_esconde_tudo():
    assert credenciais.mascarar("curta") == "•••••"
    assert credenciais.mascarar("") == "(nenhuma)"
