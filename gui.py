"""
gui.py — Interface gráfica do buscador de provedores.

Feita em tkinter, da biblioteca padrão: não acrescenta nenhuma dependência e
empacota num executável único sem bibliotecas nativas extras.

    python gui.py

────────────────────────────────────────────────────────────────────────
Threads

A busca leva de segundos a minutos e não pode rodar na thread da interface,
sob pena de a janela congelar. Ela roda numa thread de trabalho, que NUNCA
toca em widgets — o tkinter não é seguro para uso concorrente. A comunicação
é por fila: a thread publica eventos, e a interface os consome no seu próprio
laço, via after(). Toda alteração de tela acontece na thread principal.
────────────────────────────────────────────────────────────────────────

Atribuição: as políticas do Google exigem crédito visível ao exibir dados de
Places fora de um mapa do Google. O rodapé da janela cumpre esse requisito e
não deve ser removido.
"""

import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import credenciais
from analise_termos import formatar_relatorio_multi
from config import DIRETORIO_SAIDA, MAX_PAGINAS, RAIO_PADRAO, TERMOS_DE_BUSCA
from service import calibrar_termos, executar_busca

TITULO = "Buscador de Provedores de Internet"
CREDITO = "Dados de estabelecimentos: Google Maps"

# Colunas exibidas na tabela. As demais vão para o arquivo exportado — mostrar
# tudo em tela deixaria as colunas estreitas demais para serem úteis.
COLUNAS_TABELA = [
    ("nome", "Nome", 240),
    ("distancia_km", "Dist. (km)", 80),
    ("telefone", "Telefone", 130),
    ("site", "Site", 240),
    ("avaliacao", "Nota", 60),
    ("status", "Status", 130),
]


# ---------------------------------------------------------------------------
# Helpers sem dependência de tkinter (testáveis isoladamente)
# ---------------------------------------------------------------------------

def comando_abrir_pasta(caminho: str) -> list[str]:
    """
    Comando do sistema para abrir uma pasta no gerenciador de arquivos.

    Args:
        caminho: Pasta a abrir.

    Returns:
        Lista de argumentos pronta para subprocess, sem shell — o caminho vem
        de um seletor de arquivos, mas passá-lo por shell abriria espaço para
        interpretação de metacaracteres sem necessidade nenhuma.
    """
    sistema = platform.system()
    if sistema == "Windows":
        return ["explorer", caminho]
    if sistema == "Darwin":
        return ["open", caminho]
    return ["xdg-open", caminho]


def valor_para_ordenacao(valor: str):
    """
    Converte o texto de uma célula para ordenar a tabela.

    Números ordenam por grandeza, e não alfabeticamente — sem isso, "10" viria
    antes de "9". Células vazias vão para o fim, já que representam ausência
    de dado e não um valor pequeno.
    """
    texto = (valor or "").strip()
    if not texto:
        return (2, 0.0, "")
    try:
        return (0, float(texto.replace(",", ".")), "")
    except ValueError:
        return (1, 0.0, texto.lower())


def texto_do_erro(exc: BaseException) -> str:
    """Mensagem de falha inesperada, legível para quem não programa."""
    return (
        f"Ocorreu um erro inesperado ({type(exc).__name__}).\n\n{exc}\n\n"
        "Se o problema persistir, rode pelo terminal com -v para ver os detalhes."
    )


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

