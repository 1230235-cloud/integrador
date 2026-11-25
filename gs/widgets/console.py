"""Panel de control (comandos y grabación CSV) y consola de mensajes."""

from __future__ import annotations

import time

from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import protocol
from ..theme import Colors
from .connection import Panel

#: Color de consola por nivel de mensaje.
LEVEL_COLORS = {
    "info": Colors.TEXT_DIM,
    "tx": Colors.ACCENT,
    "rx": Colors.OK,
    "ok": Colors.OK,
    "warn": Colors.WARN,
    "error": Colors.ERROR,
}

DEFAULT_RECORD_DIR = "grabaciones"


def _format(color: str) -> QTextCharFormat:
    char_format = QTextCharFormat()
    char_format.setForeground(QColor(color))
    return char_format


def _restyle(widget: QWidget) -> None:
    """Fuerza la re-evaluación del estilo tras cambiar ``objectName``."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class LogConsole(QFrame):
    """Consola de texto con marca de tiempo y color por nivel."""

    def __init__(self, parent: QWidget | None = None, max_lines: int = 800) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 10)
        layout.setSpacing(0)

        title = QLabel("CONSOLA DE COMUNICACIONES")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self.view = QPlainTextEdit(self)
        self.view.setObjectName("Console")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(max_lines)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.view, 1)

        self._formats = {level: _format(color) for level, color in LEVEL_COLORS.items()}
        self._formats["default"] = _format(Colors.TEXT)

    def append(self, message: str, level: str = "info", stamp: bool = True) -> None:
        """Añade una línea a la consola (scroll automático)."""
        prefix = f"[{time.strftime('%H:%M:%S')}] " if stamp else ""
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"{prefix}{message}\n",
                          self._formats.get(level, self._formats["default"]))
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def clear(self) -> None:
        self.view.clear()


class ControlPanel(Panel):
    """Calibración, comandos de misión, grabación CSV y entrada libre.

    Señales:
        ``command_sent(str)``       comando a transmitir por el puerto
        ``record_toggle(str)``      ruta destino (iniciar) o ``""`` (detener)
        ``echo_toggled(bool)``      impresión de tramas brutas
        ``clear_requested()``       limpiar la consola
    """

    command_sent = pyqtSignal(str)
    record_toggle = pyqtSignal(str)
    echo_toggled = pyqtSignal(bool)
    clear_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("CONTROL DE MISIÓN", parent)
        self._recording = False

        # Botón principal de armado / inicio de misión (habilita el servo para caída libre)
        self.start_mission_btn = _button(
            "▶ INICIAR MISIÓN (ARMAR SERVO)",
            "Warn",
            "Calibra sensores y arma el despliegue automático del servo para el vuelo",
        )
        self.start_mission_btn.setFixedHeight(34)
        self.start_mission_btn.clicked.connect(lambda: self._send(protocol.CMD_START_MISSION))
        self.body.addWidget(self.start_mission_btn)

        # Fila compacta: desplegable QComboBox de acciones + botón ejecutar + botón grabar
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self.action_combo = QComboBox(self)
        self.action_combo.setFixedHeight(32)
        self.action_combo.setToolTip("Selecciona un comando de misión y pulsa ▶")
        self.action_combo.addItem("Calibrar barómetro", protocol.CMD_CALIBRATE)
        self.action_combo.addItem("Probar servo (GPIO 5)", protocol.CMD_TEST_SERVO)
        self.action_combo.addItem("Desplegar autogiro", protocol.CMD_DEPLOY_PARENT)
        self.action_combo.addItem("Reiniciar misión", protocol.CMD_RECOVER)
        self.action_combo.addItem("Abortar despliegue", protocol.CMD_CUT_PARACHUTE)
        self.action_combo.addItem("Elegir ruta CSV…", "__BROWSE__")
        top_row.addWidget(self.action_combo, 1)

        self.exec_btn = _button("▶", "Accent", "Ejecuta la acción seleccionada del desplegable")
        self.exec_btn.setFixedSize(36, 32)
        self.exec_btn.clicked.connect(self._execute_selected_action)
        top_row.addWidget(self.exec_btn)

        self.record_btn = _button(
            "● GRABAR",
            "Primary",
            "Inicia o detiene la grabación al instante (CSV + JSONL + Reporte JSON)",
        )
        self.record_btn.setFixedHeight(32)
        self.record_btn.setMinimumWidth(98)
        self.record_btn.clicked.connect(self._toggle_recording)
        top_row.addWidget(self.record_btn)

        self.body.addLayout(top_row)

        self.path_label = QLabel("Exportación: sin grabación activa", self)
        self.path_label.setObjectName("Hint")
        self.path_label.setToolTip("Sin grabación activa")
        self.body.addWidget(self.path_label)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        self.echo_check = QCheckBox("Trama cruda", self)
        self.echo_check.setToolTip("Muestra cada telemetría recibida en la consola")
        self.echo_check.setChecked(True)
        self.echo_check.toggled.connect(self.echo_toggled)
        row3.addWidget(self.echo_check)
        self.clear_btn = _button("LIMPIAR CONSOLA", "", "Borra el historial de la consola")
        self.clear_btn.clicked.connect(self.clear_requested)
        row3.addWidget(self.clear_btn, 1)
        self.body.addLayout(row3)

        self._pending_path = ""
        self._link_active = False

    # ------------------------------------------------------------------ API
    @property
    def is_recording(self) -> bool:
        return self._recording

    def toggle_recording(self) -> None:
        """Alterna la grabación (usado también por atajo de teclado)."""
        self._toggle_recording()

    def set_link_active(self, active: bool) -> None:
        """Actualiza estado de enlace; acciones y grabación permanecen accesibles."""
        self._link_active = bool(active)
        self.action_combo.setEnabled(True)
        self.exec_btn.setEnabled(True)
        self.record_btn.setEnabled(True)

    def set_recording(self, recording: bool, path: str = "") -> None:
        """Refleja el estado de la grabación en el botón dedicado y la etiqueta."""
        self._recording = recording
        self.record_btn.setEnabled(True)
        self.record_btn.setText("■ DETENER" if recording else "● GRABAR")
        self.record_btn.setObjectName("Danger" if recording else "Primary")
        _restyle(self.record_btn)
        self.path_label.setText(
            f"Exportando: {path}" if path else "Exportación: sin grabación activa"
        )
        self.path_label.setToolTip(path or "Sin grabación activa")

    # -------------------------------------------------------------- internos
    def _execute_selected_action(self) -> None:
        data = self.action_combo.currentData()
        if data == "__BROWSE__":
            self._browse()
            return
        if data:
            self._send(str(data))

    def _send(self, command: str) -> None:
        self.command_sent.emit(command)

    def _toggle_recording(self) -> None:
        if self._recording:
            self.record_toggle.emit("")
            return
        path = self._pending_path or (
            f"{DEFAULT_RECORD_DIR}/vuelo_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        self._pending_path = ""
        self.record_toggle.emit(path)

    def _choose_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar telemetría en CSV",
            f"{DEFAULT_RECORD_DIR}/cansat.csv",
            "Archivos CSV (*.csv);;Todos los archivos (*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if path:
            self._pending_path = path
            self.path_label.setText(f"Destino: {path}")
        return path

    def _browse(self) -> None:
        self._choose_path()


def _button(text: str, object_name: str, tooltip: str) -> QPushButton:
    button = QPushButton(text)
    if object_name:
        button.setObjectName(object_name)
    button.setToolTip(tooltip)
    button.setCursor(Qt.PointingHandCursor)
    return button