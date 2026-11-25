#!/usr/bin/env python3
"""generar_reporte.py — Generador de reportes HTML y PDF con gráficas de vuelo.

Lee el paquete ``<vuelo>.report.json`` (o un ``.csv`` grabado por la estación
terrestre) y genera automáticamente:
  * ``<vuelo>_reporte.html`` — Informe autocontenido con insignia, tabla KPI y 5 gráficas.
  * ``<vuelo>_reporte.pdf``  — Reporte listo para anexar al documento RAM.

Uso:
    python3 tools/generar_reporte.py grabaciones/vuelo01.report.json
    python3 tools/generar_reporte.py grabaciones/vuelo01.csv
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import sys
import time
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

DEPLOY_TARGET_M = 25.5
DEFAULT_LOGO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "insignia-pepe-el-pollo.png",
)


def _to_float(val: Any, default: float | None = 0.0) -> float | None:
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def load_flight_data(path: str) -> dict[str, Any]:
    """Carga un paquete ``.report.json`` o construye la misma estructura desde CSV."""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    # Respaldo: leer directamente un CSV de gs/recording.py
    samples: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            samples.append({
                "mission_time_s": _to_float(row.get("mission_time_s") or row.get("t"), 0.0),
                "altitude_m": _to_float(row.get("altitude_m") or row.get("alt"), 0.0),
                "velocity_ms": _to_float(row.get("velocity_ms") or row.get("vel"), 0.0),
                "accel_ms2": _to_float(row.get("accel_ms2") or row.get("acc"), 0.0),
                "temperature_c": _to_float(row.get("temperature_c") or row.get("temp"), 0.0),
                "pressure_hpa": _to_float(row.get("pressure_hpa") or row.get("pres"), 0.0),
                "voltage_v": _to_float(row.get("voltage_v") or row.get("vol"), 0.0),
                "pitch_deg": _to_float(row.get("pitch_deg") or row.get("pitch"), 0.0),
                "roll_deg": _to_float(row.get("roll_deg") or row.get("roll"), 0.0),
                "yaw_deg": _to_float(row.get("yaw_deg") or row.get("yaw"), 0.0),
                "state": int(_to_float(row.get("state"), 0.0) or 0),
                "chute": int(_to_float(row.get("chute"), 0.0) or 0),
                "rssi_dbm": _to_float(row.get("rssi_dbm") or row.get("rssi"), None),
                "snr_db": _to_float(row.get("snr_db") or row.get("snr"), None),
            })

    if not samples:
        raise ValueError(f"El archivo {path} no contiene muestras válidas.")

    alts = [s["altitude_m"] for s in samples]
    vels = [s["velocity_ms"] for s in samples]
    temps = [s["temperature_c"] for s in samples]
    press = [s["pressure_hpa"] for s in samples]
    volts = [s["voltage_v"] for s in samples]
    rssis = [s["rssi_dbm"] for s in samples if s["rssi_dbm"] is not None]
    deploy = next((s for s in samples if s["chute"] == 1), None)

    return {
        "schema_version": "1.0",
        "metadata": {
            "team": "Pepe el Pollo",
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source_csv": os.path.basename(path),
            "total_samples": len(samples),
            "duration_s": round(samples[-1]["mission_time_s"] - samples[0]["mission_time_s"], 2),
        },
        "summary": {
            "max_altitude_m": round(max(alts), 2),
            "max_ascent_rate_ms": round(max(vels), 2),
            "max_descent_rate_ms": round(abs(min(vels)), 2),
            "deploy_altitude_m": deploy["altitude_m"] if deploy else None,
            "min_temperature_c": round(min(temps), 2),
            "max_temperature_c": round(max(temps), 2),
            "min_pressure_hpa": round(min(press), 2),
            "max_pressure_hpa": round(max(press), 2),
            "min_voltage_v": round(min(volts), 3),
            "avg_rssi_dbm": round(sum(rssis) / len(rssis), 1) if rssis else None,
        },
        "series": {
            "t": [s["mission_time_s"] for s in samples],
            "altitude_m": alts,
            "velocity_ms": vels,
            "accel_ms2": [s["accel_ms2"] for s in samples],
            "temperature_c": temps,
            "pressure_hpa": press,
            "voltage_v": volts,
            "pitch_deg": [s["pitch_deg"] for s in samples],
            "roll_deg": [s["roll_deg"] for s in samples],
            "yaw_deg": [s["yaw_deg"] for s in samples],
            "state": [s["state"] for s in samples],
            "chute": [s["chute"] for s in samples],
            "rssi_dbm": [s["rssi_dbm"] for s in samples],
            "snr_db": [s["snr_db"] for s in samples],
        },
    }


def _style_axis(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.35)


def build_figures(data: dict[str, Any]) -> list[tuple[str, plt.Figure]]:
    """Genera las 5 figuras de telemetría del vuelo."""
    s = data["series"]
    t = s["t"]
    alt = s["altitude_m"]
    vel = s["velocity_ms"]
    acc = s["accel_ms2"]
    temp = s["temperature_c"]
    pres = s["pressure_hpa"]
    vol = s["voltage_v"]
    chute = s["chute"]

    figs: list[tuple[str, plt.Figure]] = []

    # 1. Altitud vs tiempo
    fig1, ax1 = plt.subplots(figsize=(9.5, 4.2), dpi=180)
    ax1.plot(t, alt, color="#0284c7", linewidth=2.0, label="Altitud (m)")
    ax1.axhline(DEPLOY_TARGET_M, color="#d97706", linestyle="--", linewidth=1.3,
                label=f"Objetivo despliegue ({DEPLOY_TARGET_M:.0f} m)")
    if alt:
        idx_max = alt.index(max(alt))
        ax1.scatter([t[idx_max]], [alt[idx_max]], color="#16a34a", zorder=5,
                    label=f"Apogeo: {alt[idx_max]:.1f} m ({t[idx_max]:.1f} s)")
    dep_idx = next((i for i, c in enumerate(chute) if c == 1), None)
    if dep_idx is not None:
        ax1.scatter([t[dep_idx]], [alt[dep_idx]], color="#dc2626", marker="D", zorder=6,
                    label=f"Despliegue: {alt[dep_idx]:.1f} m ({t[dep_idx]:.1f} s)")
    _style_axis(ax1, "Perfil de Altitud vs Tiempo", "Tiempo de misión (s)", "Altitud (m)")
    ax1.legend(loc="best", fontsize=8)
    fig1.tight_layout()
    figs.append(("Perfil de Altitud", fig1))

    # 2. Velocidad vertical y aceleración
    fig2, ax2 = plt.subplots(figsize=(9.5, 4.2), dpi=180)
    ax2.plot(t, vel, color="#16a34a", linewidth=1.8, label="Velocidad vertical (m/s)")
    ax2.axhspan(-12.0, -8.0, color="#22c55e", alpha=0.12, label="Banda descenso 8–12 m/s")
    ax2b = ax2.twinx()
    ax2b.plot(t, acc, color="#ea580c", linewidth=1.3, alpha=0.85, label="Aceleración vertical (m/s²)")
    ax2b.set_ylabel("Aceleración (m/s²)", fontsize=9, color="#ea580c")
    _style_axis(ax2, "Velocidad Vertical y Aceleración", "Tiempo de misión (s)", "Velocidad (m/s)")
    lines_a, labels_a = ax2.get_legend_handles_labels()
    lines_b, labels_b = ax2b.get_legend_handles_labels()
    ax2.legend(lines_a + lines_b, labels_a + labels_b, loc="best", fontsize=8)
    fig2.tight_layout()
    figs.append(("Velocidad y Aceleración", fig2))

    # 3. Temperatura y presión
    fig3, ax3 = plt.subplots(figsize=(9.5, 4.2), dpi=180)
    ax3.plot(t, temp, color="#dc2626", linewidth=1.8, label="Temperatura (°C)")
    ax3b = ax3.twinx()
    ax3b.plot(t, pres, color="#7c3aed", linewidth=1.8, label="Presión (hPa)")
    ax3b.set_ylabel("Presión atmosférica (hPa)", fontsize=9, color="#7c3aed")
    _style_axis(ax3, "Temperatura y Presión Atmosférica", "Tiempo de misión (s)", "Temperatura (°C)")
    la, lba = ax3.get_legend_handles_labels()
    lb, lbb = ax3b.get_legend_handles_labels()
    ax3.legend(la + lb, lba + lbb, loc="best", fontsize=8)
    fig3.tight_layout()
    figs.append(("Temperatura y Presión", fig3))

    # 4. Actitud (Pitch / Roll / Yaw)
    fig4, ax4 = plt.subplots(figsize=(9.5, 4.2), dpi=180)
    ax4.plot(t, s["pitch_deg"], color="#0284c7", linewidth=1.5, label="Pitch (°)")
    ax4.plot(t, s["roll_deg"], color="#16a34a", linewidth=1.5, label="Roll (°)")
    ax4.plot(t, s["yaw_deg"], color="#d97706", linewidth=1.3, alpha=0.8, label="Yaw (°)")
    _style_axis(ax4, "Orientación del CanSat (IMU)", "Tiempo de misión (s)", "Ángulo (°)")
    ax4.legend(loc="best", fontsize=8)
    fig4.tight_layout()
    figs.append(("Orientación (Pitch / Roll / Yaw)", fig4))

    # 5. Batería y calidad de enlace RF
    fig5, ax5 = plt.subplots(figsize=(9.5, 4.2), dpi=180)
    ax5.plot(t, vol, color="#ca8a04", linewidth=1.8, label="Batería (V)")
    ax5.axhline(6.8, color="#dc2626", linestyle=":", linewidth=1.2, label="Umbral alerta (6.8 V)")
    rssi_pts = [(ti, r) for ti, r in zip(t, s.get("rssi_dbm", [])) if r is not None]
    if rssi_pts:
        ax5b = ax5.twinx()
        ax5b.plot([p[0] for p in rssi_pts], [p[1] for p in rssi_pts],
                  color="#0ea5e9", linewidth=1.4, alpha=0.85, label="RSSI (dBm)")
        ax5b.set_ylabel("RSSI (dBm)", fontsize=9, color="#0ea5e9")
        la, lba = ax5.get_legend_handles_labels()
        lb, lbb = ax5b.get_legend_handles_labels()
        ax5.legend(la + lb, lba + lbb, loc="best", fontsize=8)
    else:
        ax5.legend(loc="best", fontsize=8)
    _style_axis(ax5, "Batería y Enlace LoRa (RSSI)", "Tiempo de misión (s)", "Voltaje (V)")
    fig5.tight_layout()
    figs.append(("Batería y Enlace RF", fig5))

    return figs


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def write_html_report(out_html: str, data: dict[str, Any],
                      figs: list[tuple[str, plt.Figure]], logo_path: str) -> None:
    meta = data["metadata"]
    sm = data["summary"]
    dep = sm.get("deploy_altitude_m")
    dep_txt = f"{dep:.1f} m (error {dep - DEPLOY_TARGET_M:+.1f} m)" if dep is not None else "No registrado"
    rssi_txt = f"{sm['avg_rssi_dbm']:.1f} dBm" if sm.get("avg_rssi_dbm") is not None else "N/D"

    logo_html = ""
    if os.path.exists(logo_path):
        b64_logo = base64.b64encode(open(logo_path, "rb").read()).decode("ascii")
        logo_html = f'<img src="data:image/png;base64,{b64_logo}" alt="Insignia" class="logo">'

    charts_html = "\n".join(
        f'<section class="chart"><h2>{title}</h2>'
        f'<img src="data:image/png;base64,{_fig_to_b64(fig)}" alt="{title}"></section>'
        for title, fig in figs
    )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Reporte de Vuelo CanSat · {meta.get('team', 'Pepe el Pollo')}</title>
<style>
  body{{font-family:system-ui,-apple-system,sans-serif;background:#f8fafc;color:#0f172a;margin:0;padding:24px}}
  .wrap{{max-width:1020px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:28px}}
  header{{display:flex;align-items:center;gap:18px;border-bottom:2px solid #0f172a;padding-bottom:16px;margin-bottom:20px}}
  .logo{{width:84px;height:84px;object-fit:contain;border-radius:10px}}
  h1{{margin:0;font-size:22px}}
  .meta{{color:#475569;font-size:13px;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;margin:16px 0 24px;font-size:14px}}
  th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid #e2e8f0}}
  th{{background:#f1f5f9;color:#334155;font-weight:600}}
  .chart{{margin-bottom:24px;page-break-inside:avoid}}
  .chart h2{{font-size:15px;color:#1e293b;margin:0 0 8px}}
  .chart img{{width:100%;border:1px solid #e2e8f0;border-radius:8px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    {logo_html}
    <div>
      <h1>Reporte de Resultados y Análisis de Misión (RAM) · CanSat</h1>
      <div class="meta">Equipo: <strong>{meta.get('team', 'Pepe el Pollo')}</strong> ·
      Fuente: <code>{meta.get('source_csv', '')}</code> ·
      Muestras: {meta.get('total_samples', 0)} · Duración: {meta.get('duration_s', 0)} s</div>
    </div>
  </header>

  <table>
    <tr><th>Métrica de Misión</th><th>Valor Registrado</th><th>Métrica de Misión</th><th>Valor Registrado</th></tr>
    <tr><td>Altura máxima (apogeo)</td><td><strong>{sm.get('max_altitude_m', 0):.2f} m</strong></td>
        <td>Despliegue de autogiro</td><td><strong>{dep_txt}</strong></td></tr>
    <tr><td>Velocidad máx. ascenso</td><td>{sm.get('max_ascent_rate_ms', 0):.2f} m/s</td>
        <td>Velocidad máx. descenso</td><td>{sm.get('max_descent_rate_ms', 0):.2f} m/s</td></tr>
    <tr><td>Rango de temperatura</td><td>{sm.get('min_temperature_c', 0):.1f} °C a {sm.get('max_temperature_c', 0):.1f} °C</td>
        <td>Rango de presión</td><td>{sm.get('min_pressure_hpa', 0):.1f} a {sm.get('max_pressure_hpa', 0):.1f} hPa</td></tr>
    <tr><td>Voltaje mínimo batería</td><td>{sm.get('min_voltage_v', 0):.2f} V</td>
        <td>RSSI promedio LoRa</td><td>{rssi_txt}</td></tr>
  </table>

  {charts_html}
</div>
</body>
</html>
"""
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)


