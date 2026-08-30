# -*- mode: python ; coding: utf-8 -*-
"""
empacotar.spec — Receita do PyInstaller para gerar o executável.

    pip install pyinstaller
    pyinstaller empacotar.spec

O resultado sai em dist/. Rode o comando NO SISTEMA DE DESTINO: o PyInstaller
não faz compilação cruzada. Para gerar o .exe do Windows é preciso rodar num
Windows; o binário gerado no Linux só roda em Linux.

Sobre o tamanho: pandas e numpy foram removidos do projeto (a exportação em
Excel usa openpyxl diretamente), o que mantém o executável na casa de dezenas
de megabytes em vez de centenas.

A chave de API NÃO é embutida e nem deve ser. Cada usuário informa a sua na
primeira execução, e ela fica gravada na pasta de configuração do próprio
usuário. Uma chave embutida seria extraível do binário por qualquer pessoa que
recebesse o arquivo.
"""

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=[],
    # Os módulos do projeto são descobertos pelos imports de gui.py.
    datas=[("README.md", ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Nada aqui é usado pelo projeto; excluir reduz o tamanho e o tempo de análise.
    excludes=[
        "pandas",
        "numpy",
        "matplotlib",
        "scipy",
        "PIL",
        "pytest",
        "IPython",
        "notebook",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BuscadorProvedores",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Sem console: é um programa de janela. Para depurar um problema que só
    # aparece no executável, troque para True e as mensagens de erro do Python
    # passam a aparecer numa janela de terminal.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
