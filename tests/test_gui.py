"""
Testes dos auxiliares da interface gráfica.

Só as funções puras — construir a janela exige um servidor gráfico, que não
existe em integração contínua. A lógica que pode errar em silêncio (ordenação
da tabela, comando de abrir pasta) vive fora dos widgets justamente para poder
ser testada aqui.
"""

import gui


def test_ordena_numeros_por_grandeza_e_nao_por_texto():
    """Sem isso, "10" viria antes de "9" na coluna de distância."""
    valores = ["10.5", "9.2", "100"]
    assert sorted(valores, key=gui.valor_para_ordenacao) == ["9.2", "10.5", "100"]


def test_celulas_vazias_vao_para_o_fim():
    """Vazio é ausência de dado, não valor pequeno — não pode liderar a ordenação."""
    valores = ["3.0", "", "1.5"]
    assert sorted(valores, key=gui.valor_para_ordenacao) == ["1.5", "3.0", ""]


def test_aceita_virgula_como_separador_decimal():
    assert gui.valor_para_ordenacao("3,5") == gui.valor_para_ordenacao("3.5")


def test_texto_ordena_ignorando_maiusculas():
    valores = ["beta", "Alfa", "gama"]
    assert sorted(valores, key=gui.valor_para_ordenacao) == ["Alfa", "beta", "gama"]


def test_numeros_vem_antes_de_texto():
    assert sorted(["Alfa", "1.0"], key=gui.valor_para_ordenacao) == ["1.0", "Alfa"]


def test_comando_de_abrir_pasta_por_sistema(monkeypatch):
    import platform

    for sistema, esperado in [
        ("Windows", "explorer"), ("Darwin", "open"), ("Linux", "xdg-open"),
    ]:
        monkeypatch.setattr(platform, "system", lambda s=sistema: s)
        comando = gui.comando_abrir_pasta("/tmp/x")
        assert comando[0] == esperado
        assert comando[-1] == "/tmp/x"


def test_comando_de_abrir_pasta_e_lista_e_nao_string(monkeypatch):
    """
    Lista de argumentos, sem shell: o caminho vem de um seletor de arquivos,
    mas concatenar numa string de shell deixaria metacaracteres serem
    interpretados sem necessidade alguma.
    """
    comando = gui.comando_abrir_pasta("/tmp/pasta com espaço; echo oi")
    assert isinstance(comando, list)
    assert comando[-1] == "/tmp/pasta com espaço; echo oi"


def test_mensagem_de_erro_inesperado_traz_o_tipo_e_a_saida():
    texto = gui.texto_do_erro(ValueError("algo quebrou"))
    assert "ValueError" in texto
    assert "algo quebrou" in texto
    assert "-v" in texto      # aponta o caminho para investigar


def test_credito_do_google_esta_definido():
    """
    As políticas exigem crédito visível ao exibir dados de Places fora de um
    mapa do Google. O rodapé usa esta constante.
    """
    assert "Google Maps" in gui.CREDITO
