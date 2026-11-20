#!/usr/bin/env python3
"""
analisis_vuelo.py — Análisis post-vuelo del CanSat.

Lee el CSV que graba la estación terrena (botón de grabación) y entrega:

  * tabla de fases y métricas por consola,
  * ``<nombre>_procesado.csv`` con altura y velocidad suavizadas,
  * ``<nombre>_resumen.json`` con todos los números del informe,
  * gráficas de altura, velocidad y actitud.

Formato esperado (el de ``gs/recording.py``)::

    mission_time_s,altitude_m,temperature_c,pressure_hpa,voltage_v,
    pitch_deg,roll_deg,yaw_deg,state,satellite,chute,packet

Uso::

    python tools/analisis_vuelo.py grabaciones/vuelo01.csv --masa 0.30
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

try:  # opcional: suavizado Savitzky-Golay
    from scipy.signal import savgol_filter
except Exception:  # pragma: no cover
    savgol_filter = None

G = 9.80665
ALT_DESPLEGUE_M = 200.0

#: Sinónimos aceptados por columna (para leer también logs de firmware).
ALIAS: dict[str, tuple[str, ...]] = {
    "t": ("mission_time_s", "t", "time_s"),
    "alt": ("altitude_m", "alt_m", "alt", "alt_f"),
    "temp": ("temperature_c", "temp_c", "temp"),
    "pres": ("pressure_hpa", "pres_pa", "pres"),
    "vol": ("voltage_v", "bateria_v", "vol"),
    "pitch": ("pitch_deg", "pitch"),
    "roll": ("roll_deg", "roll"),
    "yaw": ("yaw_deg", "yaw"),
    "state": ("state", "estado"),
    "sat": ("satellite", "sat"),
    "chute": ("chute", "autogiro"),
    "packet": ("packet", "sec"),
    "vel": ("velocity_ms", "vel_ms", "vel"),
    "acc": ("accel_ms2", "acc_ms2", "acc"),
    "sec_dist": ("secondary_distance_m", "sec_dist"),
    "sec_bear": ("secondary_bearing_deg", "sec_bear"),
}


@dataclass
class Segmento:
    """Tramo continuo de vuelo (un reinicio del CanSat abre un segmento)."""

    t: np.ndarray
    alt: np.ndarray
    temp: np.ndarray | None = None
    pres: np.ndarray | None = None
    vol: np.ndarray | None = None
    actitud: np.ndarray | None = None
    estado: np.ndarray | None = None
    sat: np.ndarray | None = None
    chute: np.ndarray | None = None
    vel: np.ndarray | None = None
    acc: np.ndarray | None = None
    sec_dist: np.ndarray | None = None
    sec_bear: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.t)


@dataclass
class Analisis:
    archivo: str
    masa_kg: float
    segmentos: list[Segmento] = field(default_factory=list)
    metricas: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
def _resolver_columnas(cabecera: list[str]) -> dict[str, str]:
    disponibles = {c.strip() for c in cabecera if c}
    mapa: dict[str, str] = {}
    for clave, alias in ALIAS.items():
        for nombre in alias:
            if nombre in disponibles:
                mapa[clave] = nombre
                break
    return mapa


def _leer_numeros(filas, columna: str | None) -> np.ndarray | None:
    if columna is None:
        return None
    valores = []
    for fila in filas:
        crudo = (fila.get(columna) or "").strip()
        try:
            valores.append(float(crudo))
        except ValueError:
            valores.append(math.nan)
    return np.array(valores, dtype=float)


def cargar(ruta: str) -> list[Segmento]:
    """Lee el CSV y devuelve segmentos de vuelo continuos."""
    with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
        lineas = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lineas) < 2:
        raise ValueError("el archivo no contiene datos suficientes")

    lector = csv.DictReader(lineas)
    filas = list(lector)
    if not filas:
        raise ValueError("el CSV no tiene filas de datos")

    columnas = _resolver_columnas(list(lector.fieldnames or []))
    faltantes = {"t", "alt"} - set(columnas)
    if faltantes:
        raise ValueError(
            f"faltan columnas obligatorias {sorted(faltantes)}; "
            f"cabecera: {lector.fieldnames}"
        )

    t = _leer_numeros(filas, columnas["t"])
    alt = _leer_numeros(filas, columnas["alt"])
    actitud = (
        np.column_stack(
            [
                _leer_numeros(filas, columnas.get("pitch")),
                _leer_numeros(filas, columnas.get("roll")),
                _leer_numeros(filas, columnas.get("yaw")),
            ]
        )
        if "pitch" in columnas and "roll" in columnas and "yaw" in columnas
        else None
    )

    cortes = [0]
    for i in range(1, len(t)):
        if math.isfinite(t[i]) and math.isfinite(t[i - 1]) and t[i] < t[i - 1] - 1.0:
            cortes.append(i)
    cortes.append(len(t))

    segmentos: list[Segmento] = []
    for a, b in zip(cortes[:-1], cortes[1:]):
        if b - a < 5:
            continue
        seg = Segmento(
            t=t[a:b],
            alt=alt[a:b],
            temp=_leer_numeros(filas, columnas.get("temp")),
            pres=_leer_numeros(filas, columnas.get("pres")),
            vol=_leer_numeros(filas, columnas.get("vol")),
            actitud=actitud,
            estado=_leer_numeros(filas, columnas.get("state")),
            sat=_leer_numeros(filas, columnas.get("sat")),
            chute=_leer_numeros(filas, columnas.get("chute")),
            vel=_leer_numeros(filas, columnas.get("vel")),
            acc=_leer_numeros(filas, columnas.get("acc")),
            sec_dist=_leer_numeros(filas, columnas.get("sec_dist")),
            sec_bear=_leer_numeros(filas, columnas.get("sec_bear")),
        )
        # recorta los arrays opcionales al segmento
        for nombre in ("temp", "pres", "vol", "estado", "sat", "chute",
                       "vel", "acc", "sec_dist", "sec_bear"):
            valor = getattr(seg, nombre)
            if valor is not None:
                setattr(seg, nombre, valor[a:b])
        if seg.actitud is not None:
            seg.actitud = seg.actitud[a:b]
        seg.t = seg.t - seg.t[0]
        segmentos.append(seg)
    return segmentos


def suavizar(seg: Segmento) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (altura suavizada, velocidad vertical) consistentes."""
    alt = seg.alt.astype(float).copy()
    malos = ~np.isfinite(alt)
    while malos.any():  # rellena huecos por interpolación
        idx = np.arange(len(alt))
        alt[malos] = np.interp(idx[malos], idx[~malos], alt[~malos])
        break

    dt = float(np.median(np.diff(seg.t))) if len(seg.t) > 2 else 0.1
    if savgol_filter is not None and len(alt) >= 21:
        ventana = min(31, len(alt) // 2 * 2 - 1)
        alt = savgol_filter(alt, ventana, 2)
    elif len(alt) >= 5:
        # media móvil simple como respaldo
        kernel = np.ones(5) / 5.0
        alt = np.convolve(alt, kernel, mode="same")

    vel = np.gradient(alt, dt)
    return alt, vel


def _primero(array: np.ndarray | None, condicion) -> int | None:
    if array is None:
        return None
    idx = np.where(condicion(array))[0]
    return int(idx[0]) if len(idx) else None


def resumir(seg: Segmento, masa_kg: float = 0.30) -> dict:
    """Calcula las métricas de un segmento de vuelo."""
    alt, vel = suavizar(seg)
    dt = float(np.median(np.diff(seg.t))) if len(seg.t) > 2 else 0.1
    info: dict = {
        "muestras": int(len(seg)),
        "dt_medio_s": round(dt, 4),
        "duracion_s": round(float(seg.t[-1]), 2),
        "altura_max_m": round(float(np.nanmax(alt)), 1),
        "t_apogeo_s": round(float(seg.t[int(np.argmax(alt))]), 2),
    }

    i_despegue = _primero(alt, lambda a: a > 15.0)
    if i_despegue is not None:
        info["t_despegue_s"] = round(float(seg.t[i_despegue]), 2)

    # Velocidad: se prefiere la que reporta el CanSat (columna vel); si el
    # registro es antiguo se usa la derivada suavizada de la altura.
    if seg.vel is not None and np.isfinite(seg.vel).any():
        vel_ref = seg.vel
    else:
        vel_ref = vel
    info["vel_max_descenso_ms"] = round(float(np.nanmin(vel_ref)), 2)

    # La velocidad de ascenso se mide solo en la fase de ascenso: el salto
    # de velocidad en el apogeo produce sobreoscilación al suavizar.
    if seg.estado is not None and len(seg.estado) == len(vel_ref):
        ascenso = vel_ref[seg.estado <= 1]
        if ascenso.size:
            info["vel_max_ascenso_ms"] = round(float(np.nanmax(ascenso)), 2)
        else:
            info["vel_max_ascenso_ms"] = round(float(np.nanmax(vel_ref)), 2)
    else:
        info["vel_max_ascenso_ms"] = round(float(np.nanmax(vel_ref)), 2)

    # Despliegue del autogiro: columna chute o satellite
    i_despliegue = _primero(seg.chute, lambda a: a >= 0.5)
    if i_despliegue is None:
        i_despliegue = _primero(seg.sat, lambda a: a >= 0.5)
    if i_despliegue is not None:
        info["t_despliegue_s"] = round(float(seg.t[i_despliegue]), 2)
        info["altura_despliegue_m"] = round(float(alt[i_despliegue]), 2)
        info["error_despliegue_m"] = round(
            float(alt[i_despliegue]) - ALT_DESPLEGUE_M, 2
        )

    # Aterrizaje
    i_aterrizaje = _primero(seg.estado, lambda a: a >= 3)
    # Instante físico de contacto: primera muestra que vuelve al suelo.
    i_contacto = None
    desde = i_despliegue if i_despliegue is not None else int(np.argmax(alt))
    idx_suelo = np.where(alt[desde:] <= 1.0)[0] if len(alt) > desde else []
    if len(idx_suelo):
        i_contacto = desde + int(idx_suelo[0])
    if i_aterrizaje is None:
        i_aterrizaje = i_contacto

    if i_aterrizaje is not None:
        info["t_aterrizaje_s"] = round(float(seg.t[i_aterrizaje]), 2)
        referencia = i_contacto if i_contacto is not None else i_aterrizaje
        inicio = max(0, referencia - max(1, int(1.0 / dt)))
        ventana = np.abs(vel_ref[inicio:referencia])
        ventana = ventana[ventana > 1e-3]
        v_impacto = (
            float(np.median(ventana))
            if ventana.size
            else abs(float(vel_ref[min(referencia, len(vel_ref) - 1)]))
        )
        info["vel_impacto_ms"] = round(v_impacto, 2)
        info["energia_impacto_j"] = round(0.5 * masa_kg * v_impacto**2, 2)
        info["transmision_post_aterrizaje_s"] = round(
            float(seg.t[-1] - seg.t[i_aterrizaje]), 1
        )

    if seg.temp is not None:
        info["temp_min_c"] = round(float(np.nanmin(seg.temp)), 1)
        info["temp_max_c"] = round(float(np.nanmax(seg.temp)), 1)
    if seg.pres is not None:
        info["pres_min_hpa"] = round(float(np.nanmin(seg.pres)), 2)
        info["pres_max_hpa"] = round(float(np.nanmax(seg.pres)), 2)
    if seg.vol is not None:
        info["voltaje_min_v"] = round(float(np.nanmin(seg.vol)), 2)
        info["voltaje_max_v"] = round(float(np.nanmax(seg.vol)), 2)
    if seg.actitud is not None:
        for i, eje in enumerate(("pitch", "roll", "yaw")):
            info[f"{eje}_rango_deg"] = [
                round(float(np.nanmin(seg.actitud[:, i])), 1),
                round(float(np.nanmax(seg.actitud[:, i])), 1),
            ]
    if seg.vel is not None and np.isfinite(seg.vel).any():
        info["vel_telemetria_max_ms"] = round(float(np.nanmax(seg.vel)), 2)
        info["vel_telemetria_min_ms"] = round(float(np.nanmin(seg.vel)), 2)
    if seg.acc is not None and np.isfinite(seg.acc).any():
        info["acc_max_ms2"] = round(float(np.nanmax(seg.acc)), 2)
        info["acc_min_ms2"] = round(float(np.nanmin(seg.acc)), 2)
    if seg.sec_dist is not None and np.isfinite(seg.sec_dist).any():
        validos = np.isfinite(seg.sec_dist) & (seg.sec_dist >= 0.0)
        if validos.any():
            info["sec_distancia_max_m"] = round(float(np.nanmax(seg.sec_dist[validos])), 1)
            info["sec_distancia_final_m"] = round(float(seg.sec_dist[validos][-1]), 1)
            if seg.sec_bear is not None:
                rumbos = seg.sec_bear[validos]
                rumbos = rumbos[np.isfinite(rumbos) & (rumbos >= 0.0)]
                if rumbos.size:
                    info["sec_rumbo_medio_deg"] = round(float(np.mean(rumbos)), 0)
    return info


# ---------------------------------------------------------------------------
def exportar_procesado(seg: Segmento, ruta: str) -> None:
    alt, vel = suavizar(seg)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "alt_m", "vel_ms"])
        for i in range(len(seg.t)):
            w.writerow([f"{seg.t[i]:.3f}", f"{alt[i]:.2f}", f"{vel[i]:.3f}"])


