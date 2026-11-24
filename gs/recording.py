"""Grabación de telemetría a CSV.

La escritura se realiza dentro del hilo de recepción de datos (el mismo
que lee el puerto), por lo que el orden de las filas queda garantizado y
no se bloquea nunca la interfaz. Las órdenes de inicio/parada se
sincronizan con un lock y se aplican en el siguiente paquete.
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time

from .protocol import CSV_HEADER, format_csv_row, telemetry_to_dict


class CsvRecorder:
    """Escritor CSV + JSONL en flujo y exportador de paquete JSON para reportes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._file = None
        self._jsonl_file = None
        self._writer = None
        self._path = ""
        self._jsonl_path = ""
        self._report_path = ""
        self._rows = 0
        self._samples: list[dict] = []

    # ------------------------------------------------------------------ API
    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._file is not None

    @property
    def path(self) -> str:
        with self._lock:
            return self._path

    @property
    def jsonl_path(self) -> str:
        with self._lock:
            return self._jsonl_path

    @property
    def report_path(self) -> str:
        with self._lock:
            return self._report_path

    @property
    def rows(self) -> int:
        with self._lock:
            return self._rows

    def start(self, path: str, header: str = CSV_HEADER) -> bool:
        """Abre CSV + JSONL y prepara el buffer para el paquete ``.report.json``."""
        with self._lock:
            if self._file is not None:
                return False
            base, _ = os.path.splitext(path)
            jsonl_path = base + ".jsonl"
            report_path = base + ".report.json"
            try:
                self._file = open(path, "w", newline="", encoding="utf-8")
                self._jsonl_file = open(jsonl_path, "w", encoding="utf-8")
            except OSError:
                if self._file is not None:
                    try:
                        self._file.close()
                    except OSError:
                        pass
                self._file = None
                self._jsonl_file = None
                return False
            self._writer = csv.writer(self._file)
            self._writer.writerow(header.split(","))
            self._file.flush()
            self._path = path
            self._jsonl_path = jsonl_path
            self._report_path = report_path
            self._rows = 0
            self._samples = []
            return True

    def stop(self) -> int:
        """Cierra CSV/JSONL y genera el paquete ``.report.json`` listo para graficar."""
        with self._lock:
            if self._file is None:
                return 0
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                pass
            if self._jsonl_file is not None:
                try:
                    self._jsonl_file.flush()
                    self._jsonl_file.close()
                except OSError:
                    pass
            if self._samples and self._report_path:
                self._write_report_bundle(self._report_path, self._path, self._samples)
            self._file = None
            self._jsonl_file = None
            self._writer = None
            return self._rows

    def write(self, telemetry) -> None:
        """Añade un paquete en CSV, JSONL y buffer de reporte."""
        with self._lock:
            if self._writer is None or self._file is None:
                return
            try:
                self._writer.writerow(format_csv_row(telemetry).split(","))
                record = telemetry_to_dict(telemetry)
                if self._jsonl_file is not None:
                    self._jsonl_file.write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )
                self._samples.append(record)
                self._rows += 1
            except (OSError, ValueError):
                self._file = None
                self._jsonl_file = None
                self._writer = None

    @staticmethod
    def _write_report_bundle(report_path: str, csv_path: str, samples: list[dict]) -> None:
        """Exporta metadatos, resumen KPI y series listas para un generador de reportes."""
        alts = [s["altitude_m"] for s in samples]
        vels = [s["velocity_ms"] for s in samples]
        temps = [s["temperature_c"] for s in samples]
        press = [s["pressure_hpa"] for s in samples]
        volts = [s["voltage_v"] for s in samples]
        rssis = [s["rssi_dbm"] for s in samples if s.get("rssi_dbm") is not None]
        deploy_sample = next((s for s in samples if s.get("chute") == 1), None)

        bundle = {
            "schema_version": "1.0",
            "metadata": {
                "team": "Pepe el Pollo",
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_csv": os.path.basename(csv_path),
                "total_samples": len(samples),
                "duration_s": round(samples[-1]["mission_time_s"] - samples[0]["mission_time_s"], 2),
            },
            "summary": {
                "max_altitude_m": round(max(alts), 2),
                "max_ascent_rate_ms": round(max(vels), 2),
                "max_descent_rate_ms": round(abs(min(vels)), 2),
                "deploy_altitude_m": deploy_sample["altitude_m"] if deploy_sample else None,
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
                "rssi_dbm": [s.get("rssi_dbm") for s in samples],
                "snr_db": [s.get("snr_db") for s in samples],
            },
        }
        try:
            with open(report_path, "w", encoding="utf-8") as fh:
                json.dump(bundle, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass