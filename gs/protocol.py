"""Protocolo de telemetría CanSat.

Formato de trama de telemetría (CSV, terminada por ``\\r`` o ``\\n``)::

    T,t,alt,temp,pres,vol,pitch,roll,yaw,state,sat,chute,packet,vel,acc,sec_dist,sec_bear

Las cuatro últimas columnas son **opcionales**: los firmware antiguos (13
campos) siguen siendo válidos y se rellenan con 0 / -1. Así la estación es
retrocompatible y a la vez recibe lo que exige la misión.

Ejemplo real::

    T,125.40,1042.6,22.8,891.4,8.61,3.1,-2.4,179.8,2,1,1,1254,-4.70,0.12,38.5,247.0

Convenciones:
  * ``t``        segundos de misión (ST)
  * ``alt``      altitud sobre el punto de suelta, en metros
  * ``temp``     temperatura en °C
  * ``pres``     presión en hPa
  * ``vol``      tensión de batería en V
  * ``pitch``    cabeceo en grados (+ arriba)
  * ``roll``     alabeo en grados (+ derecha)
  * ``yaw``      guiñada en grados
  * ``state``    estado de la misión (0 = pre-lanzamiento, 1 = ascenso,
                 2 = descenso, 3 = aterrizaje, 4 = fin)
  * ``sat``      etapa secundaria liberada (1 = sí)
  * ``chute``    autogiro desplegado (1 = sí)
  * ``packet``   contador de paquetes
  * ``vel``      velocidad vertical en m/s (+ arriba)
  * ``acc``      aceleración vertical en m/s² (+ arriba)
  * ``sec_dist`` distancia horizontal a la carga secundaria en m (-1 = sin dato)
  * ``sec_bear`` rumbo hacia la carga secundaria en grados (-1 = sin dato)

Tramas de estado/respuesta aceptadas y mostradas en consola:
  ``E,<texto>``  -> aviso/error del CanSat
  ``OK,...`` / ``CMD,...`` -> confirmaciones
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

TELEMETRY_PREFIX = "T"
EVENT_PREFIX = "E"

#: Comandos hacia el CanSat (tramas de cable del firmware).
CMD_CALIBRATE = "C,CAL,1"
CMD_TEST_SERVO = "C,SERVO,TEST"
CMD_INJECTION = "C,INJ,1"          # reservado: sin efecto en esta misión
CMD_DEPLOY_PARENT = "C,DEP,DEPLOY"
CMD_CUT_PARACHUTE = "C,CHUTE,CUT"
CMD_RECOVER = "C,SYS,RESET"

#: Comandos expuestos como botones en el panel de control.
COMMANDS: dict = {
    "Calibrar barómetro": CMD_CALIBRATE,
    "Probar servo (GPIO 5)": CMD_TEST_SERVO,
    "Desplegar autogiro": CMD_DEPLOY_PARENT,
    "Abortar despliegue": CMD_CUT_PARACHUTE,
    "Reiniciar misión": CMD_RECOVER,
}

BAUDRATES = [9600, 19200, 38400, 57600, 74880, 115200, 230400, 460800, 921600]


@dataclass
class Telemetry:
    """Paquete de telemetría ya normalizado."""

    t: float = 0.0
    altitude: float = 0.0
    temperature: float = 0.0
    pressure: float = 0.0
    voltage: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    yaw: float = 0.0
    state: int = 0
    satellite: int = 0
    chute: int = 0
    packet: int = 0
    velocity: float = 0.0
    accel: float = 0.0
    sec_distance: float = -1.0
    sec_bearing: float = -1.0
    rssi: Optional[float] = None
    snr: Optional[float] = None
    received_at: float = field(default_factory=time.time)

    @property
    def st(self) -> str:
        """Tiempo de misión formateado HH:MM:SS."""
        total = int(self.t)
        sign = "-" if total < 0 else ""
        total = abs(total)
        return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"

    @property
    def state_name(self) -> str:
        return {0: "PRE-LANZAMIENTO", 1: "ASCENSO", 2: "DESCENSO",
                3: "ATERRIZAJE", 4: "FIN DE MISIÓN"}.get(self.state, f"S{self.state}")

    @property
    def secondary_known(self) -> bool:
        """``True`` si se conoce al menos la distancia a la carga secundaria."""
        return self.sec_distance >= 0.0

    @property
    def sink_rate(self) -> float:
        """Régimen de descenso en m/s (positivo hacia abajo)."""
        return -self.velocity


class ProtocolError(ValueError):
    """Trama recibida que no cumple el protocolo."""


def _to_float(value: str, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"campo '{field_name}' no numérico: {value!r}") from exc


def parse_telemetry(line: str) -> Optional[Telemetry]:
    """Convierte una línea de telemetría en :class:`Telemetry`.

    Devuelve ``None`` si la línea no es una trama de telemetría válida
    (mensaje de estado o línea corrupta), para que el llamante pueda
    registrarla sin abortar el flujo.
    """
    if not line:
        return None

    frame = line.strip()
    if not frame:
        return None

    if not frame.startswith(TELEMETRY_PREFIX + ",") and frame != TELEMETRY_PREFIX:
        return None

    fields = frame.split(",")[1:]
    if len(fields) < 9:
        raise ProtocolError(f"trama incompleta ({len(fields)} campos): {frame!r}")

    def num(index: int, name: str, default: float = 0.0) -> float:
        if index >= len(fields) or fields[index].strip() == "":
            return default
        val = _to_float(fields[index], name)
        return val if math.isfinite(val) else default

    def opt_num(index: int, name: str) -> Optional[float]:
        if index >= len(fields) or fields[index].strip() == "":
            return None
        val = _to_float(fields[index], name)
        return val if math.isfinite(val) else None

    telemetry = Telemetry(
        t=num(0, "t"),
        altitude=num(1, "alt"),
        temperature=num(2, "temp"),
        pressure=num(3, "pres"),
        voltage=num(4, "vol"),
        pitch=num(5, "pitch"),
        roll=num(6, "roll"),
        yaw=num(7, "yaw"),
        state=int(num(8, "state")),
        satellite=int(num(9, "sat", 0)),
        chute=int(num(10, "chute", 0)),
        packet=int(num(11, "packet", 0)),
        velocity=num(12, "vel", 0.0),
        accel=num(13, "acc", 0.0),
        sec_distance=num(14, "sec_dist", -1.0),
        sec_bearing=num(15, "sec_bear", -1.0),
        rssi=opt_num(16, "rssi"),
        snr=opt_num(17, "snr"),
    )

    for name in ("pitch", "roll", "yaw"):
        value = getattr(telemetry, name)
        if value < -360.0 or value > 360.0:
            raise ProtocolError(f"ángulo '{name}' fuera de rango: {value}")

    if telemetry.pressure < 0.0:
        raise ProtocolError(f"presión negativa: {telemetry.pressure}")

    return telemetry


def parse_event(line: str) -> Optional[str]:
    """Devuelve el texto de una trama de estado ``E,<texto>`` o ``None``."""
    frame = (line or "").strip()
    if not frame:
        return None
    if frame.startswith(EVENT_PREFIX + ","):
        return frame.split(",", 1)[1].strip() or "evento"
    if frame.startswith(("OK", "CMD", "ACK")):
        return frame
    return None


def format_csv_row(telemetry: Telemetry) -> str:
    """Serializa un paquete para el fichero CSV de grabación."""
    return ",".join([
        f"{telemetry.t:.2f}",
        f"{telemetry.altitude:.2f}",
        f"{telemetry.temperature:.2f}",
        f"{telemetry.pressure:.2f}",
        f"{telemetry.voltage:.3f}",
        f"{telemetry.pitch:.2f}",
        f"{telemetry.roll:.2f}",
        f"{telemetry.yaw:.2f}",
        str(telemetry.state),
        str(telemetry.satellite),
        str(telemetry.chute),
        str(telemetry.packet),
        f"{telemetry.velocity:.2f}",
        f"{telemetry.accel:.2f}",
        f"{telemetry.sec_distance:.1f}",
        f"{telemetry.sec_bearing:.1f}",
        "" if telemetry.rssi is None else f"{telemetry.rssi:.1f}",
        "" if telemetry.snr is None else f"{telemetry.snr:.1f}",
    ])


def telemetry_to_dict(telemetry: Telemetry) -> dict:
    """Serializa un paquete a diccionario listo para JSONL."""
    return {
        "mission_time_s": round(telemetry.t, 2),
        "altitude_m": round(telemetry.altitude, 2),
        "temperature_c": round(telemetry.temperature, 2),
        "pressure_hpa": round(telemetry.pressure, 2),
        "voltage_v": round(telemetry.voltage, 3),
        "pitch_deg": round(telemetry.pitch, 2),
        "roll_deg": round(telemetry.roll, 2),
        "yaw_deg": round(telemetry.yaw, 2),
        "state": telemetry.state,
        "satellite": telemetry.satellite,
        "chute": telemetry.chute,
        "packet": telemetry.packet,
        "velocity_ms": round(telemetry.velocity, 2),
        "accel_ms2": round(telemetry.accel, 2),
        "secondary_distance_m": round(telemetry.sec_distance, 1),
        "secondary_bearing_deg": round(telemetry.sec_bearing, 1),
        "rssi_dbm": None if telemetry.rssi is None else round(telemetry.rssi, 1),
        "snr_db": None if telemetry.snr is None else round(telemetry.snr, 1),
        "received_at": round(telemetry.received_at, 3),
    }


CSV_HEADER = (
    "mission_time_s,altitude_m,temperature_c,pressure_hpa,voltage_v,"
    "pitch_deg,roll_deg,yaw_deg,state,satellite,chute,packet,"
    "velocity_ms,accel_ms2,secondary_distance_m,secondary_bearing_deg,"
    "rssi_dbm,snr_db"
)