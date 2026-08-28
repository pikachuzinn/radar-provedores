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
# Geração da Places API
# ---------------------------------------------------------------------------

# O Google congelou a Places API legada em 01/03/2025: projetos do Google Cloud
# criados a partir dessa data NÃO conseguem mais ativá-la, embora projetos
# anteriores continuem funcionando (com aviso mínimo de 12 meses antes de um
# eventual desligamento).
#
#   True  — Places API (New). Padrão, e única opção para projetos novos.
#           Traz telefone, site e avaliação já na busca: dispensa a chamada de
#           Place Details por estabelecimento e reduz muito o custo.
#   False — Places API (Legacy). Só para projetos que já a utilizam hoje.
USAR_PLACES_NOVA: bool = True

# Idioma e região dos resultados (usados apenas pela API nova).
IDIOMA_RESULTADOS: str = "pt-BR"
REGIAO_RESULTADOS: str = "BR"

# Resultados por página. Máximo aceito pela API: 20.
RESULTADOS_POR_PAGINA: int = 20

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# Geocoding API — comum às duas gerações, não faz parte da migração.
URL_GEOCODING = "https://maps.googleapis.com/maps/api/geocode/json"

# Places API (New)
URL_PLACES_BUSCA = "https://places.googleapis.com/v1/places:searchText"
URL_PLACES_DETALHES = "https://places.googleapis.com/v1/places"  # + "/{place_id}"

# Places API (Legacy)
URL_TEXT_SEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
URL_DETALHES = "https://maps.googleapis.com/maps/api/place/details/json"

# ---------------------------------------------------------------------------
# Campos solicitados
# ---------------------------------------------------------------------------

# Campos da Places API (New), usados no cabeçalho X-Goog-FieldMask.
# O field mask é obrigatório: sem ele a API retorna erro, e não uma resposta
# com todos os campos. Cada campo tem faixa de preço própria — 'id',
# 'formattedAddress' e 'location' são Essentials; 'displayName' e
# 'businessStatus' são Pro; telefone, site e avaliação são Enterprise.
# Remover os campos Enterprise reduz o custo por requisição.
CAMPOS_PLACES_NOVA: list[str] = [
    "id",
    "displayName",
    "formattedAddress",
    "nationalPhoneNumber",
    "websiteUri",
    "rating",
    "userRatingCount",
    "businessStatus",
    "location",
]

# Campos solicitados na chamada de Place Details da API legada.
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
# Exigência da API legada: o next_page_token só passa a valer alguns segundos
# depois de emitido. A API nova aceita o pageToken de imediato e ignora este valor.
INTERVALO_PAGINACAO: float = 2.0

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

# Caminho do arquivo de cache de Place Details (relativo ao diretório de execução).
# O cache evita chamadas repetidas à API para o mesmo place_id.
CAMINHO_CACHE: str = ".cache_detalhes.json"

# A cada quantas entradas novas o cache é gravado em disco durante a busca.
# Gravar a cada entrada reescreve o arquivo inteiro N vezes; gravar apenas no
# final arrisca perder tudo se a execução for interrompida. Este valor é o
# meio-termo — o cache também é sempre gravado ao fim da busca.
INTERVALO_GRAVACAO_CACHE: int = 25

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
    "distancia_km": "Distância (km)",
    "avaliacao": "Avaliação",
    "total_avaliacoes": "Nº de Avaliações",
    "status": "Status",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "place_id": "Place ID (Google)",
}

# ---------------------------------------------------------------------------
# Filtro de distância
# ---------------------------------------------------------------------------

# O parâmetro `radius` da Places Text Search é um *viés* de relevância, não um
# filtro rígido: a API pode devolver estabelecimentos bem além do raio pedido.
# Com RAIO_ESTRITO = True, resultados acima do raio são descartados.
# Com False (padrão), tudo é mantido e a coluna "Distância (km)" permite ao
# analista filtrar manualmente na planilha, sem perder dado nenhum.
RAIO_ESTRITO: bool = False
