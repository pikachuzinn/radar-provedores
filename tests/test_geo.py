"""Testes de geo.py — cálculo de distância por Haversine."""

import pytest

from geo import distancia_km


def test_mesma_coordenada_da_zero():
    assert distancia_km(-27.5954, -48.5480, -27.5954, -48.5480) == 0.0


def test_distancia_conhecida_florianopolis_joinville():
    """
    Distância em linha reta Florianópolis → Joinville: ~146 km.
    Tolerância de 2 km cobre a diferença entre modelo esférico e elipsoidal.
    """
    resultado = distancia_km(-27.5954, -48.5480, -26.3044, -48.8487)
    assert resultado == pytest.approx(146.6, abs=2.0)


def test_distancia_e_simetrica():
    ida = distancia_km(-27.5954, -48.5480, -26.3044, -48.8487)
    volta = distancia_km(-26.3044, -48.8487, -27.5954, -48.5480)
    assert ida == volta


def test_cruzando_o_equador():
    """Sinais opostos de latitude devem somar, não subtrair."""
    # 1 grau ao norte + 1 grau ao sul do equador = ~222 km
    assert distancia_km(1.0, 0.0, -1.0, 0.0) == pytest.approx(222.4, abs=1.0)


def test_arredondado_em_duas_casas():
    resultado = distancia_km(-27.5954, -48.5480, -27.6000, -48.5500)
    assert resultado == round(resultado, 2)
