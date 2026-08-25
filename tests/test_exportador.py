"""Testes de exportador.py — geração de CSV e Excel."""

import csv

import pytest

from config import COLUNAS_SAIDA
from exportador import exportar_csv, exportar_excel, exportar_resultados

DADOS = [
    {
        "nome": "Provedor Alfa",
        "endereco": "Rua Um, 100",
        "telefone": "(48) 3333-0000",
        "site": "https://alfa.example.com",
        "distancia_km": 1.23,
        "avaliacao": 4.5,
        "total_avaliacoes": 120,
        "status": "Operacional",
        "latitude": -27.5954,
        "longitude": -48.5480,
        "place_id": "pid_alfa",
    },
    # Registro incompleto: campos ausentes devem virar string vazia, não KeyError
    {"nome": "Provedor Beta", "place_id": "pid_beta"},
]


def test_csv_tem_todas_as_colunas_na_ordem_configurada(tmp_path):
    caminho = exportar_csv(DADOS, str(tmp_path))

    with open(caminho, encoding="utf-8-sig") as arq:
        linhas = list(csv.DictReader(arq))

    assert list(linhas[0].keys()) == list(COLUNAS_SAIDA.values())
    assert linhas[0]["Nome"] == "Provedor Alfa"
    assert linhas[0]["Distância (km)"] == "1.23"
    assert linhas[0]["Latitude"] == "-27.5954"


def test_csv_preenche_campos_ausentes_com_vazio(tmp_path):
    caminho = exportar_csv(DADOS, str(tmp_path))

    with open(caminho, encoding="utf-8-sig") as arq:
        linhas = list(csv.DictReader(arq))

    assert linhas[1]["Telefone"] == ""
    assert linhas[1]["Distância (km)"] == ""


def test_csv_usa_bom_para_abrir_certo_no_excel(tmp_path):
    """Sem o BOM, o Excel no Windows exibe 'Endereço' como 'EndereÃ§o'."""
    caminho = exportar_csv(DADOS, str(tmp_path))
    assert open(caminho, "rb").read(3) == b"\xef\xbb\xbf"


def test_cria_diretorio_inexistente(tmp_path):
    destino = tmp_path / "novo" / "subpasta"
    caminho = exportar_csv(DADOS, str(destino))
    assert caminho.exists()


def test_nomes_de_arquivo_nao_colidem(tmp_path):
    """Timestamp no nome evita sobrescrever resultado anterior."""
    primeiro = exportar_csv(DADOS, str(tmp_path))
    assert primeiro.name.startswith("provedores_")
    assert primeiro.suffix == ".csv"


def test_formato_invalido_levanta_value_error(tmp_path):
    with pytest.raises(ValueError, match="Formato inválido"):
        exportar_resultados(DADOS, formato="pdf", diretorio=str(tmp_path))


def test_lista_vazia_nao_gera_arquivo(tmp_path):
    assert exportar_resultados([], formato="ambos", diretorio=str(tmp_path)) == []
    assert list(tmp_path.iterdir()) == []


def test_formato_ambos_gera_dois_arquivos(tmp_path):
    arquivos = exportar_resultados(DADOS, formato="ambos", diretorio=str(tmp_path))
    assert len(arquivos) == 2
    assert {a.suffix for a in arquivos} == {".csv", ".xlsx"}


def test_excel_tem_cabecalho_congelado_e_filtro(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("pandas")

    caminho = exportar_excel(DADOS, str(tmp_path))
    planilha = openpyxl.load_workbook(caminho)["Provedores"]

    assert planilha.freeze_panes == "A2"
    assert planilha.auto_filter.ref is not None
    assert [c.value for c in planilha[1]] == list(COLUNAS_SAIDA.values())
