"""Testes de cache.py — leitura e gravação tolerantes a falha."""

import json

from cache import carregar_cache, salvar_cache


def test_arquivo_inexistente_retorna_dict_vazio(tmp_path):
    assert carregar_cache(str(tmp_path / "nao_existe.json")) == {}


def test_json_corrompido_nao_levanta_excecao(tmp_path):
    arquivo = tmp_path / "cache.json"
    arquivo.write_text("{isso não é json válido", encoding="utf-8")
    assert carregar_cache(str(arquivo)) == {}


def test_json_valido_mas_nao_dict_e_ignorado(tmp_path):
    """Um array no lugar de um objeto quebraria as buscas por place_id."""
    arquivo = tmp_path / "cache.json"
    arquivo.write_text('["a", "b"]', encoding="utf-8")
    assert carregar_cache(str(arquivo)) == {}


def test_ida_e_volta_preserva_acentuacao(tmp_path):
    arquivo = str(tmp_path / "cache.json")
    dados = {"pid1": {"name": "Provedor Ação & Cia", "rating": 4.7}}

    salvar_cache(dados, arquivo)
    assert carregar_cache(arquivo) == dados

    # ensure_ascii=False: o arquivo deve ficar legível para inspeção manual
    assert "Ação" in json.loads(open(arquivo, encoding="utf-8").read())["pid1"]["name"]


def test_falha_de_gravacao_nao_interrompe(tmp_path):
    """Caminho inválido gera aviso, nunca exceção — o cache é acessório."""
    salvar_cache({"pid": {}}, str(tmp_path / "pasta_inexistente" / "cache.json"))
