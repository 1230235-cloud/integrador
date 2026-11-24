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

from .protocol import CSV_HEADER, format_csv_row, telemetry_to_dict


class CsvRecorder:
    """Escritor CSV y JSONL de flujo con inicio/parada en caliente."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._file = None
        self._jsonl_file = None
        self._writer = None
        self._path = ""
        self._jsonl_path = ""
        self._rows = 0

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
    def rows(self) -> int:
        with self._lock:
            return self._rows

    def start(self, path: str, header: str = CSV_HEADER) -> bool:
        """Abre el fichero CSV (y su espejo JSONL) y escribe la cabecera."""
        with self._lock:
            if self._file is not None:
                return False
            base, _ = os.path.splitext(path)
            jsonl_path = base + ".jsonl"
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
            self._rows = 0
            return True

    def stop(self) -> int:
        """Cierra ambos ficheros y devuelve el número de filas escritas."""
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
            self._file = None
            self._jsonl_file = None
            self._writer = None
            return self._rows

    def write(self, telemetry) -> None:
        """Añade un paquete en CSV y JSONL. Seguro desde el hilo lector."""
        with self._lock:
            if self._writer is None or self._file is None:
                return
            try:
                self._writer.writerow(format_csv_row(telemetry).split(","))
                if self._jsonl_file is not None:
                    self._jsonl_file.write(
                        json.dumps(telemetry_to_dict(telemetry), ensure_ascii=False) + "\n"
                    )
                self._rows += 1
            except (OSError, ValueError):
                self._file = None
                self._jsonl_file = None
                self._writer = None