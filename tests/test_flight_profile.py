"""Pruebas de la física del perfil de vuelo (sin Qt)."""

from __future__ import annotations

import math

import pytest

from gs.flight_profile import G, FlightProfile, MissionConfig


@pytest.fixture()
def perfil() -> FlightProfile:
    return FlightProfile()


def test_hitos_de_la_mision(perfil: FlightProfile) -> None:
    # Ascenso 0 → 450 m a 5 m/s
    assert perfil.t_ascenso == pytest.approx(90.0)
    assert perfil.altitud(perfil.t_ascenso) == pytest.approx(450.0)
    # Despliegue exactamente a 200 m
    assert perfil.altitud(perfil.t_despliegue) == pytest.approx(200.0, abs=1e-6)
    # Aterrizaje a 4,7 m/s desde 200 m
    assert perfil.t_aterrizaje - perfil.t_despliegue == pytest.approx(200.0 / 4.7)
    assert perfil.altitud(perfil.t_aterrizaje) == pytest.approx(0.0, abs=1e-9)
    # La secundaria cae libre desde 200 m y llega antes que la primaria
    assert perfil.t_aterrizaje_secundaria < perfil.t_aterrizaje


def test_altitud_monotona_por_fases(perfil: FlightProfile) -> None:
    dt = 0.1
    t = 0.0
    anterior = perfil.altitud(t)
    while t < perfil.t_aterrizaje:
        t += dt
        actual = perfil.altitud(t)
        if t <= perfil.t_ascenso:
            assert actual >= anterior - 1e-6
        else:
            assert actual <= anterior + 1e-6
        anterior = actual


def test_velocidad_por_fases(perfil: FlightProfile) -> None:
    assert perfil.velocidad(10.0) == pytest.approx(5.0)
    # En caída libre la velocidad terminal es -41 m/s como máximo
    assert perfil.velocidad(perfil.t_despliegue) < -35.0
    assert perfil.velocidad(perfil.t_despliegue) > -41.0
    # Bajo el autogiro, descenso constante
    mitad = 0.5 * (perfil.t_despliegue + perfil.t_aterrizaje)
    assert perfil.velocidad(mitad) == pytest.approx(-4.7)
    # En el suelo, reposo
    assert perfil.velocidad(perfil.t_fin) == 0.0


def test_aceleracion_caida_libre(perfil: FlightProfile) -> None:
    # Justo al soltar, la aceleración es -g (sin velocidad todavía)
    assert perfil.aceleracion(perfil.t_ascenso + 0.02) == pytest.approx(-G, abs=0.15)
    # Bajo el autogiro, régimen estacionario
    mitad = 0.5 * (perfil.t_despliegue + perfil.t_aterrizaje)
    assert perfil.aceleracion(mitad) == pytest.approx(0.0, abs=0.5)
    # El modelo nunca entrega valores absurdos
    for t in range(0, int(perfil.t_fin)):
        assert abs(perfil.aceleracion(float(t))) <= 100.0


def test_estados_de_mision(perfil: FlightProfile) -> None:
    assert perfil.estado(-1.0) == 0
    assert perfil.estado(0.0) == 1
    assert perfil.estado(perfil.t_ascenso - 1.0) == 1
    assert perfil.estado(perfil.t_despliegue) == 2
    assert perfil.estado(perfil.t_aterrizaje) == 3
    assert perfil.estado(perfil.t_fin) == 4


def test_banderas_de_despliegue(perfil: FlightProfile) -> None:
    assert perfil.satelite_desplegado(perfil.t_despliegue - 0.1) == 0
    assert perfil.satelite_desplegado(perfil.t_despliegue) == 1
    assert perfil.autogiro_desplegado(perfil.t_despliegue + 0.1) == 0
    assert perfil.autogiro_desplegado(perfil.t_despliegue + 0.25) == 1


def test_carga_secundaria_se_aleja_tras_el_despliegue(perfil: FlightProfile) -> None:
    assert perfil.distancia_secundaria(perfil.t_despliegue - 1.0) == 0.0
    d_medio = perfil.distancia_secundaria(
        0.5 * (perfil.t_despliegue + perfil.t_aterrizaje)
    )
    d_final = perfil.distancia_secundaria(perfil.t_fin)
    assert 0.0 < d_medio < d_final
    # Con los valores por defecto la secundaria queda a ~125 m
    assert 80.0 < d_final < 180.0
    rumbo = perfil.rumbo_secundaria(perfil.t_fin)
    assert 0.0 <= rumbo < 360.0


def test_telemetria_completa_y_coherente(perfil: FlightProfile) -> None:
    for t in (0.0, 45.0, perfil.t_despliegue, perfil.t_aterrizaje + 1.0):
        muestra = perfil.sample(t)
        assert muestra.t == pytest.approx(t)
        assert muestra.altitude >= 0.0
        assert math.isfinite(muestra.velocity)
        assert math.isfinite(muestra.accel)
        assert muestra.pressure > 0.0
        assert muestra.sec_distance >= 0.0
        assert 0.0 <= muestra.sec_bearing < 360.0


def test_configuracion_personalizada() -> None:
    perfil = FlightProfile(MissionConfig(alt_suelta=300.0, alt_despliegue=150.0,
                                         v_ascenso=3.0, v_autogiro=5.0))
    assert perfil.t_ascenso == pytest.approx(100.0)
    assert perfil.altitud(perfil.t_despliegue) == pytest.approx(150.0, abs=1e-6)
    assert perfil.altitud(perfil.t_aterrizaje) == pytest.approx(0.0, abs=1e-9)
