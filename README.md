# Buscador de Provedores de Internet

Script Python para encontrar provedores de internet próximos a uma localização usando a **Google Places API**. Ideal para analistas de viabilidade que precisam mapear a concorrência ou parceiros em uma região.

---

## Funcionalidades

- Aceita endereço textual ou coordenadas geográficas como entrada
- Busca provedores num raio configurável (padrão: 5 km)
- Extrai: nome, endereço, telefone, site e avaliação de cada empresa
- Deduplica resultados automaticamente por `place_id`
- **Cache local de Place Details** — evita chamadas repetidas à API para o mesmo estabelecimento, reduzindo custo em buscas consecutivas na mesma região
- Exporta para **CSV** (padrão) ou **Excel (.xlsx)** com formatação profissional
- **Camada de serviço** (`service.py`) sem dependência de I/O, pronta para integração com Flask, FastAPI ou GUI
- Interface de linha de comando completa ou modo interativo
- **Chave de API nunca exposta em logs** — filtro de logging automático mascara a chave em qualquer saída de debug
- Tratamento claro de erros (endereço não encontrado, chave inválida, falha de rede)

---

## Pré-requisitos

| Requisito | Versão mínima |
|---|---|
| Python | 3.10 |
| Conta Google Cloud | — |
| Chave de API Google Maps | — |

---

## Instalação

### 1. Clone ou baixe o projeto

```bash
git clone <url-do-repositorio>
cd buscador_provedores
```

### 2. Crie e ative um ambiente virtual (recomendado)

```bash
# Criar ambiente
python3 -m venv .venv

# Ativar no Linux / macOS
source .venv/bin/activate

# Ativar no Windows (CMD)
.venv\Scripts\activate.bat

# Ativar no Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

### 3. Instale as dependências

Para uso com **CSV apenas**:
```bash
pip install requests python-dotenv
```

Para uso com **Excel também**:
```bash
pip install -r requirements.txt
```

### 4. Configure a chave de API

Copie o arquivo de exemplo e preencha com sua chave real:

```bash
cp .env.example .env
```

Abra `.env` em um editor e substitua `sua_chave_aqui` pela sua chave:

```
GOOGLE_MAPS_API_KEY=AIzaSy...sua_chave_real...
```

> O arquivo `.env` nunca deve ser enviado ao Git. Ele já está listado no `.gitignore`.

---

## Como obter a chave de API do Google Maps

### Passo a passo

1. Acesse o **Google Cloud Console**: https://console.cloud.google.com/
2. Crie um novo projeto (ou selecione um existente)
3. No menu lateral, vá em **APIs e Serviços → Biblioteca**
4. Ative as seguintes APIs:
   - **Geocoding API** — converte endereços em coordenadas
   - **Places API** — busca de estabelecimentos e detalhes
5. Vá em **APIs e Serviços → Credenciais**
6. Clique em **+ Criar Credenciais → Chave de API**
7. Copie a chave gerada e cole no arquivo `.env`

### Restringindo a chave (recomendado)

Para evitar uso não autorizado caso a chave vaze:

- Em **Restrições de aplicativo**: selecione *Endereços IP* e adicione seu IP fixo, ou deixe sem restrição durante testes
- Em **Restrições de API**: selecione apenas *Geocoding API* e *Places API*

---

## Segurança da chave de API

| Método | Segurança | Recomendado |
|---|---|---|
| Arquivo `.env` | Alta — não aparece em histórico nem em `ps aux` | Sim |
| Variável de ambiente exportada na sessão | Média — visível com `env` | Aceitável |
| Argumento `--api-key` no terminal | Baixa — fica no `~/.bash_history` e em `ps aux` | Apenas em testes |

Independentemente do método usado, a chave **nunca aparecerá em logs ou saída de debug** — o filtro `_FiltroChaveAPI` em `buscador.py` mascara qualquer ocorrência literal da chave, substituindo-a por `***API_KEY***`.

---

## Custo estimado das APIs

O Google Maps Platform oferece **US$ 200 de crédito gratuito por mês**. A tabela abaixo mostra o custo acima desse crédito:

| API | Custo por 1.000 chamadas | Uso típico por busca |
|---|---|---|
| Geocoding API | US$ 5,00 | 1 chamada |
| Places Text Search | US$ 32,00 | 5–15 chamadas |
| Place Details | US$ 17,00 | 10–60 chamadas* |

*\* O cache local elimina chamadas repetidas ao Place Details para `place_id`s já consultados. Em buscas consecutivas na mesma cidade, a economia pode ser significativa.*

### Estimativa por execução (sem cache)

| Cenário | Chamadas aprox. | Custo estimado |
|---|---|---|
| Poucos resultados (~10 provedores) | ~17 | ~US$ 0,40 |
| Resultados médios (~30 provedores) | ~47 | ~US$ 1,00 |
| Muitos resultados (~60 provedores) | ~77 | ~US$ 1,60 |

Com o crédito de US$ 200/mês, é possível realizar **~125 buscas completas gratuitamente** (sem cache). Com o cache ativo, esse número aumenta nas buscas seguintes da mesma região.

> **Dica:** Para testar sem custos, use raios menores (`-r 2000`) ou reduza `TERMOS_DE_BUSCA` em `config.py`.

---

## Exemplos de uso

### Modo interativo (mais fácil)

```bash
python main.py
```

O script pergunta o endereço e o raio de forma guiada.

### Por endereço

```bash
# Busca no raio padrão (5 km)
python main.py -e "Florianópolis, SC"

