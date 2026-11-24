"""Panel de control (comandos y grabación CSV) y consola de mensajes."""

from __future__ import annotations

import time

from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
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

        # Fila compacta: menú desplegable de acciones + botón dedicado de grabación
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.menu_btn = _button(
            "ACCIONES  ▾",
            "Accent",
            "Comandos de calibración, despliegue, reinicio y ruta de exportación",
        )
        self.menu_btn.setFixedHeight(32)
        self.menu = QMenu(self)
        self.menu.setStyleSheet(
            f"QMenu {{ background: {Colors.BG_PANEL}; color: {Colors.TEXT}; "
            f"border: 1px solid {Colors.BORDER}; padding: 4px; font-size: 12px; }}"
            f"QMenu::item {{ padding: 6px 14px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background: {Colors.BG_WIDGET}; color: {Colors.ACCENT}; }}"
            f"QMenu::item:disabled {{ color: {Colors.TEXT_FAINT}; }}"
            f"QMenu::separator {{ height: 1px; background: {Colors.BORDER}; margin: 4px 8px; }}"
        )

        self.action_calib = QAction("Calibrar barómetro  (C,CAL,1)", self)
        self.action_calib.triggered.connect(lambda: self._send(protocol.CMD_CALIBRATE))
        self.menu.addAction(self.action_calib)

        self.action_deploy = QAction("Desplegar autogiro  (C,DEP,DEPLOY)", self)
        self.action_deploy.triggered.connect(lambda: self._send(protocol.CMD_DEPLOY_PARENT))
        self.menu.addAction(self.action_deploy)

        self.action_reset = QAction("Reiniciar misión  (C,SYS,RESET)", self)
        self.action_reset.triggered.connect(lambda: self._send(protocol.CMD_RECOVER))
        self.menu.addAction(self.action_reset)

        self.action_abort = QAction("Abortar despliegue  (C,CHUTE,CUT)", self)
        self.action_abort.triggered.connect(lambda: self._send(protocol.CMD_CUT_PARACHUTE))
        self.menu.addAction(self.action_abort)

        self.menu.addSeparator()

        self.action_browse = QAction("Elegir ruta de exportación…", self)
        self.action_browse.triggered.connect(self._browse)
        self.menu.addAction(self.action_browse)

        self.menu_btn.setMenu(self.menu)
        top_row.addWidget(self.menu_btn, 1)

        self.record_btn = _button(
            "● GRABAR",
            "Primary",
            "Inicia o detiene la grabación (CSV + JSONL + Reporte JSON)",
        )
        self.record_btn.setFixedHeight(32)
        self.record_btn.clicked.connect(self._toggle_recording)
        top_row.addWidget(self.record_btn, 1)

        self.body.addLayout(top_row)

        self.path_label = QLabel("Exportación: sin grabación activa", self)
        self.path_label.setObjectName("Hint")
        self.path_label.setToolTip("Sin grabación activa")
        self.body.addWidget(self.path_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.command_edit = QLineEdit(self)
        self.command_edit.setPlaceholderText("Comando libre (Enter para enviar)")
        self.command_edit.returnPressed.connect(self._send_typed)
        row.addWidget(self.command_edit, 1)
        self.send_btn = _button("ENVIAR", "Primary", "Envía el texto del campo de comando")
        self.send_btn.setFixedWidth(92)
        self.send_btn.clicked.connect(self._send_typed)
        row.addWidget(self.send_btn)
        self.body.addLayout(row)

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

    # ------------------------------------------------------------------ API
    @property
    def is_recording(self) -> bool:
        return self._recording

    def toggle_recording(self) -> None:
        """Alterna la grabación (usado también por atajo de teclado)."""
        self._toggle_recording()

    def set_link_active(self, active: bool) -> None:
        """Habilita los comandos solo con el enlace abierto."""
        for action in (self.action_calib, self.action_deploy,
                       self.action_reset, self.action_abort):
            action.setEnabled(active)
        self.send_btn.setEnabled(active)
        self.command_edit.setEnabled(active)
        self.action_browse.setEnabled(active or self._recording)

    def set_recording(self, recording: bool, path: str = "") -> None:
        """Refleja el estado de la grabación en el botón dedicado y la etiqueta."""
        self._recording = recording
        self.record_btn.setText("■ DETENER" if recording else "● GRABAR")
        self.record_btn.setObjectName("Danger" if recording else "Primary")
        _restyle(self.record_btn)
        self.path_label.setText(
            f"Exportando: {path}" if path else "Exportación: sin grabación activa"
        )
        self.path_label.setToolTip(path or "Sin grabación activa")
        self.action_browse.setEnabled(not recording)

    # -------------------------------------------------------------- internos
    def _send(self, command: str) -> None:
        self.command_edit.setText(command)
        self.command_sent.emit(command)

    def _send_typed(self) -> None:
        command = self.command_edit.text().strip()
        if command:
            self.command_sent.emit(command)

    def _toggle_recording(self) -> None:
        if self._recording:
            self.record_toggle.emit("")
            return
        path = self._choose_path()
        if path:
            self.record_toggle.emit(path)

    def _choose_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar telemetría en CSV",
            f"{DEFAULT_RECORD_DIR}/cansat.csv",
            "Archivos CSV (*.csv);;Todos los archivos (*)",
        )
        if path:
            self._pending_path = path
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