def graficar(seg: Segmento, prefijo: str) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        print(f"[aviso] matplotlib no disponible: {exc}")
        return []

    alt, vel = suavizar(seg)
    salidas: list[str] = []

    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(seg.t, alt, lw=1.7, color="#00a8cc", label="altura")
    ax.axhline(ALT_DESPLEGUE_M, ls="--", lw=1, color="#d9480f",
               label=f"despliegue {ALT_DESPLEGUE_M:.0f} m")
    ax.set_xlabel("tiempo de misión (s)")
    ax.set_ylabel("altura (m)")
    ax.set_title("CanSat · perfil de altura")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    ruta = f"{prefijo}_altura.png"
    fig.savefig(ruta, dpi=140)
    plt.close(fig)
    salidas.append(ruta)

    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(seg.t, vel, lw=1.7, color="#2f9e44")
    ax.axhline(0, ls=":", lw=1, color="gray")
    ax.set_xlabel("tiempo de misión (s)")
    ax.set_ylabel("velocidad vertical (m/s)")
    ax.set_title("CanSat · velocidad vertical")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    ruta = f"{prefijo}_velocidad.png"
    fig.savefig(ruta, dpi=140)
    plt.close(fig)
    salidas.append(ruta)

    if seg.actitud is not None:
        fig, ax = plt.subplots(figsize=(9, 4.4))
        for i, eje in enumerate(("pitch", "roll", "yaw")):
            ax.plot(seg.t, seg.actitud[:, i], lw=1.1, label=eje)
        ax.set_xlabel("tiempo de misión (s)")
        ax.set_ylabel("ángulo (°)")
        ax.set_title("CanSat · actitud")
        ax.grid(alpha=0.3)
        ax.legend(ncol=3)
        fig.tight_layout()
        ruta = f"{prefijo}_actitud.png"
        fig.savefig(ruta, dpi=140)
        plt.close(fig)
        salidas.append(ruta)

    return salidas


