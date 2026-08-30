"""
assistente.py — Assistente de primeira execução.

Quem instala o programa pela primeira vez precisa criar uma chave no Google
Cloud, e é aí que a maioria trava. Três tropeços respondem por quase todo o
suporte:

  1. Não ativar o faturamento. É obrigatório mesmo para usar apenas a cota
     gratuita, e sem ele toda chamada é recusada.
  2. Ativar "Places API" em vez de "Places API (New)". São produtos distintos
     no Console, com nomes quase iguais, e a legada sequer pode ser ativada em
     projetos criados a partir de 01/03/2025.
  3. Restringir a chave a APIs erradas, o que produz o mesmo erro de permissão
     de uma chave inválida.

O assistente conduz passo a passo, com botões que abrem a página exata do
Console em cada etapa, e termina verificando a chave de verdade — para que o
usuário saia daqui com algo que funciona, e não com uma dúvida.

As etapas são dados (PASSOS), separadas da interface, para poderem ser
conferidas por teste sem abrir janela.
"""

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import credenciais
from service import testar_chave

TITULO = "Configuração inicial"

# Páginas do Google Cloud Console usadas pelos botões de cada passo.
URL_PROJETO = "https://console.cloud.google.com/projectcreate"
URL_FATURAMENTO = "https://console.cloud.google.com/billing"
URL_PLACES_NOVA = "https://console.cloud.google.com/apis/library/places.googleapis.com"
URL_GEOCODING = "https://console.cloud.google.com/apis/library/geocoding-backend.googleapis.com"
URL_CREDENCIAIS = "https://console.cloud.google.com/apis/credentials"
URL_PRECOS = "https://developers.google.com/maps/billing-and-pricing/pricing"


PASSOS: list[dict] = [
    {
        "titulo": "Antes de começar",
        "texto": (
            "Este programa consulta o Google Maps para encontrar provedores de "
            "internet numa região.\n\n"
            "Para isso é preciso uma chave de API própria, criada na sua conta "
            "Google. A chave é individual: ela identifica quem fez cada consulta "
            "e permite acompanhar o consumo.\n\n"
            "A configuração leva cerca de 5 minutos e é feita uma única vez.\n\n"
            "Sobre o custo: o Google oferece cotas gratuitas mensais. Com a "
            "configuração padrão deste programa, cabem cerca de 66 buscas "
            "completas por mês sem nenhuma cobrança."
        ),
        "links": [("Ver a tabela de preços do Google", URL_PRECOS)],
        "confirmacao": None,
    },
    {
        "titulo": "Passo 1 — Projeto e faturamento",
        "texto": (
            "Crie um projeto no Google Cloud e associe uma conta de faturamento "
            "a ele.\n\n"
            "O faturamento é obrigatório mesmo para quem vai usar somente a cota "
            "gratuita — sem ele, o Google recusa todas as chamadas. Ficando "
            "dentro da cota, não há cobrança.\n\n"
            "Contas novas ainda recebem um crédito de US$ 300, válido por 90 dias."
        ),
        "links": [
            ("1. Criar um projeto", URL_PROJETO),
            ("2. Ativar o faturamento", URL_FATURAMENTO),
        ],
        "confirmacao": "Criei o projeto e ativei o faturamento",
    },
    {
        "titulo": "Passo 2 — Ativar as duas APIs",
        "texto": (
            "Com o projeto selecionado, ative as duas APIs abaixo. Cada botão "
            "abre a página exata — basta clicar em ATIVAR.\n\n"
            "ATENÇÃO ao nome: no Console existem \"Places API\" e \"Places API "
            "(New)\". São produtos diferentes, e este programa usa a (New). A "
            "antiga foi congelada em 01/03/2025 e nem aparece em projetos "
            "criados depois dessa data.\n\n"
            "Os botões abaixo já levam à página certa, sem risco de confusão."
        ),
        "links": [
            ("1. Ativar Places API (New)", URL_PLACES_NOVA),
            ("2. Ativar Geocoding API", URL_GEOCODING),
        ],
        "confirmacao": "Ativei a Places API (New) e a Geocoding API",
    },
    {
        "titulo": "Passo 3 — Criar a chave",
        "texto": (
            "Na página de credenciais, clique em CRIAR CREDENCIAIS e escolha "
            "Chave de API. Copie a chave gerada — ela começa com \"AIza\" e tem "
            "39 caracteres.\n\n"
            "Recomendado: logo depois, clique na chave recém-criada e, em "
            "Restrições de API, selecione somente Places API (New) e Geocoding "
            "API. Assim, se a chave vazar, ela não serve para mais nada.\n\n"
            "Cuidado para não restringir a APIs erradas: o erro que aparece é o "
            "mesmo de uma chave inválida, e confunde bastante."
        ),
        "links": [("Abrir a página de credenciais", URL_CREDENCIAIS)],
        "confirmacao": "Criei a chave e copiei o valor",
    },
    {
        "titulo": "Passo 4 — Colar e verificar",
        "texto": (
            "Cole a chave abaixo e clique em Verificar. O teste faz uma única "
            "consulta de endereço, dentro da cota gratuita, e confirma se está "
            "tudo certo antes de você começar a usar.\n\n"
            "A chave é gravada apenas no seu computador, na sua pasta de "
            "configuração de usuário."
        ),
        "links": [],
        "confirmacao": None,
        "campo_chave": True,
    },
]


