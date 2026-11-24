"""Gráficas en tiempo real con pyqtgraph.

Tres instrumentos, todos contra el tiempo de misión:

  1. **Altitud** (m), con la marca del despliegue a 200 m.
  2. **Velocidad vertical** (m/s) y **aceleración vertical** (m/s²) en un
     eje secundario: permite ver de un vistazo el ascenso, la caída libre
     (≈ −g) y la meseta del autogiro (≈ 0).
  3. **Temperatura** (°C) y **presión** (hPa), con eje derecho para la
     presión.

Los buffers son circulares (``collections.deque``) con un límite de
muestras, y el redibujado se limita a ``SAMPLE_DT`` segundos para no
saturar la CPU con tasas de envío altas.
"""

from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSizePolicy, QVBoxLayout

from ..theme import Colors
from .connection import Panel

#: Máximo de muestras retenidas por canal.
MAX_SAMPLES = 1500
#: Intervalo mínimo (s) entre muestras dibujadas (25 Hz para caída de 2.5 s).
SAMPLE_DT = 0.04
#: Altitud nominal de apertura del autogiro (m, perfil de prueba 30 m).
ALT_DESPLEGUE = 24.0


class TelemetryPlots(Panel):
    """Conjunto de gráficas en tiempo real."""

    def __init__(self, parent=None) -> None:
        super().__init__("TELEMETRÍA EN TIEMPO REAL", parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._t = deque(maxlen=MAX_SAMPLES)
        self._alt = deque(maxlen=MAX_SAMPLES)
        self._vel = deque(maxlen=MAX_SAMPLES)
        self._acc = deque(maxlen=MAX_SAMPLES)
        self._temp = deque(maxlen=MAX_SAMPLES)
        self._press = deque(maxlen=MAX_SAMPLES)
        self._last_plot = 0.0
        self._dirty = False
        self._window: float | None = None
        self._frozen = False

        layout = QVBoxLayout()
        layout.setSpacing(8)

        # -------------------------------------------------- altitud vs tiempo
        self.alt_plot = self._make_plot("Altitud vs tiempo", "m")
        self.alt_curve = self.alt_plot.plot(
            pen=pg.mkPen(Colors.ALT, width=2),
            fillLevel=0,
            brush=pg.mkBrush(98, 146, 196, 32),
        )
        self.deploy_line = pg.InfiniteLine(
            pos=ALT_DESPLEGUE, angle=0,
            pen=pg.mkPen(Colors.WARN, width=1, style=Qt.DashLine),
            label=f"despliegue {ALT_DESPLEGUE:.0f} m",
            labelOpts={"position": 0.05, "color": Colors.WARN},
        )
        self.alt_plot.addItem(self.deploy_line)
        self.alt_plot.setYRange(0, 35, padding=0.08)
        self.alt_plot.setMouseEnabled(x=True, y=False)
        self.alt_markers = pg.ScatterPlotItem(
            size=5, pen=pg.mkPen(Colors.ALT), brush=pg.mkBrush(Colors.ALT)
        )
        self.alt_plot.addItem(self.alt_markers)
        layout.addWidget(self.alt_plot, 3)

        # ------------------------------------- velocidad + aceleración
        self.dyn_plot = self._make_plot("Velocidad y aceleración vs tiempo", "m/s")
        self.vel_curve = self.dyn_plot.plot(pen=pg.mkPen(Colors.OK, width=2))
        self._acc_vb, self.acc_curve = self._add_right_axis(
            self.dyn_plot, "m/s²", Colors.WARN
        )
        self.dyn_plot.addLine(y=0, pen=pg.mkPen(Colors.BORDER, width=1))
        layout.addWidget(self.dyn_plot, 2)

        # ------------------------------------- temperatura + presión vs tiempo
        self.env_plot = self._make_plot("Temperatura y presión vs tiempo", "°C")
        self.temp_curve = self.env_plot.plot(pen=pg.mkPen(Colors.TEMP, width=2))
        self._press_vb, self._press_curve = self._add_right_axis(
            self.env_plot, "hPa", Colors.PRESS
        )
        self._press_vb.setYRange(900, 1050, padding=0.1)
        layout.addWidget(self.env_plot, 2)

        self.body.addLayout(layout, 1)

    # ------------------------------------------------------------- públicas
    def add_sample(self, telemetry) -> None:
        """Añade un paquete a los buffers (no dibuja necesariamente)."""
        self._t.append(telemetry.t)
        self._alt.append(telemetry.altitude)
        self._vel.append(telemetry.velocity)
        self._acc.append(telemetry.accel)
        self._temp.append(telemetry.temperature)
        self._press.append(telemetry.pressure)

        now = time.monotonic()
        if now - self._last_plot >= SAMPLE_DT or len(self._t) < 2:
            self._last_plot = now
            self._redraw()
            self._dirty = False
        else:
            self._dirty = True

    def redraw(self) -> None:
        """Fuerza el redibujado (usado por el temporizador de la ventana)."""
        if self._dirty and self._t:
            self._dirty = False
            self._redraw()

    def clear(self) -> None:
        """Borra las trazas y reinicia las escalas."""
        for buffer in (self._t, self._alt, self._vel, self._acc,
                       self._temp, self._press):
            buffer.clear()
        self._dirty = False
        for curve in (self.alt_curve, self.vel_curve, self.acc_curve,
                      self.temp_curve, self._press_curve):
            curve.setData([], [])
        self.alt_markers.setData([], [])
        self.alt_plot.setYRange(0, 500, padding=0.08)
        self._press_vb.setYRange(900, 1050, padding=0.1)

    def set_window(self, seconds: float | None) -> None:
        """Fija la ventana temporal visible (en segundos de misión)."""
        self._window = max(5.0, float(seconds)) if seconds else None
        if self._t:
            self._apply_x_range()

    def freeze(self, frozen: bool) -> None:
        """Detiene el desplazamiento temporal sin dejar de dibujar."""
        self._frozen = bool(frozen)

    def follow_y(self) -> None:
        """Ajusta automáticamente las escalas verticales."""
        if self._alt:
            self.alt_plot.setYRange(0, max(max(self._alt) * 1.1, 50), padding=0)
        if self._vel:
            lo = min(min(self._vel), -1.0)
            hi = max(max(self._vel), 1.0)
            self.dyn_plot.setYRange(lo * 1.15, hi * 1.15, padding=0)
        if self._acc:
            lo = min(min(self._acc), -1.0)
            hi = max(max(self._acc), 1.0)
            self._acc_vb.setYRange(lo * 1.15, hi * 1.15, padding=0)
        if self._press:
            lo, hi = min(self._press), max(self._press)
            self._press_vb.setYRange(lo - 5, hi + 5, padding=0.1)

    # ------------------------------------------------------------ internas
    @staticmethod
    def _make_plot(title: str, unit: str) -> pg.PlotWidget:
        plot = pg.PlotWidget(background=Colors.BG_WIDGET)
        plot.setTitle(title, color=Colors.TEXT, size="10pt")
        plot.showGrid(x=True, y=True, alpha=0.18)
        plot.getAxis("left").setLabel(unit, color=Colors.TEXT_FAINT, size="9pt")
        plot.getAxis("bottom").setLabel(
            "tiempo de misión (s)", color=Colors.TEXT_FAINT, size="9pt"
        )
        plot.getPlotItem().setContentsMargins(4, 6, 4, 4)
        plot.setClipToView(True)
        plot.hideButtons()
        for name in ("left", "bottom"):
            axis = plot.getAxis(name)
            axis.setPen(pg.mkPen(Colors.BORDER))
            axis.setTextPen(pg.mkPen(Colors.TEXT_FAINT))
        plot.setBackground(Colors.BG_WIDGET)
        return plot

    def _add_right_axis(self, plot: pg.PlotWidget, label: str, color: str):
        """Crea un eje vertical secundario enlazado al principal.

        Devuelve ``(viewbox, curva)``; la curva se dibuja contra ese ViewBox.
        """
        vb = pg.ViewBox()
        plot.plotItem.showAxis("right")
        plot.plotItem.scene().addItem(vb)
        right = plot.getAxis("right")
        right.linkToView(vb)
        right.setLabel(label, color=color, size="9pt")
        right.setPen(pg.mkPen(Colors.BORDER))
        right.setTextPen(pg.mkPen(Colors.TEXT_FAINT))
        right.setWidth(58)
        vb.setXLink(plot.plotItem.vb)
        vb.setMouseEnabled(x=False, y=False)

        # La curva debe vivir en el ViewBox secundario para que se dibuje
        # contra la escala de la derecha (no contra la de la izquierda).
        curve = pg.PlotDataItem(pen=pg.mkPen(color, width=2))
        vb.addItem(curve)
        self._sync_right_axis(plot, vb)
        plot.installEventFilter(self)
        plot._right_vb = vb  # type: ignore[attr-defined]
        return vb, curve

    @staticmethod
    def _sync_right_axis(plot: pg.PlotWidget, vb: pg.ViewBox) -> None:
        """Mantiene el eje derecho alineado con el ViewBox principal."""
        main = plot.plotItem.vb
        vb.setGeometry(main.sceneBoundingRect())
        vb.linkedViewChanged(main, vb.XAxis)

    def eventFilter(self, obj, event):  # noqa: N802 (API Qt)
        if event.type() == event.Resize:
            vb = getattr(obj, "_right_vb", None)
            if vb is not None:
                self._sync_right_axis(obj, vb)
        return super().eventFilter(obj, event)

    def _redraw(self) -> None:
        xs = list(self._t)
        self.alt_curve.setData(xs, list(self._alt))
        self.vel_curve.setData(xs, list(self._vel))
        self.acc_curve.setData(xs, list(self._acc))
        self.temp_curve.setData(xs, list(self._temp))
        self._press_curve.setData(xs, list(self._press))

        self.alt_markers.setData([xs[-1]], [self._alt[-1]])
        if not self._frozen:
            self._apply_x_range(xs)

    def _apply_x_range(self, xs=None) -> None:
        if xs is None:
            xs = list(self._t)
        if not xs:
            return
        if self._window:
            lo, hi = xs[-1] - self._window, xs[-1]
        else:
            span = max(xs[-1] - xs[0], 10.0)
            lo, hi = xs[0], xs[-1] + span * 0.02
        for plot in (self.alt_plot, self.dyn_plot, self.env_plot):
            plot.setXRange(lo, hi, padding=0)
