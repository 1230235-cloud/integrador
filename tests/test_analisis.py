"""Pruebas del análisis post-vuelo sobre un vuelo sintético."""

from __future__ import annotations

import csv
import json
import os

import pytest

from gs.flight_profile import FlightProfile
from gs.protocol import CSV_HEADER, format_csv_row
from tools import analisis_vuelo
from tools.generar_vuelo_sintetico import generar


@pytest.fixture()
def vuelo(tmp_path) -> str:
    ruta = os.path.join(tmp_path, "vuelo.csv")
    generar(ruta, hz=10.0)
    return ruta


def test_generador_produce_un_csv_valido(vuelo: str) -> None:
    with open(vuelo, encoding="utf-8") as f:
        cabecera = f.readline().strip()
        filas = [ln for ln in f if ln.strip()]
    assert cabecera == CSV_HEADER
    assert len(filas) > 100
    assert filas[0].startswith("0.00,")


def test_analisis_detecta_los_hitos(vuelo: str) -> None:
    resultado = analisis_vuelo.analizar(vuelo, masa_kg=0.30)
    assert len(resultado.segmentos) == 1
    metricas = resultado.metricas["segmento_1"]

    assert metricas["altura_max_m"] == pytest.approx(450.0, abs=2.0)
    assert metricas["altura_despliegue_m"] == pytest.approx(200.0, abs=3.0)
    assert abs(metricas["error_despliegue_m"]) < 3.0
    assert metricas["vel_impacto_ms"] == pytest.approx(4.7, abs=0.8)
    assert metricas["transmision_post_aterrizaje_s"] >= 10.0
    assert metricas["vel_max_ascenso_ms"] == pytest.approx(5.0, abs=0.5)
    assert metricas["vel_max_descenso_ms"] < -30.0
    assert metricas["acc_min_ms2"] < -5.0


def test_exporta_procesado_y_resumen(vuelo: str, tmp_path) -> None:
    resultado = analisis_vuelo.analizar(vuelo)
    segmento = resultado.segmentos[0]
    procesado = os.path.join(tmp_path, "procesado.csv")
    analisis_vuelo.exportar_procesado(segmento, procesado)

    with open(procesado, encoding="utf-8") as f:
        filas = list(csv.reader(f))
    assert filas[0] == ["t_s", "alt_m", "vel_ms"]
    assert len(filas) == len(segmento) + 1

    resumen = os.path.join(tmp_path, "resumen.json")
    with open(resumen, "w", encoding="utf-8") as f:
        json.dump({"metricas": resultado.metricas}, f)
    with open(resumen, encoding="utf-8") as f:
        assert "segmento_1" in json.load(f)["metricas"]


def test_admite_csv_antiguo_sin_columnas_nuevas(tmp_path) -> None:
    """Un registro del firmware viejo (13 campos) debe seguir analizándose."""
    perfil = FlightProfile()
    ruta = os.path.join(tmp_path, "antiguo.csv")
    columnas = CSV_HEADER.split(",")[:12]
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(columnas)
        t = 0.0
        paquete = 0
        while t <= perfil.t_fin:
            muestra = perfil.sample(t)
            paquete += 1
            muestra.packet = paquete
            escritor.writerow(format_csv_row(muestra).split(",")[:12])
            t += 0.1

    resultado = analisis_vuelo.analizar(ruta)
    metricas = resultado.metricas["segmento_1"]
    assert metricas["altura_max_m"] == pytest.approx(450.0, abs=2.0)
    assert "acc_min_ms2" not in metricas


def test_csv_corrupto_falla_con_mensaje(tmp_path) -> None:
    ruta = os.path.join(tmp_path, "malo.csv")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("hola,mundo\n1,2\n")
    with pytest.raises(ValueError):
        analisis_vuelo.cargar(ruta)


def test_segmentos_separados_por_reinicio(tmp_path) -> None:
    """Dos vuelos seguidos (t vuelve a 0) generan dos segmentos."""
    perfil = FlightProfile()
    ruta = os.path.join(tmp_path, "dos.csv")
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(CSV_HEADER.split(","))
        for _ in range(2):
            t = 0.0
            while t <= 40.0:
                escritor.writerow(format_csv_row(perfil.sample(t)).split(","))
                t += 0.1

    segmentos = analisis_vuelo.cargar(ruta)
    assert len(segmentos) == 2
    assert segmentos[0].t[0] == pytest.approx(0.0)
    assert segmentos[1].t[0] == pytest.approx(0.0)
