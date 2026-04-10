"""
config.py — Configurações centrais do buscador de provedores de internet.

Altere as constantes aqui para ajustar o comportamento padrão do script
sem precisar modificar a lógica principal.
"""

# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------

# Raio padrão de busca em metros (5 km)
RAIO_PADRAO: int = 5_000

# Termos usados na busca por provedores. Múltiplos termos aumentam o alcance;
# resultados duplicados são removidos automaticamente pelo place_id.
TERMOS_DE_BUSCA: list[str] = [
    "provedor de internet",
    "provedor internet fibra óptica",
    "empresa telecomunicações internet",
    "internet banda larga",
    "ISP internet service provider",
]

# ---------------------------------------------------------------------------
# API do Google Places
# ---------------------------------------------------------------------------

# Endpoints oficiais
URL_GEOCODING = "https://maps.googleapis.com/maps/api/geocode/json"
URL_TEXT_SEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
URL_DETALHES = "https://maps.googleapis.com/maps/api/place/details/json"

# Campos solicitados na chamada de Place Details.
# Cada campo tem um custo separado; remova os que não precisar para economizar.
CAMPOS_DETALHES: list[str] = [
    "name",
    "formatted_address",
    "formatted_phone_number",
    "website",
    "rating",
    "user_ratings_total",
    "business_status",
    "opening_hours",
]

# Número máximo de páginas de resultados por termo de busca (cada página = 20 itens).
# Máximo suportado pela API: 3 páginas = 60 resultados por termo.
MAX_PAGINAS: int = 3

# Intervalo (segundos) entre chamadas à API para respeitar rate limits.
INTERVALO_ENTRE_CHAMADAS: float = 0.2

# Intervalo adicional (segundos) ao buscar a próxima página paginada.
# A API exige um pequeno atraso antes de usar o next_page_token.
INTERVALO_PAGINACAO: float = 2.0

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

# Caminho do arquivo de cache de Place Details (relativo ao diretório de execução).
# O cache evita chamadas repetidas à API para o mesmo place_id.
CAMINHO_CACHE: str = ".cache_detalhes.json"

# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

# Diretório padrão onde os arquivos exportados serão salvos.
DIRETORIO_SAIDA: str = "resultados"

# Colunas e seus rótulos amigáveis para o arquivo de saída.
COLUNAS_SAIDA: dict[str, str] = {
    "nome": "Nome",
    "endereco": "Endereço",
    "telefone": "Telefone",
    "site": "Site",
    "avaliacao": "Avaliação",
    "total_avaliacoes": "Nº de Avaliações",
    "status": "Status",
    "place_id": "Place ID (Google)",
}
