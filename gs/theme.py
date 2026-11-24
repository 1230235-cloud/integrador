"""Tema oscuro aerospacial: paleta, estilos Qt y estilos de pyqtgraph."""

from __future__ import annotations


class Colors:
    """Paleta central de la aplicación (metal forjado azul acero + bronce de la insignia)."""

    BG_DEEP = "#090f18"        # fondo de ventana azul noche
    BG_PANEL = "#111b2a"       # acero oscuro de panel
    BG_WIDGET = "#172538"      # acero cepillado de tarjetas/inputs
    BG_HEADER = "#1e3048"      # barra metálica superior
    BORDER = "#3d5875"         # borde metálico plateado-azulado (juego con insignia)
    BORDER_LIGHT = "#5d7ea1"   # bisel metálico superior
    BORDER_FOCUS = "#c9853e"   # foco bronce/cobre de la insignia

    TEXT = "#e6eef6"           # plata metálica clara
    TEXT_DIM = "#9bb0c7"       # acero claro
    TEXT_FAINT = "#667e99"

    ACCENT = "#6fa0ce"         # azul acero cepillado
    ACCENT_2 = "#8a99c7"       # titanio lavanda
    OK = "#358f6a"             # verde técnico sobrio
    WARN = "#c9853e"           # cobre/bronce metálico de la insignia
    ERROR = "#b84c54"          # carmesí metálico sobrio
    INFO = "#5b8ec2"

    ALT = "#72a6d8"
    TEMP = "#cf8448"
    PRESS = "#8b97cc"
    VOLT = "#48a37b"
    PITCH = "#cf8e48"


#: Tamaño de fuente base y família monoespaciada para lecturas numéricas.
FONT_FAMILY = "Segoe UI, DejaVu Sans, Arial, sans-serif"
MONO_FAMILY = "Consolas, DejaVu Sans Mono, Menlo, monospace"


