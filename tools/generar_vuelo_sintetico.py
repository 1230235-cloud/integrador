#!/usr/bin/env python3
"""Genera un vuelo sintético en el formato CSV de la estación terrena.

Sirve para tres cosas:

* probar :mod:`tools.analisis_vuelo` sin haber volado,
* alimentar la estación con un archivo reproducible,
* disponer de una referencia numérica de la misión (450 m → 200 m → suelo).

Uso::

    python tools/generar_vuelo_sintetico.py
    python tools/generar_vuelo_sintetico.py --salida grabaciones/vuelo.csv --hz 10
    python tools/generar_vuelo_sintetico.py --ruido 0.4     # telemetría realista
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gs.flight_profile import FlightProfile  # noqa: E402
from gs.protocol import CSV_HEADER, format_csv_row  # noqa: E402


def generar(salida: str, hz: float = 10.0, ruido: float = 0.0,
            semilla: int = 7) -> dict:
    """Escribe el CSV y devuelve un resumen del perfil generado."""
    perfil = FlightProfile()
    rng = random.Random(semilla)
    dt = 1.0 / max(hz, 1.0)

    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    with open(salida, "w", encoding="utf-8", newline="") as f:
        f.write(CSV_HEADER + "\n")
        t = 0.0
        paquete = 0
        while t <= perfil.t_fin:
            muestra = perfil.sample(t)
            paquete += 1
            muestra.packet = paquete
            if ruido > 0.0:
                muestra.altitude += rng.gauss(0.0, ruido * 0.6)
                muestra.velocity += rng.gauss(0.0, ruido * 0.15)
                muestra.accel += rng.gauss(0.0, ruido * 0.4)
                muestra.temperature += rng.gauss(0.0, ruido * 0.05)
                muestra.pressure += rng.gauss(0.0, ruido * 0.08)
                muestra.voltage += rng.gauss(0.0, ruido * 0.005)
                muestra.altitude = max(muestra.altitude, 0.0)
            f.write(format_csv_row(muestra) + "\n")
            t += dt

    return {
        "archivo": os.path.abspath(salida),
        "muestras": paquete,
        "duracion_s": round(perfil.t_fin, 1),
        "t_despliegue_s": round(perfil.t_despliegue, 2),
        "t_aterrizaje_s": round(perfil.t_aterrizaje, 2),
        "t_aterrizaje_secundaria_s": round(perfil.t_aterrizaje_secundaria, 2),
        "altura_max_m": round(perfil.config.alt_suelta, 1),
        "distancia_secundaria_m": round(perfil.distancia_secundaria(perfil.t_fin), 1),
        "rumbo_secundaria_deg": round(perfil.rumbo_secundaria(perfil.t_fin), 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Vuelo sintético CanSat → CSV")
    ap.add_argument("--salida", default=os.path.join("grabaciones", "vuelo_sintetico.csv"),
                    help="ruta del CSV a escribir (def. grabaciones/vuelo_sintetico.csv)")
    ap.add_argument("--hz", type=float, default=10.0,
                    help="frecuencia de muestreo en Hz (def. 10)")
    ap.add_argument("--ruido", type=float, default=0.0,
                    help="desviación del ruido de sensores (0 = ideal)")
    ap.add_argument("--semilla", type=int, default=7, help="semilla del ruido")
    args = ap.parse_args()

    resumen = generar(args.salida, args.hz, args.ruido, args.semilla)
    print(f"Vuelo sintético → {resumen['archivo']}")
    for clave, valor in resumen.items():
        if clave != "archivo":
            print(f"  {clave:28s} {valor}")

    # Verificación de cordura: la física del perfil debe ser coherente.
    perfil = FlightProfile()
    if not math.isclose(perfil.altitud(perfil.t_despliegue), 200.0, abs_tol=1e-6):
        print("[error] el perfil no alcanza exactamente 200 m en el despliegue")
        return 2
    if perfil.altitud(perfil.t_aterrizaje) > 1e-6:
        print("[error] la altura no llega a cero al aterrizar")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
