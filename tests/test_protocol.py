"""Pruebas del protocolo de telemetría (compatibilidad y validación)."""

from __future__ import annotations

import pytest

from gs import protocol
from gs.protocol import Telemetry, format_csv_row, parse_event, parse_telemetry

TRAMA_LEGADA = "T,125.40,1042.6,22.8,891.4,8.61,3.1,-2.4,179.8,2,1,1,1254"
TRAMA_COMPLETA = (
    "T,125.40,1042.6,22.8,891.4,8.61,3.1,-2.4,179.8,2,1,1,1254,"
    "-4.70,0.12,38.5,247.0"
)


def test_trama_antigua_sigue_siendo_valida() -> None:
    telemetria = parse_telemetry(TRAMA_LEGADA)
    assert telemetria is not None
    assert telemetria.altitude == pytest.approx(1042.6)
    assert telemetria.state == 2
    assert telemetria.satellite == 1
    assert telemetria.chute == 1
    assert telemetria.packet == 1254
    # Campos nuevos: valores neutros
    assert telemetria.velocity == 0.0
    assert telemetria.sec_distance == -1.0
    assert telemetria.secondary_known is False


def test_trama_completa_con_campos_de_mision() -> None:
    telemetria = parse_telemetry(TRAMA_COMPLETA)
    assert telemetria is not None
    assert telemetria.velocity == pytest.approx(-4.70)
    assert telemetria.accel == pytest.approx(0.12)
    assert telemetria.sec_distance == pytest.approx(38.5)
    assert telemetria.sec_bearing == pytest.approx(247.0)
    assert telemetria.secondary_known is True
    assert telemetria.sink_rate == pytest.approx(4.70)


def test_round_trip_csv() -> None:
    original = Telemetry(
        t=12.5, altitude=310.4, temperature=18.2, pressure=980.1, voltage=8.1,
        pitch=1.5, roll=-2.0, yaw=90.0, state=2, satellite=1, chute=1,
        packet=42, velocity=-6.3, accel=-9.81, sec_distance=12.0, sec_bearing=310.0,
    )
    recuperado = parse_telemetry("T," + format_csv_row(original))
    assert recuperado is not None
    for campo in ("t", "altitude", "temperature", "pressure", "voltage",
                  "pitch", "roll", "yaw", "velocity", "accel",
                  "sec_distance", "sec_bearing"):
        assert getattr(recuperado, campo) == pytest.approx(getattr(original, campo),
                                                          abs=0.02), campo
    assert recuperado.state == original.state
    assert recuperado.packet == original.packet


def test_linea_que_no_es_telemetria_devuelve_none() -> None:
    assert parse_telemetry("E,barómetro no responde") is None
    assert parse_telemetry("") is None
    assert parse_telemetry("basura") is None


def test_trama_incompleta_lanza_error() -> None:
    with pytest.raises(protocol.ProtocolError):
        parse_telemetry("T,1,2,3")


def test_valores_fuera_de_rango() -> None:
    with pytest.raises(protocol.ProtocolError):
        parse_telemetry("T,1,2,3,4,5,999,0,0,0")
    with pytest.raises(protocol.ProtocolError):
        parse_telemetry("T,1,2,3,-5,5,0,0,0,0")


def test_campos_vacios_se_rellenan_con_cero() -> None:
    telemetria = parse_telemetry("T,1,,,,,,,,,")
    assert telemetria is not None
    assert telemetria.altitude == 0.0
    assert telemetria.state == 0


def test_eventos_y_confirmaciones() -> None:
    assert parse_event("E,autogiro desplegado") == "autogiro desplegado"
    assert parse_event("OK,DEPLOY") == "OK,DEPLOY"
    assert parse_event("CMD,CAL,1") == "CMD,CAL,1"
    assert parse_event("T,1,2,3,4,5,0,0,0,0") is None


def test_nombres_de_estado() -> None:
    assert Telemetry(state=0).state_name == "PRE-LANZAMIENTO"
    assert Telemetry(state=1).state_name == "ASCENSO"
    assert Telemetry(state=2).state_name == "DESCENSO"
    assert Telemetry(state=3).state_name == "ATERRIZAJE"
    assert Telemetry(state=4).state_name == "FIN DE MISIÓN"
    assert Telemetry(state=9).state_name == "S9"


def test_formato_tiempo_de_mision() -> None:
    assert Telemetry(t=0).st == "00:00:00"
    assert Telemetry(t=3661).st == "01:01:01"


def test_cabecera_coincide_con_las_columnas() -> None:
    columnas = protocol.CSV_HEADER.split(",")
    valores = format_csv_row(Telemetry()).split(",")
    assert len(columnas) == len(valores)


def test_trama_con_rssi_y_snr_y_tolerancia_nan() -> None:
    trama_rf = TRAMA_COMPLETA + ",-72.5,8.2"
    telemetria = parse_telemetry(trama_rf)
    assert telemetria is not None
    assert telemetria.rssi == pytest.approx(-72.5)
    assert telemetria.snr == pytest.approx(8.2)

    # NaN e infinito se sanean sin romper el parseo
    trama_nan = "T,10.0,nan,22.0,1010.0,8.2,0,0,0,1,0,0,5,inf,0,-1,-1,nan,7.5"
    saneada = parse_telemetry(trama_nan)
    assert saneada is not None
    assert saneada.altitude == 0.0
    assert saneada.velocity == 0.0
    assert saneada.rssi is None
    assert saneada.snr == pytest.approx(7.5)


def test_grabacion_csv_y_jsonl(tmp_path) -> None:
    import json
    from gs.recording import CsvRecorder

    csv_path = tmp_path / "prueba.csv"
    rec = CsvRecorder()
    assert rec.start(str(csv_path)) is True
    rec.write(Telemetry(t=1.5, altitude=120.0, rssi=-68.0, snr=9.5))
    assert rec.stop() == 1

    jsonl_path = tmp_path / "prueba.jsonl"
    assert csv_path.exists()
    assert jsonl_path.exists()
    data = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    assert data["altitude_m"] == pytest.approx(120.0)
    assert data["rssi_dbm"] == pytest.approx(-68.0)
    assert data["snr_db"] == pytest.approx(9.5)