# Busca em raio maior, exportando para Excel
python main.py -e "Curitiba, PR" -r 15000 -f excel

# Busca com endereço detalhado
python main.py -e "Rua XV de Novembro, 100, Joinville, SC" -r 3000
```

### Por coordenadas

```bash
# Latitude e longitude no formato decimal
python main.py -c -27.5954 -48.5480

# Com raio de 10 km e exportação em ambos os formatos
python main.py -c -23.5505 -46.6333 -r 10000 -f ambos
```

### Personalizando a saída

```bash
# Salva em pasta específica
python main.py -e "Blumenau, SC" -o /home/usuario/analises

# Modo verboso (mostra detalhes das chamadas para debug)
python main.py -e "Chapecó, SC" -v
```

### Passando a chave diretamente (apenas para testes)

```bash
python main.py -e "Porto Alegre, RS" --api-key AIzaSy...sua_chave...
# AVISO: a chave ficará exposta no histórico do shell. Prefira o .env.
```

---

## Usando como biblioteca (service.py)

O módulo `service.py` expõe a função `executar_busca()`, que não usa `print` nem `input`. Use-a para integrar o buscador em qualquer interface:

```python
from service import executar_busca

resultado = executar_busca(
    api_key="SUA_CHAVE",
    endereco="Joinville, SC",
    raio=8000,
    formato="csv",
)

print(resultado["total"])      # ex: 12
print(resultado["arquivos"])   # ['/caminho/provedores_20240901.csv']
print(resultado["erro"])       # None se tudo correu bem
```

### Exemplo com Flask

```python
from flask import Flask, request, jsonify
from service import executar_busca
import os

app = Flask(__name__)

@app.route("/buscar")
def buscar():
    resultado = executar_busca(
        api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
        endereco=request.args.get("endereco"),
        raio=int(request.args.get("raio", 5000)),
    )
    if resultado["erro"]:
        return jsonify({"erro": resultado["erro"]}), 400
    return jsonify({"total": resultado["total"], "provedores": resultado["provedores"]})
```

### Exemplo com tkinter

```python
from service import executar_busca

def ao_clicar_buscar():
    def progresso(info: dict) -> None:
        if info["novos_provedores"] is not None:
            label.config(text=f"[{info['etapa']}/{info['total_etapas']}] "
                              f"{info['novos_provedores']} novo(s) | total: {info['total_acumulado']}")
            janela.update_idletasks()

    resultado = executar_busca(
        api_key=entry_chave.get(),
        endereco=entry_endereco.get(),
        callback_progresso=progresso,
    )
    label.config(text=f"{resultado['total']} provedores encontrados.")
```

---

## Estrutura do projeto

```
buscador_provedores/
│
├── main.py            # CLI e modo interativo — delega lógica ao service.py
├── service.py         # Camada de serviço sem I/O (Flask, GUI, testes)
├── buscador.py        # Geocodificação + Places API + filtro de segurança de logs
├── exportador.py      # Exportação para CSV e Excel (.xlsx)
├── cache.py           # Cache local de Place Details em JSON
├── config.py          # Todas as configurações centralizadas
│
├── requirements.txt   # Dependências Python
├── .env.example       # Modelo do arquivo de variáveis de ambiente
├── .env               # Sua chave de API (NÃO versionar no Git!)
│
├── .cache_detalhes.json  # Cache gerado automaticamente (pode ser ignorado no Git)
└── resultados/           # Arquivos exportados (gerado automaticamente)
    ├── provedores_20240901_143012.csv
    └── provedores_20240901_143012.xlsx
```

---

## Parâmetros disponíveis

```
python main.py [opções]

Localização (escolha uma):
  -e, --endereco ENDEREÇO          Endereço textual
  -c, --coordenadas LAT LNG        Latitude e longitude em graus decimais

Busca:
  -r, --raio METROS                Raio de busca (padrão: 5000)

Exportação:
  -f, --formato {csv,excel,ambos}  Formato de saída (padrão: csv)
  -o, --saida DIRETÓRIO            Pasta de destino (padrão: resultados/)

API:
  --api-key CHAVE                  Chave da API — prefira o .env por segurança

Debug:
  -v, --verbose                    Exibe logs detalhados (chave mascarada)
  -h, --help                       Exibe esta ajuda
```

---

## Personalização

Todas as configurações ajustáveis estão em `config.py`:

| Constante | Descrição | Valor padrão |
|---|---|---|
| `RAIO_PADRAO` | Raio de busca em metros | `5000` |
| `TERMOS_DE_BUSCA` | Palavras-chave usadas na busca | 5 termos pré-definidos |
| `MAX_PAGINAS` | Máx. páginas de resultado por termo | `3` (= 60 resultados) |
| `CAMINHO_CACHE` | Arquivo de cache de Place Details | `".cache_detalhes.json"` |
| `DIRETORIO_SAIDA` | Pasta padrão para os arquivos gerados | `"resultados"` |
| `CAMPOS_DETALHES` | Campos solicitados ao Place Details | Nome, endereço, telefone, site, avaliação |

### Limpando o cache

Para forçar uma nova consulta à API ignorando os dados em cache, basta apagar o arquivo:

```bash
rm .cache_detalhes.json
```

---

## Limitações conhecidas

- **Cobertura do Google Maps**: empresas sem perfil no Google Maps não aparecem. Regiões menos urbanizadas tendem a ter menos cadastros.
- **Máximo de 60 resultados por termo de busca**: a Places API limita a 3 páginas de 20 itens. Adicionar termos em `TERMOS_DE_BUSCA` amplia o alcance.
- **Raio máximo da Places API**: 50.000 metros (50 km). Valores maiores são silenciosamente ignorados pela API.
- **Dados desatualizados**: telefone e site dependem do que está cadastrado no Google Maps pela própria empresa.
- **Rate limiting**: pausas automáticas entre chamadas para respeitar os limites. Buscas com muitos resultados podem levar alguns minutos.
- **Cache não expira automaticamente**: dados muito antigos podem divergir da realidade. Apague `.cache_detalhes.json` periodicamente ou ao notar inconsistências.

---

## Solução de problemas

| Mensagem de erro | Causa provável | Solução |
|---|---|---|
| `Chave de API não encontrada` | Arquivo `.env` ausente ou mal configurado | Crie o `.env` a partir do `.env.example` |
| `Chave de API inválida ou sem permissão` | API não ativada no Google Cloud | Ative Geocoding API e Places API no Console |
| `Endereço não encontrado` | Endereço muito vago ou incorreto | Adicione cidade, estado ou CEP |
| `Sem conexão com a internet` | Falha de rede | Verifique sua conexão |
| `Para exportar em Excel instale: pip install pandas openpyxl` | Dependências opcionais ausentes | Execute `pip install pandas openpyxl` |
| `Sem permissão para criar arquivo` | Pasta bloqueada ou arquivo aberto no Excel | Feche o Excel ou escolha outra pasta com `-o` |

---

## Licença

Uso interno. Consulte os [Termos de Uso da Google Maps Platform](https://cloud.google.com/maps-platform/terms) antes de redistribuir os dados coletados.
