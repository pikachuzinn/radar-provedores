# Buscador de Provedores de Internet

Script Python para encontrar provedores de internet próximos a uma localização usando a **Google Places API**. Ideal para analistas de viabilidade que precisam mapear a concorrência ou parceiros em uma região.

---

## Funcionalidades

- Usa a **Places API (New)** por padrão, com suporte à API legada para projetos antigos
- Aceita endereço textual ou coordenadas geográficas como entrada
- Busca provedores num raio configurável (padrão: 5 km)
- Extrai: nome, endereço, telefone, site e avaliação de cada empresa
- **Coordenadas e distância em km** de cada provedor até o centro da busca — permite ordenar a planilha por proximidade e descartar resultados fora da área de interesse
- Deduplica resultados automaticamente por `place_id`
- **Cache local de Place Details** — evita chamadas repetidas à API para o mesmo estabelecimento, reduzindo custo em buscas consecutivas na mesma região
- Exporta para **CSV** (padrão) ou **Excel (.xlsx)** com formatação profissional
- **Camada de serviço** (`service.py`) sem dependência de I/O, pronta para integração com Flask, FastAPI ou GUI
- Interface de linha de comando completa ou modo interativo
- **Chave de API nunca exposta em logs** — filtro de logging automático mascara a chave em qualquer saída de debug, inclusive nos logs de bibliotecas de terceiros
- Tratamento claro de erros (endereço não encontrado, chave inválida, falha de rede)
- **Relatório de sobreposição dos termos** (`--relatorio-termos`) — mostra quais termos de busca são redundantes, sem custar nenhuma requisição extra
- **Calibração multi-cidade** (`calibrar_termos.py`) — cruza várias regiões e recomenda o conjunto de termos que serve a todas elas
- **Suíte de testes** com 141 casos, sem dependência de rede nem de chave de API

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
   - **Places API (New)** — busca de estabelecimentos e detalhes

   > Atenção ao nome: **"Places API (New)"** e **"Places API"** são produtos
   > diferentes no Console. Este projeto usa a *(New)* por padrão. A antiga só
   > aparece para projetos criados antes de 01/03/2025.
5. Vá em **APIs e Serviços → Credenciais**
6. Clique em **+ Criar Credenciais → Chave de API**
7. Copie a chave gerada e cole no arquivo `.env`

### Restringindo a chave (recomendado)

Para evitar uso não autorizado caso a chave vaze:

- Em **Restrições de aplicativo**: selecione *Endereços IP* e adicione seu IP fixo, ou deixe sem restrição durante testes
- Em **Restrições de API**: selecione apenas *Geocoding API* e *Places API (New)*

---

## Segurança da chave de API

| Método | Segurança | Recomendado |
|---|---|---|
| Arquivo `.env` | Alta — não aparece em histórico nem em `ps aux` | Sim |
| Variável de ambiente exportada na sessão | Média — visível com `env` | Aceitável |
| Argumento `--api-key` no terminal | Baixa — fica no `~/.bash_history` e em `ps aux` | Apenas em testes |

Independentemente do método usado, a chave **nunca aparecerá em logs ou saída de debug** — o filtro `_FiltroChaveAPI` em `buscador.py` mascara qualquer ocorrência literal da chave, substituindo-a por `***API_KEY***`.

O filtro é instalado nos **handlers** do logger raiz, e não apenas no logger raiz em si. A distinção importa: no módulo `logging`, um filtro registrado em um *Logger* só é aplicado aos registros emitidos naquele logger — os que sobem por propagação dos loggers filhos passam direto. Como cada módulo do projeto usa `getLogger(__name__)`, um filtro somente no raiz nunca veria essas mensagens. Instalado nos handlers, ele alcança tudo que chega à saída, incluindo logs de `requests`/`urllib3`.

> **Consequência prática:** configure o logging **antes** de instanciar `BuscadorProvedores`. Handlers criados depois não recebem o filtro.

---

## Qual geração da Places API usar

O Google marcou a Places API legada como *legacy* em **01/03/2025**. Na prática:

| Situação do seu projeto no Google Cloud | O que usar |
|---|---|
| Criado a partir de 01/03/2025 | **Places API (New)** — a legada não pode mais ser ativada |
| Criado antes, já usando a legada | Qualquer uma; a legada segue funcionando |