class Aplicacao(tk.Tk):
    """Janela principal."""

    def __init__(self) -> None:
        super().__init__()
        self.title(TITULO)
        self.minsize(940, 620)
        self.geometry("1060x720")

        # Comunicação entre a thread de trabalho e a interface
        self._fila: queue.Queue = queue.Queue()
        self._trabalho: threading.Thread | None = None
        self._cancelamento = threading.Event()

        self._ultimos_arquivos: list[str] = []
        self._ultima_calibracao: dict | None = None

        self._montar_estilo()
        self._montar_chave()
        self._montar_abas()
        self._montar_rodape()

        self._carregar_chave_existente()

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.after(120, self._drenar_fila)

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------

    def _montar_estilo(self) -> None:
        estilo = ttk.Style(self)
        if "clam" in estilo.theme_names():
            estilo.theme_use("clam")
        estilo.configure("Erro.TLabel", foreground="#b00020")
        estilo.configure("Ok.TLabel", foreground="#1b7f3b")
        estilo.configure("Discreto.TLabel", foreground="#666666")
        estilo.configure("Titulo.TLabel", font=("TkDefaultFont", 11, "bold"))

    def _montar_chave(self) -> None:
        quadro = ttk.LabelFrame(self, text="Chave de API do Google Maps", padding=10)
        quadro.pack(fill="x", padx=12, pady=(12, 6))
        quadro.columnconfigure(1, weight=1)

        ttk.Label(quadro, text="Chave:").grid(row=0, column=0, sticky="w")

        self.var_chave = tk.StringVar()
        self.entrada_chave = ttk.Entry(quadro, textvariable=self.var_chave, show="•")
        self.entrada_chave.grid(row=0, column=1, sticky="ew", padx=8)

        self.var_mostrar_chave = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            quadro, text="Mostrar", variable=self.var_mostrar_chave,
            command=self._alternar_visibilidade_chave,
        ).grid(row=0, column=2, padx=4)

        ttk.Button(quadro, text="Salvar", command=self._salvar_chave).grid(row=0, column=3, padx=4)
        ttk.Button(quadro, text="Testar", command=self._testar_chave).grid(row=0, column=4)

        self.rotulo_chave = ttk.Label(quadro, text="", style="Discreto.TLabel")
        self.rotulo_chave.grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))

        ttk.Label(
            quadro,
            text=(
                "Cada pessoa deve usar a própria chave. A chave fica gravada em "
                "texto puro no seu computador — não a compartilhe."
            ),
            style="Discreto.TLabel", wraplength=980, justify="left",
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))

    def _montar_abas(self) -> None:
        self.abas = ttk.Notebook(self)
        self.abas.pack(fill="both", expand=True, padx=12, pady=6)
        self._montar_aba_busca()
        self._montar_aba_calibracao()

    # ---- Aba: busca ---------------------------------------------------

    def _montar_aba_busca(self) -> None:
        aba = ttk.Frame(self.abas, padding=12)
        self.abas.add(aba, text="  Buscar provedores  ")
        aba.columnconfigure(0, weight=1)
        aba.rowconfigure(3, weight=1)

        # --- Parâmetros ---
        params = ttk.LabelFrame(aba, text="Onde buscar", padding=10)
        params.grid(row=0, column=0, sticky="ew")
        params.columnconfigure(1, weight=1)

        self.var_modo = tk.StringVar(value="endereco")
        ttk.Radiobutton(
            params, text="Endereço", value="endereco", variable=self.var_modo,
            command=self._alternar_modo_local,
        ).grid(row=0, column=0, sticky="w")

        self.var_endereco = tk.StringVar()
        self.entrada_endereco = ttk.Entry(params, textvariable=self.var_endereco)
        self.entrada_endereco.grid(row=0, column=1, columnspan=3, sticky="ew", padx=8)
        self.entrada_endereco.bind("<Return>", lambda _e: self._iniciar_busca())

        ttk.Radiobutton(
            params, text="Coordenadas", value="coordenadas", variable=self.var_modo,
            command=self._alternar_modo_local,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.var_lat = tk.StringVar()
        self.var_lng = tk.StringVar()
        self.entrada_lat = ttk.Entry(params, textvariable=self.var_lat, width=16)
        self.entrada_lng = ttk.Entry(params, textvariable=self.var_lng, width=16)
        ttk.Label(params, text="Latitude").grid(row=1, column=1, sticky="e", pady=(6, 0))
        self.entrada_lat.grid(row=1, column=2, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(params, text="Longitude").grid(row=1, column=3, sticky="e", pady=(6, 0))
        self.entrada_lng.grid(row=1, column=4, sticky="w", padx=6, pady=(6, 0))

        # --- Opções ---
        opcoes = ttk.LabelFrame(aba, text="Opções", padding=10)
        opcoes.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        opcoes.columnconfigure(5, weight=1)

        ttk.Label(opcoes, text="Raio (metros):").grid(row=0, column=0, sticky="w")
        self.var_raio = tk.StringVar(value=str(RAIO_PADRAO))
        ttk.Spinbox(
            opcoes, from_=500, to=50_000, increment=500,
            textvariable=self.var_raio, width=10,
        ).grid(row=0, column=1, sticky="w", padx=(6, 20))

        ttk.Label(opcoes, text="Formato:").grid(row=0, column=2, sticky="w")
        self.var_formato = tk.StringVar(value="csv")
        ttk.Combobox(
            opcoes, textvariable=self.var_formato, width=10, state="readonly",
            values=["csv", "excel", "ambos"],
        ).grid(row=0, column=3, sticky="w", padx=(6, 20))

        ttk.Label(opcoes, text="Salvar em:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.var_saida = tk.StringVar(value=str(Path(DIRETORIO_SAIDA).resolve()))
        ttk.Entry(opcoes, textvariable=self.var_saida).grid(
            row=1, column=1, columnspan=5, sticky="ew", padx=6, pady=(8, 0)
        )
        ttk.Button(opcoes, text="Procurar...", command=self._escolher_pasta).grid(
            row=1, column=6, pady=(8, 0)
        )

        # --- Ações e progresso ---
        acoes = ttk.Frame(aba)
        acoes.grid(row=2, column=0, sticky="ew", pady=10)
        acoes.columnconfigure(2, weight=1)

        self.botao_buscar = ttk.Button(acoes, text="Buscar", command=self._iniciar_busca)
        self.botao_buscar.grid(row=0, column=0)

        self.botao_cancelar = ttk.Button(
            acoes, text="Cancelar", command=self._cancelar, state="disabled"
        )
        self.botao_cancelar.grid(row=0, column=1, padx=6)

        self.progresso = ttk.Progressbar(acoes, mode="determinate", maximum=len(TERMOS_DE_BUSCA))
        self.progresso.grid(row=0, column=2, sticky="ew", padx=12)

        self.rotulo_progresso = ttk.Label(acoes, text="Pronto.", style="Discreto.TLabel")
        self.rotulo_progresso.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # --- Resultados ---
        resultados = ttk.LabelFrame(aba, text="Resultados", padding=6)
        resultados.grid(row=3, column=0, sticky="nsew")
        resultados.columnconfigure(0, weight=1)
        resultados.rowconfigure(0, weight=1)

        self.tabela = ttk.Treeview(
            resultados, columns=[c[0] for c in COLUNAS_TABELA], show="headings", selectmode="browse"
        )
        for chave, titulo, largura in COLUNAS_TABELA:
            self.tabela.heading(
                chave, text=titulo, command=lambda c=chave: self._ordenar_tabela(c)
            )
            self.tabela.column(chave, width=largura, anchor="w")
        self.tabela.grid(row=0, column=0, sticky="nsew")
        self.tabela.bind("<Double-1>", self._abrir_site_selecionado)

        barra = ttk.Scrollbar(resultados, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=barra.set)
        barra.grid(row=0, column=1, sticky="ns")

        rodape = ttk.Frame(resultados)
        rodape.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.rotulo_total = ttk.Label(rodape, text="", style="Discreto.TLabel")
        self.rotulo_total.pack(side="left")
        ttk.Label(
            rodape, text="Duplo clique numa linha abre o site da empresa.",
            style="Discreto.TLabel",
        ).pack(side="left", padx=16)
        self.botao_abrir_pasta = ttk.Button(
            rodape, text="Abrir pasta dos arquivos", command=self._abrir_pasta_saida,
            state="disabled",
        )
        self.botao_abrir_pasta.pack(side="right")

        self._alternar_modo_local()

    # ---- Aba: calibração ----------------------------------------------

    def _montar_aba_calibracao(self) -> None:
        aba = ttk.Frame(self.abas, padding=12)
        self.abas.add(aba, text="  Calibrar termos  ")
        aba.columnconfigure(1, weight=1)
        aba.rowconfigure(2, weight=1)

        ttk.Label(
            aba,
            text=(
                "Mede quais termos de busca valem a pena. A sobreposição varia por "
                "região — meça 3 ou mais cidades representativas da sua área."
            ),
            style="Discreto.TLabel", wraplength=980, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        # --- Lista de cidades ---
        entrada = ttk.Frame(aba)
        entrada.grid(row=1, column=0, columnspan=3, sticky="ew")
        entrada.columnconfigure(0, weight=1)

        self.var_cidade = tk.StringVar()
        campo = ttk.Entry(entrada, textvariable=self.var_cidade)
        campo.grid(row=0, column=0, sticky="ew")
        campo.bind("<Return>", lambda _e: self._adicionar_cidade())

        ttk.Button(entrada, text="Adicionar", command=self._adicionar_cidade).grid(
            row=0, column=1, padx=6
        )
        ttk.Button(entrada, text="Remover", command=self._remover_cidade).grid(row=0, column=2)

        ttk.Label(entrada, text="Raio (m):").grid(row=0, column=3, padx=(20, 4))
        self.var_raio_calib = tk.StringVar(value=str(RAIO_PADRAO))
        ttk.Spinbox(
            entrada, from_=500, to=50_000, increment=500,
            textvariable=self.var_raio_calib, width=10,
        ).grid(row=0, column=4)

        # --- Cidades e relatório ---
        painel = ttk.Frame(aba)
        painel.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=8)
        painel.columnconfigure(1, weight=1)
        painel.rowconfigure(0, weight=1)

        self.lista_cidades = tk.Listbox(painel, height=8, exportselection=False)
        self.lista_cidades.grid(row=0, column=0, sticky="nsw", padx=(0, 8))

        self.saida_calibracao = tk.Text(
            painel, wrap="none", height=18, font=("TkFixedFont", 9), state="disabled"
        )
        self.saida_calibracao.grid(row=0, column=1, sticky="nsew")

        barra = ttk.Scrollbar(painel, orient="vertical", command=self.saida_calibracao.yview)
        self.saida_calibracao.configure(yscrollcommand=barra.set)
        barra.grid(row=0, column=2, sticky="ns")

        # --- Ações ---
        acoes = ttk.Frame(aba)
        acoes.grid(row=3, column=0, columnspan=3, sticky="ew")

        self.botao_calibrar = ttk.Button(acoes, text="Calibrar", command=self._iniciar_calibracao)
        self.botao_calibrar.pack(side="left")

        self.rotulo_custo = ttk.Label(acoes, text="", style="Discreto.TLabel")
        self.rotulo_custo.pack(side="left", padx=12)

        self.botao_copiar = ttk.Button(
            acoes, text="Copiar TERMOS_DE_BUSCA", command=self._copiar_termos, state="disabled"
        )
        self.botao_copiar.pack(side="right")

        self._atualizar_custo_calibracao()

    def _montar_rodape(self) -> None:
        rodape = ttk.Frame(self, padding=(12, 4))
        rodape.pack(fill="x")
        # Crédito exigido pelas políticas do Google ao exibir dados de Places
        # fora de um mapa do Google. Não remover.
        ttk.Label(rodape, text=CREDITO, style="Discreto.TLabel").pack(side="left")
        self.rotulo_status = ttk.Label(rodape, text="", style="Discreto.TLabel")
        self.rotulo_status.pack(side="right")

    # ------------------------------------------------------------------
    # Chave de API
    # ------------------------------------------------------------------

    def _carregar_chave_existente(self) -> None:
        chave, origem = credenciais.carregar_chave()
        if chave:
            self.var_chave.set(chave)
            self.rotulo_chave.configure(
                text=f"Chave carregada de: {origem}  ({credenciais.mascarar(chave)})",
                style="Ok.TLabel",
            )
        else:
            self.rotulo_chave.configure(
                text=(
                    "Nenhuma chave encontrada. Cole a sua chave acima e clique em Salvar. "
                    "Veja o README para criar uma no Google Cloud Console."
                ),
                style="Erro.TLabel",
            )

    def _alternar_visibilidade_chave(self) -> None:
        self.entrada_chave.configure(show="" if self.var_mostrar_chave.get() else "•")

    def _salvar_chave(self) -> None:
        chave = self.var_chave.get().strip()
        if not chave:
            messagebox.showwarning(TITULO, "Informe a chave antes de salvar.")
            return

        if not credenciais.formato_plausivel(chave):
            seguir = messagebox.askyesno(
                TITULO,
                "Esta chave não tem o formato usual do Google Maps "
                "(começa com 'AIza' e tem 39 caracteres).\n\n"
                "Pode ser um erro de digitação ou uma colagem incompleta.\n\n"
                "Salvar mesmo assim?",
            )
            if not seguir:
                return

        try:
            destino = credenciais.salvar_chave(chave)
        except (OSError, ValueError) as exc:
            messagebox.showerror(TITULO, f"Não foi possível salvar a chave:\n\n{exc}")
            return

        self.rotulo_chave.configure(
            text=f"Chave salva em: {destino}  ({credenciais.mascarar(chave)})",
            style="Ok.TLabel",
        )

    def _testar_chave(self) -> None:
        """Geocodifica um endereço conhecido — 1 requisição, dentro da cota gratuita."""
        chave = self.var_chave.get().strip()
        if not chave:
            messagebox.showwarning(TITULO, "Informe a chave antes de testar.")
            return

        self.rotulo_chave.configure(text="Testando a chave...", style="Discreto.TLabel")
        self.update_idletasks()

        def tarefa():
            from buscador import BuscadorProvedores
            try:
                with BuscadorProvedores(api_key=chave) as buscador:
                    buscador.geocodificar("Florianópolis, SC")
                self._fila.put(("chave_ok", None))
            except Exception as exc:                      # noqa: BLE001 — vai para a tela
                self._fila.put(("chave_erro", str(exc)))

        threading.Thread(target=tarefa, daemon=True).start()

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------

    def _alternar_modo_local(self) -> None:
        por_endereco = self.var_modo.get() == "endereco"
        self.entrada_endereco.configure(state="normal" if por_endereco else "disabled")
        for campo in (self.entrada_lat, self.entrada_lng):
            campo.configure(state="disabled" if por_endereco else "normal")

    def _escolher_pasta(self) -> None:
        escolhida = filedialog.askdirectory(initialdir=self.var_saida.get() or ".")
        if escolhida:
            self.var_saida.set(escolhida)

    def _ler_parametros_busca(self) -> dict | None:
        """Valida os campos e monta os argumentos, ou avisa e devolve None."""
        chave = self.var_chave.get().strip()
        if not chave:
            messagebox.showwarning(TITULO, "Informe a chave de API antes de buscar.")
            return None

        try:
            raio = int(self.var_raio.get())
            if raio <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(TITULO, "O raio deve ser um número inteiro de metros.")
            return None

        endereco = coordenadas = None
        if self.var_modo.get() == "endereco":
            endereco = self.var_endereco.get().strip()
            if not endereco:
                messagebox.showwarning(TITULO, "Informe o endereço a pesquisar.")
                return None
        else:
            try:
                coordenadas = (
                    float(self.var_lat.get().replace(",", ".")),
                    float(self.var_lng.get().replace(",", ".")),
                )
            except ValueError:
                messagebox.showwarning(
                    TITULO, "Latitude e longitude devem ser números decimais."
                )
                return None

        return {
            "api_key": chave,
            "endereco": endereco,
            "coordenadas": coordenadas,
            "raio": raio,
            "formato": self.var_formato.get(),
            "diretorio": self.var_saida.get() or DIRETORIO_SAIDA,
        }

    def _iniciar_busca(self) -> None:
        if self._ocupado():
            return

        argumentos = self._ler_parametros_busca()
        if argumentos is None:
            return

        self.tabela.delete(*self.tabela.get_children())
        self.rotulo_total.configure(text="")
        self.botao_abrir_pasta.configure(state="disabled")
        self.progresso.configure(value=0, maximum=len(TERMOS_DE_BUSCA))
        self._definir_ocupado(True, "Buscando...")
        self._cancelamento.clear()

        def tarefa():
            try:
                resultado = executar_busca(
                    **argumentos,
                    callback_progresso=lambda info: self._fila.put(("progresso", info)),
                    deve_cancelar=self._cancelamento.is_set,
                )
                self._fila.put(("resultado", resultado))
            except Exception as exc:                      # noqa: BLE001 — vai para a tela
                self._fila.put(("falha", texto_do_erro(exc)))

        self._trabalho = threading.Thread(target=tarefa, daemon=True)
        self._trabalho.start()

    def _cancelar(self) -> None:
        self._cancelamento.set()
        self.rotulo_progresso.configure(text="Cancelando ao fim da etapa atual...")
        self.botao_cancelar.configure(state="disabled")

    def _preencher_tabela(self, provedores: list[dict]) -> None:
        for provedor in provedores:
            self.tabela.insert(
                "", "end",
                values=[provedor.get(chave, "") for chave, _, _ in COLUNAS_TABELA],
            )

    def _ordenar_tabela(self, coluna: str) -> None:
        itens = [(self.tabela.set(i, coluna), i) for i in self.tabela.get_children("")]
        invertido = getattr(self, "_ordem_invertida", {}).get(coluna, False)
        itens.sort(key=lambda par: valor_para_ordenacao(par[0]), reverse=invertido)

        for posicao, (_, item) in enumerate(itens):
            self.tabela.move(item, "", posicao)

        if not hasattr(self, "_ordem_invertida"):
            self._ordem_invertida = {}
        self._ordem_invertida[coluna] = not invertido

    def _abrir_site_selecionado(self, _evento=None) -> None:
        selecao = self.tabela.selection()
        if not selecao:
            return
        site = self.tabela.set(selecao[0], "site")
        if site.startswith(("http://", "https://")):
            webbrowser.open(site)

    def _abrir_pasta_saida(self) -> None:
        pasta = self.var_saida.get()
        if not os.path.isdir(pasta):
            messagebox.showinfo(TITULO, "A pasta ainda não existe.")
            return
        try:
            subprocess.Popen(comando_abrir_pasta(pasta))
        except OSError as exc:
            messagebox.showerror(TITULO, f"Não foi possível abrir a pasta:\n\n{exc}")

    # ------------------------------------------------------------------
    # Calibração
    # ------------------------------------------------------------------

    def _cidades(self) -> list[str]:
        return list(self.lista_cidades.get(0, "end"))

    def _adicionar_cidade(self) -> None:
        cidade = self.var_cidade.get().strip()
        if not cidade:
            return
        if cidade in self._cidades():
            messagebox.showinfo(TITULO, "Essa cidade já está na lista.")
            return
        self.lista_cidades.insert("end", cidade)
        self.var_cidade.set("")
        self._atualizar_custo_calibracao()

    def _remover_cidade(self) -> None:
        for indice in reversed(self.lista_cidades.curselection()):
            self.lista_cidades.delete(indice)
        self._atualizar_custo_calibracao()

    def _atualizar_custo_calibracao(self) -> None:
        total = len(self._cidades())
        if not total:
            self.rotulo_custo.configure(text="Adicione as cidades a medir.")
            return
        buscas = total * len(TERMOS_DE_BUSCA) * MAX_PAGINAS
        self.rotulo_custo.configure(
            text=f"{total} cidade(s) · custo máximo: {total} geocodificações + {buscas} buscas"
        )

    def _iniciar_calibracao(self) -> None:
        if self._ocupado():
            return

        chave = self.var_chave.get().strip()
        cidades = self._cidades()

        if not chave:
            messagebox.showwarning(TITULO, "Informe a chave de API antes de calibrar.")
            return
        if not cidades:
            messagebox.showwarning(TITULO, "Adicione ao menos uma cidade.")
            return
        if len(cidades) < 3 and not messagebox.askyesno(
            TITULO,
            f"Você adicionou {len(cidades)} cidade(s).\n\n"
            "A sobreposição entre os termos varia bastante por região. Com poucas "
            "cidades, a recomendação pode não valer para a sua área toda.\n\n"
            "Continuar mesmo assim?",
        ):
            return

        try:
            raio = int(self.var_raio_calib.get())
        except ValueError:
            messagebox.showwarning(TITULO, "O raio deve ser um número inteiro de metros.")
            return

        self._escrever_calibracao("Medindo...\n")
        self.botao_copiar.configure(state="disabled")
        self._definir_ocupado(True, "Calibrando...")
        self.progresso.configure(value=0, maximum=len(cidades))

        def tarefa():
            try:
                resultado = calibrar_termos(
                    api_key=chave, localizacoes=cidades, raio=raio,
                    callback_cidade=lambda info: self._fila.put(("cidade", info)),
                )
                self._fila.put(("calibracao", resultado))
            except Exception as exc:                      # noqa: BLE001 — vai para a tela
                self._fila.put(("falha", texto_do_erro(exc)))

        self._trabalho = threading.Thread(target=tarefa, daemon=True)
        self._trabalho.start()

    def _escrever_calibracao(self, texto: str) -> None:
        self.saida_calibracao.configure(state="normal")
        self.saida_calibracao.delete("1.0", "end")
        self.saida_calibracao.insert("1.0", texto)
        self.saida_calibracao.configure(state="disabled")

    def _copiar_termos(self) -> None:
        if not self._ultima_calibracao:
            return
        linhas = ["TERMOS_DE_BUSCA: list[str] = ["]
        linhas += [f'    "{termo}",' for termo in self._ultima_calibracao["essenciais"]]
        linhas.append("]")

        self.clipboard_clear()
        self.clipboard_append("\n".join(linhas))
        self.rotulo_status.configure(text="Bloco copiado — cole em config.py")

    # ------------------------------------------------------------------
    # Estado e fila de eventos
    # ------------------------------------------------------------------

    def _ocupado(self) -> bool:
        if self._trabalho and self._trabalho.is_alive():
            messagebox.showinfo(TITULO, "Já existe uma operação em andamento.")
            return True
        return False

    def _definir_ocupado(self, ocupado: bool, mensagem: str = "") -> None:
        estado = "disabled" if ocupado else "normal"
        self.botao_buscar.configure(state=estado)
        self.botao_calibrar.configure(state=estado)
        self.botao_cancelar.configure(state="normal" if ocupado else "disabled")
        if mensagem:
            self.rotulo_progresso.configure(text=mensagem)

    def _drenar_fila(self) -> None:
        """
        Consome os eventos publicados pela thread de trabalho.

        Só aqui a interface é alterada: este método roda sempre na thread
        principal, agendado por after().
        """
        try:
            while True:
                evento, dado = self._fila.get_nowait()
                self._tratar_evento(evento, dado)
        except queue.Empty:
            pass
        finally:
            self.after(120, self._drenar_fila)

    def _tratar_evento(self, evento: str, dado) -> None:
        if evento == "progresso":
            self._evento_progresso(dado)
        elif evento == "cidade":
            self._evento_cidade(dado)
        elif evento == "resultado":
            self._evento_resultado(dado)
        elif evento == "calibracao":
            self._evento_calibracao(dado)
        elif evento == "falha":
            self._definir_ocupado(False, "Falhou.")
            messagebox.showerror(TITULO, dado)
        elif evento == "chave_ok":
            self.rotulo_chave.configure(
                text="Chave válida — Geocoding API respondeu corretamente.", style="Ok.TLabel"
            )
        elif evento == "chave_erro":
            self.rotulo_chave.configure(text=f"Chave recusada: {dado}", style="Erro.TLabel")

    def _evento_progresso(self, info: dict) -> None:
        if info.get("erro"):
            self.rotulo_progresso.configure(text=info["mensagem"], style="Erro.TLabel")
            return

        self.rotulo_progresso.configure(text=info["mensagem"], style="Discreto.TLabel")
        if info["novos_provedores"] is not None:
            self.progresso.configure(value=info["etapa"])
            self.rotulo_total.configure(text=f"{info['total_acumulado']} encontrado(s)...")

    def _evento_cidade(self, info: dict) -> None:
        if info["etapa"] == "iniciando":
            self.rotulo_progresso.configure(
                text=f"[{info['indice']}/{info['total']}] {info['cidade']}...",
                style="Discreto.TLabel",
            )
        elif info["etapa"] == "concluida":
            self.progresso.configure(value=info["indice"])
        else:
            self.rotulo_progresso.configure(
                text=f"{info['cidade']}: {info['erro']}", style="Erro.TLabel"
            )

    def _evento_resultado(self, resultado: dict) -> None:
        self._definir_ocupado(False)

        if resultado["erro"] and not resultado["provedores"]:
            self.rotulo_progresso.configure(text="Nada encontrado.", style="Erro.TLabel")
            messagebox.showerror(TITULO, resultado["erro"])
            return

        self._preencher_tabela(resultado["provedores"])
        self._ultimos_arquivos = resultado["arquivos"]

        total = resultado["total"]
        sufixo = " (busca cancelada — resultado parcial)" if resultado.get("cancelado") else ""
        self.rotulo_total.configure(text=f"{total} provedor(es){sufixo}")
        self.progresso.configure(value=self.progresso["maximum"])

        if total == 0:
            self.rotulo_progresso.configure(
                text="Nenhum provedor nesta área. Tente aumentar o raio.",
                style="Discreto.TLabel",
            )
            return

        self.rotulo_progresso.configure(text="Concluído.", style="Ok.TLabel")
        if resultado["arquivos"]:
            self.botao_abrir_pasta.configure(state="normal")
            self.rotulo_status.configure(text=f"Salvo: {Path(resultado['arquivos'][0]).name}")
        if resultado["erro"]:
            messagebox.showwarning(TITULO, resultado["erro"])

    def _evento_calibracao(self, resultado: dict) -> None:
        self._definir_ocupado(False, "Concluído.")

        if resultado["erro"]:
            self._escrever_calibracao(resultado["erro"])
            messagebox.showerror(TITULO, resultado["erro"])
            return

        self._ultima_calibracao = resultado["consolidacao"]
        self._escrever_calibracao(
            formatar_relatorio_multi(
                resultado["consolidacao"], resultado["cidades_com_erro"]
            )
        )
        self.botao_copiar.configure(state="normal")

    # ------------------------------------------------------------------
    # Encerramento
    # ------------------------------------------------------------------

    def _ao_fechar(self) -> None:
        if self._trabalho and self._trabalho.is_alive():
            if not messagebox.askyesno(
                TITULO, "Há uma operação em andamento. Fechar mesmo assim?"
            ):
                return
            self._cancelamento.set()
        self.destroy()


def main() -> int:
    Aplicacao().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