STYLESHEET = f"""
QWidget {{
    background-color: {Colors.BG_DEEP};
    color: {Colors.TEXT};
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {Colors.BG_DEEP};
}}

/* ---------- Paneles ---------- */
QLabel {{
    background: transparent;
    border: none;
}}

QFrame#Panel {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #162438, stop:0.12 {Colors.BG_PANEL}, stop:1 #0d1522);
    border: 1.5px solid {Colors.BORDER};
    border-top-color: {Colors.BORDER_LIGHT};
    border-radius: 10px;
}}

QFrame#Card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1d2e45, stop:1 {Colors.BG_WIDGET});
    border: 1px solid {Colors.BORDER};
    border-top-color: {Colors.BORDER_LIGHT};
    border-radius: 8px;
}}

QFrame#Header {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #263c59, stop:1 {Colors.BG_HEADER});
    border: none;
    border-bottom: 1.5px solid {Colors.BORDER};
    border-radius: 0px;
}}

QLabel#PanelTitle {{
    color: {Colors.TEXT};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2.2px;
    padding: 8px 10px 6px 10px;
    background: transparent;
    border: none;
}}

QLabel#Hint {{
    color: {Colors.TEXT_FAINT};
    font-size: 11px;
    background: transparent;
    border: none;
}}

/* ---------- Indicadores ---------- */
QLabel#IndLabel {{
    color: {Colors.TEXT_DIM};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
    background: transparent;
    border: none;
}}

QLabel#IndValue {{
    font-family: {MONO_FAMILY};
    font-size: 26px;
    font-weight: bold;
    color: {Colors.TEXT};
    background: transparent;
    border: none;
}}

QLabel#IndUnit {{
    color: {Colors.TEXT_FAINT};
    font-size: 11px;
    background: transparent;
    border: none;
}}

/* ---------- Inputs ---------- */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {Colors.BG_WIDGET};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {Colors.ACCENT};
    selection-color: #06121a;
}}

QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
    border: 1px solid #2f4256;
}}

QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
    border: 1px solid {Colors.BORDER_FOCUS};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background-color: {Colors.BG_WIDGET};
    border: 1px solid {Colors.BORDER};
    selection-background-color: {Colors.ACCENT};
    selection-color: #06121a;
    outline: none;
}}

/* ---------- Botones (acero cepillado con bisel metálico) ---------- */
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2c4360, stop:0.5 #1f324a, stop:1 #18273a);
    border: 1px solid {Colors.BORDER};
    border-top-color: {Colors.BORDER_LIGHT};
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: bold;
    letter-spacing: 0.7px;
    color: {Colors.TEXT};
}}

QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #375375, stop:1 #223854);
    border-color: {Colors.BORDER_LIGHT};
}}

QPushButton:pressed {{
    background: #142233;
    border-color: {Colors.BORDER};
}}

QPushButton:disabled {{
    color: {Colors.TEXT_FAINT};
    background: #121b28;
    border-color: #203044;
}}

QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3fa67c, stop:0.5 {Colors.OK}, stop:1 #276e51);
    color: #f2faf6;
    border: 1px solid #4fc293;
    border-top-color: #74d9ae;
}}

QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4ab88b, stop:1 #2f8260);
}}
QPushButton#Primary:disabled {{ background: #19362a; color: #678075; border-color: #224737; }}

QPushButton#Danger {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #cc5c64, stop:0.5 {Colors.ERROR}, stop:1 #8f383f);
    color: #fdf2f3;
    border: 1px solid #d9737a;
    border-top-color: #e69399;
}}

QPushButton#Danger:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #d96a72, stop:1 #a14149);
}}
QPushButton#Danger:disabled {{ background: #3f1f24; color: #8a6a70; border-color: #4f282e; }}

QPushButton#Accent {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4c7ba8, stop:0.5 #38628a, stop:1 #294b6b);
    color: #eef5fc;
    border: 1px solid #6b9bc7;
    border-top-color: #8cb7de;
}}

QPushButton#Accent:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #5b8cb9, stop:1 #335c82);
}}
QPushButton#Accent:disabled {{ background: #1a2e42; color: #637e99; border-color: #253d54; }}

QPushButton#Warn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #d9974d, stop:0.5 {Colors.WARN}, stop:1 #9e662b);
    color: #fff8f0;
    border: 1px solid #e0a865;
    border-top-color: #edc08a;
}}

QPushButton#Warn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #e3a359, stop:1 #b07332);
}}
QPushButton#Warn:disabled {{ background: #45331a; color: #8a7a5c; border-color: #543e21; }}

/* ---------- Casillas / radios ---------- */
QCheckBox, QRadioButton {{
    color: {Colors.TEXT_DIM};
    background: transparent;
    spacing: 7px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {Colors.BORDER};
    background-color: {Colors.BG_WIDGET};
}}

QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}

QCheckBox::indicator:checked {{
    background-color: {Colors.ACCENT};
    border: 1px solid {Colors.ACCENT};
}}

QRadioButton::indicator:checked {{
    background-color: {Colors.ACCENT};
    border: 3px solid {Colors.BG_WIDGET};
    outline: 1px solid {Colors.ACCENT};
}}

/* ---------- Consola ---------- */
QPlainTextEdit#Console {{
    background-color: #05080c;
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    font-family: {MONO_FAMILY};
    font-size: 11px;
    color: {Colors.TEXT};
}}

/* ---------- Barras de progreso / scroll ---------- */
QProgressBar {{
    background-color: {Colors.BG_WIDGET};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    text-align: center;
    color: {Colors.TEXT_DIM};
    font-size: 11px;
}}

QProgressBar::chunk {{
    background-color: {Colors.ACCENT};
    border-radius: 5px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: #2b3a4c;
    border-radius: 5px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{ background: {Colors.ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: #2b3a4c;
    border-radius: 5px;
    min-width: 28px;
}}

QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- Varios ---------- */
QSplitter::handle {{ background-color: {Colors.BORDER}; }}
QSplitter::handle:hover {{ background-color: {Colors.ACCENT}; }}

QStatusBar {{
    background-color: {Colors.BG_HEADER};
    border-top: 1px solid {Colors.BORDER};
    color: {Colors.TEXT_DIM};
}}

QStatusBar::item {{ border: none; }}

QToolTip {{
    background-color: {Colors.BG_HEADER};
    color: {Colors.TEXT};
    border: 1px solid {Colors.ACCENT};
    padding: 4px;
}}

QMenu {{
    background-color: {Colors.BG_WIDGET};
    border: 1px solid {Colors.BORDER};
}}

QMenu::item:selected {{ background-color: {Colors.ACCENT}; color: #06121a; }}
"""


def apply_graph_theme(pg) -> None:
    """Aplica la paleta oscura a pyqtgraph (llamar tras importar pyqtgraph)."""
    pg.setConfigOption("background", Colors.BG_PANEL)
    pg.setConfigOption("foreground", Colors.TEXT_DIM)
    pg.setConfigOptions(antialias=True)

    # Ejes con estética "instrumentación": fondo de etiquetas translúcido
    for axis_name in ("left", "bottom", "right", "top"):
        try:
            axis = pg.getViewBox().getAxis(axis_name)
        except Exception:  # pragma: no cover - depende de la versión de pyqtgraph
            axis = None
        if axis is None:
            continue
        axis.setPen(pg.mkPen(Colors.BORDER))
        axis.setTextPen(pg.mkPen(Colors.TEXT_FAINT))
        axis.setStyle(tickFont=lambda *a: _tick_font())
        axis.setHeight(42)
        axis.setWidth(58)


def _tick_font():
    from PyQt5.QtGui import QFont

    font = QFont("Consolas")
    font.setPointSize(8)
    return font