def analizar(ruta: str, masa_kg: float = 0.30) -> Analisis:
    """Carga y resume un CSV completo (una o varias sesiones)."""
    segmentos = cargar(ruta)
    resultado = Analisis(archivo=os.path.abspath(ruta), masa_kg=masa_kg)
    resultado.segmentos = segmentos
    for i, seg in enumerate(segmentos, start=1):
        resultado.metricas[f"segmento_{i}"] = resumir(seg, masa_kg)
    return resultado


def main() -> int:
    ap = argparse.ArgumentParser(description="Análisis de vuelo CanSat")
    ap.add_argument("archivo", help="CSV grabado por la estación terrena")
    ap.add_argument("--masa", type=float, default=0.30,
                    help="masa de la etapa primaria en kg (def. 0.30)")
    ap.add_argument("--sin-graficas", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.archivo):
        print(f"No existe: {args.archivo}")
        return 1

    analisis = analizar(args.archivo, args.masa)
    base = os.path.splitext(args.archivo)[0]
    print(f"\n=== CanSat · análisis de {os.path.basename(args.archivo)} ===")
    print(f"Segmentos: {len(analisis.segmentos)}   masa: {args.masa:.2f} kg")

    for nombre, metricas in analisis.metricas.items():
        print(f"\n--- {nombre} ---")
        for clave, valor in metricas.items():
            print(f"  {clave:34s} {valor}")

    if analisis.segmentos:
        principal = max(analisis.segmentos, key=len)
        exportar_procesado(principal, f"{base}_procesado.csv")
        print(f"\nProcesado -> {base}_procesado.csv")
        if not args.sin_graficas:
            for ruta in graficar(principal, base):
                print(f"Gráfica   -> {ruta}")

    with open(f"{base}_resumen.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "archivo": analisis.archivo,
                "masa_kg": analisis.masa_kg,
                "metricas": analisis.metricas,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"Resumen   -> {base}_resumen.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