A legada está congelada (sem novos recursos) e o Google promete avisar com no
mínimo 12 meses antes de desligá-la. O padrão deste projeto é a API nova.

Para voltar à legada, altere em `config.py`:

```python
USAR_PLACES_NOVA = False
```

### Por que a API nova sai muito mais barata

Na API legada, a Text Search devolvia um resumo sem telefone nem site: era
preciso **uma chamada de Place Details para cada estabelecimento**. Na API nova,
o cabeçalho `X-Goog-FieldMask` permite pedir telefone, site e avaliação já na
própria busca, para até 20 lugares por requisição.

Numa busca típica de 5 termos, 3 páginas e ~60 provedores encontrados:

| | Requisições de busca | Chamadas de Place Details | Total |
|---|---|---|---|
| Places API (Legacy) | 15 | até 60 | **até 75** |
| Places API (New) | 15 | 0 | **15** |

---

## Custo estimado das APIs

> **Atenção:** o antigo crédito mensal de US$ 200 **foi descontinuado** junto com
> a mudança de março de 2025. O modelo atual é de **cota gratuita por SKU**, e cada
> tipo de chamada tem a sua. Os valores abaixo são referência de Tier 1 (até 100 mil
> chamadas/mês) — confirme sempre na
> [página de preços oficial](https://developers.google.com/maps/billing-and-pricing/pricing).

| SKU | Grátis por mês | Acima disso (por 1.000) |
|---|---|---|
| Geocoding | 10.000 | US$ 5,00 |
| Text Search Enterprise | 1.000 | US$ 35,00 |
| Place Details Enterprise | 1.000 | US$ 20,00 |

O field mask padrão deste projeto inclui telefone, site e avaliação — campos da
faixa **Enterprise**, a mais cara. É ela que define o SKU da requisição inteira.

### Quanto rende a cota gratuita

Cada busca completa consome **1 chamada de Geocoding + até 15 de Text Search**
(5 termos × 3 páginas). Com 1.000 Text Search Enterprise gratuitas por mês:

| Cenário | Text Search por busca | Buscas grátis/mês | Custo unitário acima da cota |
|---|---|---|---|
| Padrão (5 termos, 3 páginas) | até 15 | ~66 | ~US$ 0,53 |
| Enxuto (2 termos, 3 páginas) | até 6 | ~166 | ~US$ 0,21 |
| Mínimo (1 termo, 1 página) | 1 | 1.000 | ~US$ 0,035 |

> **Dica:** para reduzir custo, corte termos em `TERMOS_DE_BUSCA` ou baixe
> `MAX_PAGINAS`. Remover os campos Enterprise de `CAMPOS_PLACES_NOVA`
> (`nationalPhoneNumber`, `websiteUri`, `rating`, `userRatingCount`) derruba a
> requisição para a faixa Pro — mas aí você perde justamente o contato das empresas.

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

# Cada provedor traz também coordenadas e distância até o centro da busca
print(resultado["provedores"][0]["distancia_km"])   # ex: 2.41
print(resultado["provedores"][0]["latitude"])       # ex: -26.3044

# Sobreposição entre os termos, calculada sem requisição extra
print(resultado["analise_termos"]["dispensaveis"])  # termos que podem sair
```

`executar_busca()` **nunca levanta exceção**: qualquer problema — chave ausente,
endereço inválido, falha de rede, erro de exportação — volta preenchido na chave
`"erro"`. Isso permite que CLI, API web e GUI tratem falhas do mesmo jeito.

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

### Usando a classe diretamente

Se precisar de controle fino sobre as etapas, use `BuscadorProvedores` como
context manager — ele grava o cache pendente, fecha a sessão HTTP e remove o
filtro de log ao sair do bloco:

```python
from buscador import BuscadorProvedores

with BuscadorProvedores(api_key="SUA_CHAVE") as buscador:
    lat, lng = buscador.geocodificar("Itajaí, SC")
    provedores = buscador.buscar_todos(lat, lng, raio=8000)
```

Para forçar uma geração da API sem mexer no `config.py`, passe `usar_nova`:

```python
BuscadorProvedores(api_key="SUA_CHAVE", usar_nova=False)   # Places API (Legacy)
```

> Em processos de vida longa (servidor web, GUI) isso não é opcional. Cada
> instância registra um filtro no logging global; sem o encerramento, eles se
> acumulam a cada requisição e toda mensagem de log passa por todos eles.

---

## Otimizando os termos de busca

Cada termo em `TERMOS_DE_BUSCA` custa até 3 requisições por busca, mas vários
deles encontram as mesmas empresas. O relatório mede exatamente isso:

```bash
python main.py -e "Itajaí, SC" -r 10000 --relatorio-termos
```

O relatório **não custa nenhuma requisição adicional** — usa os dados que a
busca já produziu.

### Como ler o resultado

```
TERMO                               ACHOU  SÓ ELE  REPET.  REQS
provedor de internet                   11       2    82%     1
provedor internet fibra óptica          6       0   100%     1  ← dispensável
internet banda larga                    6       0   100%     1
```

| Coluna | Significado |
|---|---|
| ACHOU | Estabelecimentos que o termo trouxe |
| SÓ ELE | Os que nenhum outro termo encontrou |
| REPET. | Fração dos resultados que outro termo também traria |
| REQS | Requisições que o termo consumiu |

### Cuidado: "SÓ ELE = 0" não significa "pode remover"

No exemplo acima, `internet banda larga` não tem nenhum resultado exclusivo —
mas **não** está marcado como dispensável. O motivo é uma armadilha clássica:
vários termos podem ser redundantes *isoladamente* e ainda assim necessários
*em conjunto*, quando uma empresa aparece apenas na combinação deles.

Remover um por vez é seguro; remover todos os de "SÓ ELE = 0" de uma vez pode
custar resultados. Por isso a recomendação do relatório é calculada por
**cobertura**, e não pela coluna "SÓ ELE":

```
RECOMENDAÇÃO: 2 dos 5 termos bastam para os mesmos resultados nesta região.
  Manter:  ✓ provedor de internet   ✓ internet banda larga
  Remover: ✗ provedor internet fibra óptica  ✗ empresa telecomunicações internet
           ✗ ISP internet service provider
  Economia: 3 de 5 requisições (60%) sem perder nenhum resultado.
```

O conjunto sob "Manter" reproduz, por construção, todos os estabelecimentos
que os cinco termos juntos encontraram.

---

## Calibração multi-cidade

A sobreposição **varia por região**: um termo inútil numa capital pode ser o
único a encontrar algo no interior. Decidir o `TERMOS_DE_BUSCA` a partir de uma
cidade só é generalizar demais.

O `calibrar_termos.py` mede várias cidades, cruza os resultados e recomenda o
menor conjunto de termos que reproduz o resultado completo em **todas** elas:

```bash
python calibrar_termos.py "Florianópolis, SC" "Itajaí, SC" "São Joaquim, SC" -r 10000
```

Escolha cidades que representem sua área de atuação — uma capital, uma cidade
média e uma do interior costumam revelar as diferenças que importam.

### Como a recomendação é calculada

Cada elemento a cobrir é o par **(cidade, estabelecimento)**, e um termo só
cobre uma empresa na cidade em que realmente a encontrou. Com isso, o mesmo
algoritmo de cobertura garante por construção que o conjunto recomendado não
perde nada em nenhuma das cidades — **não é uma média entre elas**.

### Saída

```
TERMO                               ESSENC.  ACHOU  SÓ ELE  REQS
provedor de internet                  2/3       18       4     3
internet banda larga                  2/3       13       2     3
provedor internet fibra óptica        2/3        6       2     3
ISP internet service provider         0/3        1       0     3  ← dispensável
empresa telecomunicações internet     0/3        3       0     3  ← dispensável

RECOMENDAÇÃO: manter 3 dos 5 termos.

TERMOS_DE_BUSCA: list[str] = [
    "provedor de internet",
    "provedor internet fibra óptica",
    "internet banda larga",
]

  Economia: 6 de 15 requisições (40%) nas cidades medidas.

Cuidado ao medir uma cidade só — estes termos apareceram como dispensáveis em
uma região e essenciais em outra:
    ! provedor de internet — essencial em 2, dispensável em 1 de 3
```

O bloco `TERMOS_DE_BUSCA` sai pronto para colar em `config.py`. O alerta final
mostra exatamente quais termos uma medição de cidade única teria cortado por
engano.

### Custo e aproveitamento

Cada cidade consome 1 chamada de Geocoding e até `termos × páginas`
requisições de busca — com a configuração padrão, 15 por cidade. O total
estimado é exibido **antes** de começar.

Como a busca é paga, use `--exportar` para também salvar os provedores
encontrados, em uma subpasta por cidade:

```bash
python calibrar_termos.py "Itajaí, SC" "Chapecó, SC" --exportar csv -o analises
```

Uma cidade que falhe (endereço não encontrado, erro de rede) não interrompe as
demais: é registrada como ignorada, e o relatório avisa que a recomendação só
vale para as cidades efetivamente medidas.

---

---

## Estrutura do projeto

```
buscador_provedores/
│
├── main.py            # CLI e modo interativo — delega lógica ao service.py
├── calibrar_termos.py # CLI de calibração multi-cidade dos termos de busca
├── service.py         # Camada de serviço sem I/O (Flask, GUI, testes)
├── buscador.py        # Orquestração: geocodificação, paginação, dedup, cache, logs
├── clientes.py        # Clientes HTTP das duas gerações da Places API
├── exportador.py      # Exportação para CSV e Excel (.xlsx)
├── cache.py           # Cache local de Place Details em JSON
├── geo.py             # Distância entre coordenadas (Haversine)
├── analise_termos.py  # Sobreposição entre os termos de busca (só cálculo)
├── config.py          # Todas as configurações centralizadas
│
├── conftest.py        # Fixtures da suíte de testes (dublês de requests)
├── pytest.ini         # Configuração do pytest
├── tests/             # Suíte de testes — não usa rede nem chave de API
│   ├── test_geo.py
│   ├── test_cache.py
│   ├── test_analise_termos.py
│   ├── test_buscador.py
│   ├── test_calibracao.py
│   ├── test_clientes.py
│   ├── test_exportador.py
│   ├── test_filtro_log.py
│   └── test_service.py
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

Diagnóstico:
  --relatorio-termos               Analisa a sobreposição entre os termos de busca

Debug:
  -v, --verbose                    Exibe logs detalhados (chave mascarada)
  -h, --help                       Exibe esta ajuda
```

---

## Personalização

Todas as configurações ajustáveis estão em `config.py`:

| Constante | Descrição | Valor padrão |
|---|---|---|
| `USAR_PLACES_NOVA` | `True` = Places API (New); `False` = legada | `True` |
| `CAMPOS_PLACES_NOVA` | Campos pedidos no `X-Goog-FieldMask` — definem o SKU | 9 campos |
| `IDIOMA_RESULTADOS` | Idioma dos resultados (só API nova) | `"pt-BR"` |
| `REGIAO_RESULTADOS` | Região dos resultados (só API nova) | `"BR"` |
| `RESULTADOS_POR_PAGINA` | Resultados por página; máximo da API: 20 | `20` |
| `RAIO_PADRAO` | Raio de busca em metros | `5000` |
| `TERMOS_DE_BUSCA` | Palavras-chave usadas na busca | 5 termos pré-definidos |
| `MAX_PAGINAS` | Máx. páginas de resultado por termo | `3` (= 60 resultados) |
| `CAMINHO_CACHE` | Arquivo de cache de Place Details | `".cache_detalhes.json"` |
| `INTERVALO_GRAVACAO_CACHE` | A cada quantas entradas novas o cache vai ao disco | `25` |
| `RAIO_ESTRITO` | Descarta resultados fora do raio pedido | `False` |
| `DIRETORIO_SAIDA` | Pasta padrão para os arquivos gerados | `"resultados"` |
| `CAMPOS_DETALHES` | Campos solicitados ao Place Details | Nome, endereço, telefone, site, avaliação |

### Limpando o cache

Para forçar uma nova consulta à API ignorando os dados em cache, basta apagar o arquivo:

```bash
rm .cache_detalhes.json
```

---

## Testes

A suíte cobre as duas gerações da Places API, geocodificação, paginação, cache,
deduplicação, filtro de distância, mascaramento da chave de API e exportação. **Nenhum teste acessa a rede ou usa uma
chave real** — a sessão HTTP é substituída por um dublê que devolve respostas
pré-programadas e registra cada chamada.

```bash
pip install pytest
python -m pytest
```

Para ver o nome de cada caso:

```bash
python -m pytest -v
```

Para rodar apenas um arquivo:

```bash
python -m pytest tests/test_buscador.py
```

### O que a suíte protege

| Arquivo | Cobertura |
|---|---|
| `test_geo.py` | Haversine: distâncias conhecidas, simetria, cruzamento do equador |
| `test_cache.py` | Arquivo ausente, JSON corrompido, formato inesperado, acentuação |
| `test_clientes.py` | Forma da requisição, cabeçalhos, field mask, mapeamento de erros e tradução de payload de cada geração |
| `test_analise_termos.py` | Contribuição exclusiva, cobertura gulosa e a armadilha dos termos coletivamente necessários |
| `test_calibracao.py` | Consolidação entre cidades, cidades com erro, e o invariante de cobertura por região |
| `test_buscador.py` | Paginação, deduplicação, gravação em lote do cache, filtro de raio, callback de progresso |
| `test_filtro_log.py` | Mascaramento da chave vinda de loggers filhos e remoção do filtro ao encerrar |
| `test_exportador.py` | Ordem das colunas, BOM do CSV, campos ausentes, formatação do Excel |
| `test_service.py` | Contrato de retorno, caminhos de erro, ausência de vazamento entre chamadas |

Cada correção e cada garantia da migração foi validada por **teste de mutação**:
reintroduzir o defeito no código faz a suíte falhar. Um teste que passa nos dois
cenários não protege nada.

---

## Limitações conhecidas

- **Cobertura do Google Maps**: empresas sem perfil no Google Maps não aparecem. Regiões menos urbanizadas tendem a ter menos cadastros.
- **Máximo de 60 resultados por termo de busca**: a Places API limita a 3 páginas de 20 itens, nas duas gerações. Adicionar termos em `TERMOS_DE_BUSCA` amplia o alcance.
- **`radius` é um viés, não um filtro**: a Places Text Search usa o raio para ordenar por relevância, mas devolve estabelecimentos bem além dele. Use a coluna *Distância (km)* para filtrar na planilha, ou defina `RAIO_ESTRITO = True` em `config.py` para descartar automaticamente — o descarte ocorre antes da chamada de Place Details, então também reduz custo.
- **Raio máximo da Places API**: 50.000 metros (50 km). Valores maiores são silenciosamente ignorados pela API.
- **Dados desatualizados**: telefone e site dependem do que está cadastrado no Google Maps pela própria empresa.
- **Rate limiting**: pausas automáticas entre chamadas para respeitar os limites. Na API legada há ainda uma espera obrigatória de 2 s antes de usar o token de cada página seguinte — a API nova não exige essa espera, o que torna as buscas visivelmente mais rápidas.
- **Cache não expira automaticamente**: dados muito antigos podem divergir da realidade. Apague `.cache_detalhes.json` periodicamente ou ao notar inconsistências.
- **Com a API nova o cache quase não é exercitado**: como os dados já vêm na busca, não há chamadas de Place Details por estabelecimento para cachear. O cache permanece ativo para consultas pontuais via `obter_detalhes()`.

---

## Solução de problemas

| Mensagem de erro | Causa provável | Solução |
|---|---|---|
| `Chave de API não encontrada` | Arquivo `.env` ausente ou mal configurado | Crie o `.env` a partir do `.env.example` |
| `Chave de API inválida ou sem permissão` | API não ativada no Google Cloud | Ative Geocoding API e Places API (New) no Console |
| `Places API (New) não ativada no projeto` | Ativou "Places API" (legada) em vez de "Places API (New)" | São produtos distintos no Console; ative a *(New)* |
| `sem permissão para a Places API (Legacy)` | Projeto criado a partir de 01/03/2025 não tem acesso à API legada | Defina `USAR_PLACES_NOVA = True` em `config.py` |
| `Cota da Places API esgotada` | Passou da cota gratuita mensal do SKU | Reduza `TERMOS_DE_BUSCA` ou `MAX_PAGINAS`, ou aguarde a virada do mês |
| `Endereço não encontrado` | Endereço muito vago ou incorreto | Adicione cidade, estado ou CEP |
| `Sem conexão com a internet` | Falha de rede | Verifique sua conexão |
| `Para exportar em Excel instale: pip install pandas openpyxl` | Dependências opcionais ausentes | Execute `pip install pandas openpyxl` |
| `Sem permissão para criar arquivo` | Pasta bloqueada ou arquivo aberto no Excel | Feche o Excel ou escolha outra pasta com `-o` |

---

## Licença

Uso interno. Consulte os [Termos de Uso da Google Maps Platform](https://cloud.google.com/maps-platform/terms) antes de redistribuir os dados coletados.
