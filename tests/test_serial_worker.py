"""Pruebas del troceado de tramas del hilo de recepción."""

from __future__ import annotations

from gs.serial_worker import SerialWorker


def test_trama_simple() -> None:
    linea, resto = SerialWorker._split_frame(b"T,1,2\nresto")
    assert linea == b"T,1,2"
    assert resto == b"resto"


def test_crlf_no_deja_salto() -> None:
    linea, resto = SerialWorker._split_frame(b"T,1\r\nT,2\r\n")
    assert linea == b"T,1"
    assert resto == b"T,2\r\n"


def test_lineas_vacias_se_descartan_sin_cortar() -> None:
    linea, resto = SerialWorker._split_frame(b"\r\n\nT,9\r\n")
    assert linea == b"T,9"
    assert resto == b""


def test_sin_delimitador_no_consume() -> None:
    linea, resto = SerialWorker._split_frame(b"T,1,2")
    assert linea is None
    assert resto == b"T,1,2"


def test_buffer_vacio() -> None:
    linea, resto = SerialWorker._split_frame(b"")
    assert linea is None
    assert resto == b""


def test_varias_tramas_se_extraen_en_orden() -> None:
    buffer = b"T,1\rT,2\rT,3\r"
    extraidas = []
    while True:
        linea, buffer = SerialWorker._split_frame(buffer)
        if linea is None:
            break
        extraidas.append(linea)
    assert extraidas == [b"T,1", b"T,2", b"T,3"]
    assert buffer == b""
