#!/usr/bin/env python3
"""Reproduce un CSV de vuelo como si fuese telemetría en vivo.

Dos modos:

* **consola** (por defecto): imprime las tramas ``T,...`` por ``stdout``.
  Útil para comprobar el formato o para redirigir a un archivo.
* **puerto serie** (``--puerto``): escribe las tramas por un puerto COM/TTY
  a la cadencia original del registro. Con un par de puertos virtuales
  (com0com en Windows, socat en Linux) se puede inyectar un vuelo completo
  en la estación terrestre sin repetirlo en bucle.

Uso::

    python tools/replay.py grabaciones/vuelo_sintetico.csv --rapido
    python tools/replay.py grabaciones/vuelo01.csv --puerto COM7 --baud 115200

En Linux, un puerto virtual de pruebas::

    socat -d -d pty,raw,echo=0 pty,raw,echo=0
    python tools/replay.py vuelo.csv --puerto /dev/pts/5
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gs.protocol import CSV_HEADER, Telemetry, format_csv_row  # noqa: E402


def _fila_a_telemetria(fila: dict) -> Telemetry:
    """Acepta tanto el CSV de la estación como el del firmware."""
    def num(*nombres: str, defecto: float = 0.0) -> float:
        for nombre in nombres:
            if nombre in fila and fila[nombre] not in ("", None):
                try:
                    return float(fila[nombre])
                except ValueError:
                    continue
        return defecto

    return Telemetry(
        t=num("mission_time_s", "t", "time_s"),
        altitude=num("altitude_m", "alt_m", "alt"),
        temperature=num("temperature_c", "temp_c", "temp"),
        pressure=num("pressure_hpa", "pres_pa", "pres"),
        voltage=num("voltage_v", "bateria_v", "vol"),
        pitch=num("pitch_deg", "pitch"),
        roll=num("roll_deg", "roll"),
        yaw=num("yaw_deg", "yaw"),
        state=int(num("state", "estado")),
        satellite=int(num("satellite", "sat")),
        chute=int(num("chute", "autogiro")),
        packet=int(num("packet", "sec")),
        velocity=num("velocity_ms", "vel_ms", "vel"),
        accel=num("accel_ms2", "acc_ms2", "acc"),
        sec_distance=num("secondary_distance_m", "sec_dist", defecto=-1.0),
        sec_bearing=num("secondary_bearing_deg", "sec_bear", defecto=-1.0),
    )


def cargar(ruta: str) -> list[Telemetry]:
    with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
        lector = csv.DictReader(f)
        if not lector.fieldnames or "mission_time_s" not in lector.fieldnames:
            # CSV sin cabecera conocida: se intenta el orden canónico
            f.seek(0)
            filas = [ln.strip() for ln in f if ln.strip()]
            columnas = [c.strip() for c in CSV_HEADER.split(",")]
            lector = csv.DictReader(filas, fieldnames=columnas)
        return [_fila_a_telemetria(fila) for fila in lector]


def reproducir(paquetes: list[Telemetry], puerto: str | None, baud: int,
               rapido: bool, bucle: bool) -> int:
    salida = None
    if puerto:
        try:
            import serial  # type: ignore
        except Exception:
            print("pyserial no está instalado: pip install pyserial", file=sys.stderr)
            return 2
        salida = serial.Serial(puerto, baud, timeout=1)
        print(f"Reproduciendo {len(paquetes)} paquetes en {puerto} @ {baud}…")

    enviados = 0
    try:
        while True:
            t_anterior = paquetes[0].t
            inicio = time.monotonic()
            for paquete in paquetes:
                if not rapido:
                    retardo = (paquete.t - t_anterior) - (time.monotonic() - inicio)
                    if retardo > 0:
                        time.sleep(retardo)
                trama = ("T," + format_csv_row(paquete) + "\r\n").encode("ascii", "ignore")
                if salida is not None:
                    salida.write(trama)
                else:
                    sys.stdout.write(trama.decode("ascii"))
                    sys.stdout.flush()
                enviados += 1
            if not bucle:
                break
            # En bucle se reinicia el reloj para que la estación vea un
            # vuelo nuevo (t vuelve a 0 y la misión se reconoce de nuevo).
    except KeyboardInterrupt:
        pass
    finally:
        if salida is not None:
            salida.close()
    print(f"\n{enviados} tramas reproducidas.", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Reproducir un vuelo grabado")
    ap.add_argument("archivo", help="CSV de vuelo")
    ap.add_argument("--puerto", help="puerto serie de salida (def. stdout)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--rapido", action="store_true",
                    help="no respeta los tiempos del registro")
    ap.add_argument("--bucle", action="store_true", help="repetir indefinidamente")
    args = ap.parse_args()

    if not os.path.exists(args.archivo):
        print(f"No existe: {args.archivo}", file=sys.stderr)
        return 1
    paquetes = cargar(args.archivo)
    if not paquetes:
        print("El archivo no contiene tramas.", file=sys.stderr)
        return 1
    return reproducir(paquetes, args.puerto, args.baud, args.rapido, args.bucle)


if __name__ == "__main__":
    sys.exit(main())