def passo_final() -> int:
    """Índice do passo que recebe a chave. Único com o campo de entrada."""
    return next(i for i, p in enumerate(PASSOS) if p.get("campo_chave"))


def _garantir_estilos(janela: tk.Misc) -> None:
    """
    Define os estilos usados aqui, caso ainda não existam.

    A janela principal já os define, mas o assistente também precisa funcionar
    quando aberto isoladamente — em testes, por exemplo. Um nome de estilo
    inexistente faria o ttk levantar TclError na criação do widget.
    """
    estilo = ttk.Style(janela)
    estilo.configure("Erro.TLabel", foreground="#b00020")
    estilo.configure("Ok.TLabel", foreground="#1b7f3b")
    estilo.configure("Discreto.TLabel", foreground="#666666")
    estilo.configure("Titulo.TLabel", font=("TkDefaultFont", 12, "bold"))


class Assistente(tk.Toplevel):
    """Janela modal do assistente de primeira execução."""

    def __init__(self, pai: tk.Misc) -> None:
        super().__init__(pai)
        _garantir_estilos(self)
        self.title(TITULO)
        self.resizable(False, False)
        self.chave_salva: str | None = None

        self._indice = 0
        self._fila: queue.Queue = queue.Queue()
        self._verificada = False

        self._montar()
        self._mostrar_passo()

        self.transient(pai)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._pular)
        self._centralizar(pai)
        self.after(120, self._drenar_fila)

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _montar(self) -> None:
        moldura = ttk.Frame(self, padding=18)
        moldura.pack(fill="both", expand=True)

        self.rotulo_etapa = ttk.Label(moldura, text="", style="Discreto.TLabel")
        self.rotulo_etapa.pack(anchor="w")

        self.rotulo_titulo = ttk.Label(moldura, text="", style="Titulo.TLabel")
        self.rotulo_titulo.pack(anchor="w", pady=(2, 10))

        self.rotulo_texto = ttk.Label(
            moldura, text="", wraplength=560, justify="left"
        )
        self.rotulo_texto.pack(anchor="w", fill="x")

        self.area_links = ttk.Frame(moldura)
        self.area_links.pack(anchor="w", fill="x", pady=(14, 0))

        # --- Campo da chave, só no último passo ---
        self.area_chave = ttk.Frame(moldura)
        self.var_chave = tk.StringVar()
        entrada = ttk.Entry(self.area_chave, textvariable=self.var_chave, width=52)
        entrada.grid(row=0, column=0, sticky="ew")
        self.botao_verificar = ttk.Button(
            self.area_chave, text="Verificar", command=self._verificar
        )
        self.botao_verificar.grid(row=0, column=1, padx=(8, 0))
        self.rotulo_teste = ttk.Label(self.area_chave, text="", style="Discreto.TLabel")
        self.rotulo_teste.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # --- Confirmação de etapa concluída ---
        self.var_confirmado = tk.BooleanVar(value=False)
        self.caixa_confirmacao = ttk.Checkbutton(
            moldura, text="", variable=self.var_confirmado, command=self._atualizar_botoes
        )

        # --- Navegação ---
        navegacao = ttk.Frame(moldura)
        navegacao.pack(fill="x", pady=(20, 0))

        ttk.Button(navegacao, text="Pular", command=self._pular).pack(side="left")
        self.botao_avancar = ttk.Button(navegacao, text="Avançar", command=self._avancar)
        self.botao_avancar.pack(side="right")
        self.botao_voltar = ttk.Button(navegacao, text="Voltar", command=self._voltar)
        self.botao_voltar.pack(side="right", padx=(0, 8))

    def _centralizar(self, pai: tk.Misc) -> None:
        self.update_idletasks()
        x = pai.winfo_rootx() + (pai.winfo_width() - self.winfo_width()) // 2
        y = pai.winfo_rooty() + (pai.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # ------------------------------------------------------------------
    # Navegação
    # ------------------------------------------------------------------

    def _mostrar_passo(self) -> None:
        passo = PASSOS[self._indice]

        self.rotulo_etapa.configure(text=f"Etapa {self._indice + 1} de {len(PASSOS)}")
        self.rotulo_titulo.configure(text=passo["titulo"])
        self.rotulo_texto.configure(text=passo["texto"])

        # --- Links da etapa ---
        for filho in self.area_links.winfo_children():
            filho.destroy()
        for rotulo, url in passo["links"]:
            ttk.Button(
                self.area_links, text=rotulo,
                command=lambda u=url: webbrowser.open(u),
            ).pack(anchor="w", pady=2)

        # --- Campo da chave ---
        if passo.get("campo_chave"):
            self.area_chave.pack(anchor="w", fill="x", pady=(14, 0))
        else:
            self.area_chave.pack_forget()

        # --- Confirmação ---
        if passo["confirmacao"]:
            self.caixa_confirmacao.configure(text=passo["confirmacao"])
            self.caixa_confirmacao.pack(anchor="w", pady=(14, 0))
            self.var_confirmado.set(False)
        else:
            self.caixa_confirmacao.pack_forget()
            self.var_confirmado.set(True)

        self._atualizar_botoes()

    def _atualizar_botoes(self) -> None:
        ultimo = self._indice == len(PASSOS) - 1

        self.botao_voltar.configure(state="normal" if self._indice > 0 else "disabled")
        self.botao_avancar.configure(
            text="Concluir" if ultimo else "Avançar",
            state="normal" if self.var_confirmado.get() else "disabled",
        )

    def _voltar(self) -> None:
        if self._indice > 0:
            self._indice -= 1
            self._mostrar_passo()

    def _avancar(self) -> None:
        if self._indice < len(PASSOS) - 1:
            self._indice += 1
            self._mostrar_passo()
            return
        self._concluir()

    def _pular(self) -> None:
        self.grab_release()
        self.destroy()

    # ------------------------------------------------------------------
    # Verificação e gravação
    # ------------------------------------------------------------------

    def _verificar(self) -> None:
        chave = self.var_chave.get().strip()
        if not chave:
            messagebox.showwarning(TITULO, "Cole a chave antes de verificar.", parent=self)
            return

        if not credenciais.formato_plausivel(chave):
            self.rotulo_teste.configure(
                text=(
                    "Atenção: o formato não parece o de uma chave do Google "
                    "(AIza… com 39 caracteres). Verificando mesmo assim..."
                ),
                style="Erro.TLabel",
            )
        else:
            self.rotulo_teste.configure(text="Verificando...", style="Discreto.TLabel")

        self.botao_verificar.configure(state="disabled")
        threading.Thread(
            target=lambda: self._fila.put(("teste", testar_chave(chave))),
            daemon=True,
        ).start()

    def _drenar_fila(self) -> None:
        """Recebe o resultado da verificação na thread da interface."""
        try:
            while True:
                evento, dado = self._fila.get_nowait()
                if evento == "teste":
                    self._mostrar_resultado_teste(*dado)
        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.after(120, self._drenar_fila)

    def _mostrar_resultado_teste(self, ok: bool, mensagem: str) -> None:
        self.botao_verificar.configure(state="normal")
        self._verificada = ok
        self.rotulo_teste.configure(
            text=("✔ " if ok else "✘ ") + mensagem,
            style="Ok.TLabel" if ok else "Erro.TLabel",
            wraplength=520,
        )

    def _concluir(self) -> None:
        chave = self.var_chave.get().strip()
        if not chave:
            messagebox.showwarning(TITULO, "Cole a chave para concluir.", parent=self)
            return

        if not self._verificada and not messagebox.askyesno(
            TITULO,
            "A chave ainda não foi verificada com sucesso.\n\n"
            "Salvar assim mesmo? Você pode verificar depois pela janela principal.",
            parent=self,
        ):
            return

        try:
            credenciais.salvar_chave(chave)
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                TITULO, f"Não foi possível salvar a chave:\n\n{exc}", parent=self
            )
            return

        self.chave_salva = chave
        self.grab_release()
        self.destroy()


def executar(pai: tk.Misc) -> str | None:
    """
    Abre o assistente e espera o usuário terminar.

    Returns:
        A chave salva, ou None se o assistente foi pulado ou fechado.
    """
    assistente = Assistente(pai)
    pai.wait_window(assistente)
    return assistente.chave_salva
