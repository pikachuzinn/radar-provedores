"""
geo.py — Cálculos geográficos auxiliares.

Isolado dos módulos de rede e de I/O para permitir teste unitário direto,
sem chave de API nem acesso à internet.
"""

from math import asin, cos, radians, sin, sqrt

# Raio médio da Terra em quilômetros (esfera de referência WGS-84).
RAIO_TERRA_KM = 6371.0088


def distancia_km(
    lat_origem: float,
    lng_origem: float,
    lat_destino: float,
    lng_destino: float,
) -> float:
    """
    Distância em linha reta entre dois pontos, pela fórmula de Haversine.

    Precisão suficiente para análise de viabilidade (erro < 0,5% em
    distâncias urbanas). Não considera relevo nem malha viária — é a
    distância "em linha reta", não a distância de deslocamento.

    Args:
        lat_origem: Latitude do ponto de origem em graus decimais.
        lng_origem: Longitude do ponto de origem em graus decimais.
        lat_destino: Latitude do ponto de destino em graus decimais.
        lng_destino: Longitude do ponto de destino em graus decimais.

    Returns:
        Distância em quilômetros, arredondada em 2 casas decimais.
    """
    lat1, lng1, lat2, lng2 = map(
        radians, (lat_origem, lng_origem, lat_destino, lng_destino)
    )

    delta_lat = lat2 - lat1
    delta_lng = lng2 - lng1

    # Haversine: a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lng / 2) ** 2
    c = 2 * asin(sqrt(a))

    return round(RAIO_TERRA_KM * c, 2)