def write_pdf_report(out_pdf: str, data: dict[str, Any],
                     figs: list[tuple[str, plt.Figure]]) -> None:
    meta = data["metadata"]
    sm = data["summary"]
    dep = sm.get("deploy_altitude_m")
    dep_txt = f"{dep:.1f} m (error {dep - DEPLOY_TARGET_M:+.1f} m)" if dep is not None else "No registrado"
    rssi_txt = f"{sm['avg_rssi_dbm']:.1f} dBm" if sm.get("avg_rssi_dbm") is not None else "N/D"

    with PdfPages(out_pdf) as pdf:
        # Portada + tabla resumen KPI
        cover, ax = plt.subplots(figsize=(9.5, 5.8), dpi=180)
        ax.axis("off")
        ax.text(0.02, 0.92, "Reporte de Misión CanSat · Equipo Pepe el Pollo",
                fontsize=16, fontweight="bold", color="#0f172a")
        ax.text(0.02, 0.85,
                f"Fuente: {meta.get('source_csv', '')}   |   Muestras: {meta.get('total_samples', 0)}   "
                f"|   Duración: {meta.get('duration_s', 0)} s",
                fontsize=10, color="#475569")

        rows = [
            ["Altura máxima (apogeo)", f"{sm.get('max_altitude_m', 0):.2f} m"],
            ["Despliegue de autogiro", dep_txt],
            ["Velocidad máxima de ascenso", f"{sm.get('max_ascent_rate_ms', 0):.2f} m/s"],
            ["Velocidad máxima de descenso", f"{sm.get('max_descent_rate_ms', 0):.2f} m/s"],
            ["Temperatura (mín / máx)", f"{sm.get('min_temperature_c', 0):.1f} °C / {sm.get('max_temperature_c', 0):.1f} °C"],
            ["Presión atmosférica (mín / máx)", f"{sm.get('min_pressure_hpa', 0):.1f} hPa / {sm.get('max_pressure_hpa', 0):.1f} hPa"],
            ["Voltaje mínimo de batería", f"{sm.get('min_voltage_v', 0):.2f} V"],
            ["RSSI promedio enlace LoRa", rssi_txt],
        ]
        table = ax.table(cellText=rows, colLabels=["Métrica", "Valor"],
                         cellLoc="left", loc="center", bbox=[0.02, 0.12, 0.96, 0.66])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        pdf.savefig(cover)
        plt.close(cover)

        for _, fig in figs:
            pdf.savefig(fig)


