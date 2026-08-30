"""
dialogos.py — Caixas de diálogo reutilizadas pela interface.

Fica separado de gui.py e de assistente.py porque os dois precisam do mesmo
diálogo de erro, e gui.py já importa assistente.py — colocá-lo em qualquer um
dos dois criaria ciclo de importação.

Não importa diagnostico.py nem nada da camada de busca: recebe o dicionário de
diagnóstico pronto e apenas o apresenta.
"""

import tkinter as tk
import webbrowser
from tkinter import ttk


def mostrar_diagnostico(pai: tk.Misc, diag: dict, titulo_janela: str = "Erro") -> None:
    """
    Exibe a causa provável de um erro e o caminho de correção.

    Em vez de repassar a mensagem em inglês do Google — que é a mesma para
    causas bem diferentes —, mostra o que aconteceu, por quê, os passos de
    correção e um botão que abre a página exata onde resolver.

    Args:
        pai: Janela sobre a qual o diálogo aparece.
        diag: Saída de diagnostico.diagnosticar() e afins.
        titulo_janela: Texto da barra de título.
    """
    if not diag:
        return

    janela = tk.Toplevel(pai)
    janela.title(titulo_janela)
    janela.resizable(False, False)
    janela.transient(pai)

    moldura = ttk.Frame(janela, padding=18)
    moldura.pack(fill="both", expand=True)

    ttk.Label(
        moldura, text=diag["titulo"], wraplength=520, justify="left",
        font=("TkDefaultFont", 11, "bold"),
    ).pack(anchor="w")

    ttk.Label(
        moldura, text=diag["explicacao"], wraplength=520, justify="left",
    ).pack(anchor="w", pady=(10, 0))

    if diag.get("correcao"):
        ttk.Label(
            moldura, text="Como corrigir:", font=("TkDefaultFont", 9, "bold"),
        ).pack(anchor="w", pady=(14, 4))
        for numero, passo in enumerate(diag["correcao"], start=1):
            ttk.Label(
                moldura, text=f"{numero}.  {passo}", wraplength=500, justify="left",
            ).pack(anchor="w", padx=(8, 0), pady=1)

    # A mensagem original do Google fica disponível, mas discreta: serve a quem
    # for pesquisar ou pedir suporte, e só confundiria em primeiro plano.
    if diag.get("mensagem_original"):
        ttk.Separator(moldura, orient="horizontal").pack(fill="x", pady=(14, 8))
        ttk.Label(
            moldura, text=f"Mensagem original do Google:\n{diag['mensagem_original']}",
            wraplength=520, justify="left", foreground="#666666",
        ).pack(anchor="w")

    # --- Ações ---
    acoes = ttk.Frame(moldura)
    acoes.pack(fill="x", pady=(18, 0))

    if diag.get("url"):
        ttk.Button(
            acoes, text="Abrir página de correção",
            command=lambda: webbrowser.open(diag["url"]),
        ).pack(side="left")

    def copiar() -> None:
        linhas = [diag["titulo"], "", diag["explicacao"], ""]
        linhas += [f"{i}. {p}" for i, p in enumerate(diag.get("correcao", []), start=1)]
        if diag.get("mensagem_original"):
            linhas += ["", diag["mensagem_original"]]
        janela.clipboard_clear()
        janela.clipboard_append("\n".join(linhas))

    ttk.Button(acoes, text="Copiar detalhes", command=copiar).pack(side="left", padx=8)
    ttk.Button(acoes, text="Fechar", command=janela.destroy).pack(side="right")

    janela.update_idletasks()
    x = pai.winfo_rootx() + (pai.winfo_width() - janela.winfo_width()) // 2
    y = pai.winfo_rooty() + (pai.winfo_height() - janela.winfo_height()) // 3
    janela.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    janela.grab_set()
    pai.wait_window(janela)