def _find_latest_recording(folder: str = "grabaciones") -> str:
    """Encuentra automáticamente la grabación activa en ``grabaciones/``."""
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"No existe la carpeta '{folder}'.")
    for suffix in (".report.json", ".csv"):
        candidates = [
            os.path.join(folder, name)
            for name in os.listdir(folder)
            if name.endswith(suffix) and os.path.isfile(os.path.join(folder, name))
        ]
        if candidates:
            candidates.sort(key=os.path.getmtime, reverse=True)
            return candidates[0]
    raise FileNotFoundError(
        f"No se encontró ningún .report.json ni .csv activo en '{folder}/'."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convierte un .report.json o .csv de CanSat en reporte HTML y PDF con gráficas."
    )
    parser.add_argument(
        "archivo",
        nargs="?",
        default=None,
        help="Ruta al .report.json o .csv (si se omite, usa automáticamente el último en grabaciones/)",
    )
    parser.add_argument("--logo", default=DEFAULT_LOGO, help="Ruta a la insignia PNG del equipo")
    args = parser.parse_args(argv)

    target = args.archivo or _find_latest_recording("grabaciones")
    data = load_flight_data(target)
    base = target
    for suffix in (".report.json", ".json", ".csv"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    out_html = base + "_reporte.html"
    out_pdf = base + "_reporte.pdf"

    figs = build_figures(data)
    try:
        write_html_report(out_html, data, figs, args.logo)
        write_pdf_report(out_pdf, data, figs)
    finally:
        for _, fig in figs:
            plt.close(fig)

    print(f"Reporte HTML generado: {out_html}")
    print(f"Reporte PDF  generado: {out_pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
