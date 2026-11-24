"""Ventana principal de la Estación Terrestre: dashboard y cableado de señales."""

from __future__ import annotations

import math
import os

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import (
    QColor,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPixmap,
    QTransform,
)
from PyQt5.QtWidgets import (
    QAction,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .serial_worker import SIM_TAG, PortScanThread, SerialWorker
from .theme import Colors
from .web_mirror import WebMirrorServer
from .widgets import (
    AttitudeIndicator,
    ConnectionPanel,
    ControlPanel,
    IndicatorCard,
    LogConsole,
    MissionClockCard,
    TelemetryPlots,
)

APP_TITLE = "CanSat · Estación Terrestre (Ground Station)"


class MainWindow(QMainWindow):
    """Dashboard de telemetría: indicadores, gráficas, actitud y control."""

    def __init__(
        self,
        initial_port: str | None = None,
        initial_baudrate: int | None = None,
        force_simulation: bool = False,
        web_port: int = 8000,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1560, 940)

        self.worker = SerialWorker(self)
        self.port_scanner: PortScanThread | None = None
        self.web_mirror = WebMirrorServer(port=web_port)
        self._linked = False
        self._echo = True
        self._max_altitude = 0.0

        # Opciones de arranque, aplicadas cuando termine el escaneo de puertos.
        self._initial_port = initial_port
        self._initial_baudrate = initial_baudrate or 115200
        self._force_simulation = bool(force_simulation)

        self._build_ui()
        self._connect_signals()
        self._build_status_bar()
        self._build_shortcuts()

        self.console.append("Estación terrestre lista.", "ok", stamp=False)
        if self.web_mirror.start():
            self.console.append(
                f"Espejo LAN para tablet activo (sin internet): {self.web_mirror.url}",
                "ok", stamp=False)
        self.console.append(
            "Actitud: " + self.attitude.backend_name
            + "   ·   trama: T,t,alt,temp,pres,vol,pitch,roll,yaw,state,sat,chute,"
              "packet,vel,acc,sec_dist,sec_bear[,rssi,snr]",
            "info", stamp=False)
        self.scan_ports()

        # Redibujado periódico: mantiene las curvas vivas aunque el hilo
        # tarde entre muestras.
        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._on_ui_tick)
        self._ui_timer.start(120)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 6)
        outer.setSpacing(8)

        # Barra superior estática: insignia sin fondo + controles de vista
        outer.addWidget(self._build_top_bar(), 0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        self.left_panel = self._build_left_column()
        body.addWidget(self.left_panel, 0)
        body.addWidget(self._build_right_area(), 1)
        outer.addLayout(body, 1)

        self.setCentralWidget(central)

    def _build_top_bar(self) -> QFrame:
        """Barra superior fija con insignia transparente y toggles de vista."""
        bar = QFrame(self)
        bar.setObjectName("Panel")
        bar.setFixedHeight(64)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(12)

        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_nobg = os.path.join(root_dir, "docs", "insignia-pepe-el-pollo-nobg.png")
        logo_fallback = os.path.join(root_dir, "docs", "insignia-pepe-el-pollo.png")
        logo_path = logo_nobg if os.path.exists(logo_nobg) else logo_fallback

        logo_lbl = SpinningBadge3D(logo_path, size=52, parent=bar)
        row.addWidget(logo_lbl)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        title = QLabel("PEPE EL POLLO", bar)
        title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; letter-spacing: 1.5px; color: {Colors.TEXT};"
        )
        subtitle = QLabel("CanSat · Estación Terrestre · FITEC", bar)
        subtitle.setStyleSheet(f"font-size: 11px; color: {Colors.ACCENT};")
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        row.addLayout(text_col)

        row.addStretch(1)

        self.btn_toggle_link = QPushButton("Ocultar enlace", bar)
        self.btn_toggle_link.setCheckable(True)
        self.btn_toggle_link.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_link.setToolTip(
            "Oculta el panel lateral de enlace para ver las gráficas en grande"
        )
        self.btn_toggle_link.toggled.connect(self._toggle_left_panel)
        row.addWidget(self.btn_toggle_link)

        self.btn_toggle_console = QPushButton("Ocultar consola", bar)
        self.btn_toggle_console.setCheckable(True)
        self.btn_toggle_console.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_console.setToolTip("Oculta o muestra la consola de comunicaciones")
        self.btn_toggle_console.toggled.connect(self._toggle_console_panel)
        row.addWidget(self.btn_toggle_console)

        return bar

    def _toggle_left_panel(self, hidden: bool) -> None:
        self.left_panel.setVisible(not hidden)
        self.btn_toggle_link.setText("Mostrar enlace" if hidden else "Ocultar enlace")

    def _toggle_console_panel(self, hidden: bool) -> None:
        self.console_holder.setVisible(not hidden)
        self.btn_toggle_console.setText("Mostrar consola" if hidden else "Ocultar consola")

    def _build_left_column(self) -> QWidget:
        column = QWidget(self)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.connection = ConnectionPanel(self)
        layout.addWidget(self.connection)

        # -------------------------------------------------- indicadores
        indicators = QWidget(self)
        grid = QGridLayout(indicators)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        self.ind_alt = IndicatorCard("ALTITUD", "m", Colors.ALT, decimals=1)
        self.ind_vel = IndicatorCard("VELOCIDAD VERT.", "m/s", Colors.OK, decimals=2)
        self.ind_temp = IndicatorCard("TEMPERATURA", "°C", Colors.TEMP, decimals=1)
        self.ind_press = IndicatorCard("PRESIÓN", "hPa", Colors.PRESS, decimals=2)
        self.ind_volt = IndicatorCard("BATERÍA", "V", Colors.VOLT, decimals=2,
                                      warning_low=6.8)
        self.ind_acc = IndicatorCard("ACELERACIÓN", "m/s²", Colors.WARN, decimals=2)
        self.ind_st = MissionClockCard(self)

        grid.addWidget(self.ind_alt, 0, 0)
        grid.addWidget(self.ind_vel, 0, 1)
        grid.addWidget(self.ind_temp, 1, 0)
        grid.addWidget(self.ind_press, 1, 1)
        grid.addWidget(self.ind_volt, 2, 0)
        grid.addWidget(self.ind_acc, 2, 1)
        grid.addWidget(self.ind_st, 3, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(indicators)

        self.controls = ControlPanel(self)
        layout.addWidget(self.controls)
        layout.addStretch(1)
        column.setFixedWidth(388)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(404)
        scroll.setWidget(column)
        return scroll

    def _build_right_area(self) -> QWidget:
        splitter = QSplitter(Qt.Vertical, self)
        splitter.setChildrenCollapsible(False)

        self.plots = TelemetryPlots(self)

        bottom = QSplitter(Qt.Horizontal, splitter)
        bottom.setChildrenCollapsible(False)
        bottom.addWidget(self._build_attitude_block())
        bottom.addWidget(self._build_console_block())
        bottom.setSizes([620, 700])

        splitter.addWidget(self.plots)
        splitter.addWidget(bottom)
        splitter.setSizes([520, 420])
        return splitter

    def _build_attitude_block(self) -> QWidget:
        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)

        self.attitude = AttitudeIndicator(self)
        layout.addWidget(self.attitude)

        reset = QLabel("Arrastra para orbitar · rueda para zoom · botón derecho para rotar",
                       holder)
        reset.setObjectName("Hint")
        reset.setAlignment(Qt.AlignCenter)
        layout.addWidget(reset)
        return holder

    def _build_console_block(self) -> QWidget:
        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        self.console = LogConsole(self)
        layout.addWidget(self.console)
        self.console_holder = holder
        return holder

    def _build_status_bar(self) -> None:
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)

        self.lbl_link = _status_label("ENLACE: —", Colors.TEXT_FAINT)
        self.lbl_rf = _status_label("RF: —", Colors.TEXT_DIM)
        self.lbl_packets = _status_label("PAQUETES: 0", Colors.TEXT_DIM)
        self.lbl_loss = _status_label("PERDIDOS: 0", Colors.TEXT_DIM)
        self.lbl_rate = _status_label("CADENCIA: 0.0 Hz", Colors.TEXT_DIM)
        self.lbl_record = _status_label("● SIN GRABAR", Colors.TEXT_FAINT)
        self.lbl_backend = _status_label("MOTOR: —", Colors.TEXT_FAINT)
        self.lbl_backend.setText(f"MOTOR: {self.attitude.backend_name}")

        for label in (self.lbl_link, self.lbl_rf, self.lbl_packets, self.lbl_loss, self.lbl_rate):
            self.status.addWidget(label)
        self.status.addPermanentWidget(self.lbl_record)
        self.status.addPermanentWidget(self.lbl_backend)

    def _build_shortcuts(self) -> None:
        for key, slot, name in (
            ("Ctrl+O", self._open_connect, "Conectar"),
            ("Ctrl+D", self._disconnect, "Desconectar"),
            ("Ctrl+R", self.controls.toggle_recording, "Grabación"),
            ("Ctrl+L", self.controls.clear_requested.emit, "Limpiar consola"),
        ):
            action = QAction(name, self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(slot)
            self.addAction(action)

    # ------------------------------------------------------------- señales
    def _connect_signals(self) -> None:
        self.connection.connect_requested.connect(self._open_connect)
        self.connection.disconnect_requested.connect(self._disconnect)
        self.connection.refresh_requested.connect(self.scan_ports)

        self.controls.command_sent.connect(self._send_command)
        self.controls.record_toggle.connect(self._toggle_recording)
        self.controls.echo_toggled.connect(self._set_echo)
        self.controls.clear_requested.connect(self.console.clear)

        self.worker.telemetry.connect(self._on_telemetry)
        self.worker.log.connect(self._on_worker_log)
        self.worker.linked.connect(self._on_linked)
        self.worker.stats.connect(self._on_stats)

    # ------------------------------------------------------------- acciones
    def _open_connect(self) -> None:
        if self.worker.isRunning():
            return
        port = self.connection.selected_port
        if not port:
            self.console.append("Selecciona un puerto COM/TTY o el simulador.", "warn")
            return

        self.connection.set_busy(True)
        self.worker.configure(SIM_TAG if self.connection.simulation_selected else port,
                              self.connection.selected_baudrate)
        self.worker.start()
        self.controls.set_link_active(True)

    def _disconnect(self) -> None:
        if not self.worker.isRunning():
            return
        self.console.append("Cerrando enlace…", "warn")
        self.connection.set_busy(False)
        self.worker.shutdown()

    def _send_command(self, command: str) -> None:
        self.worker.send_command(command)

    def _toggle_recording(self, path: str) -> None:
        if path:
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            if self.worker.start_recording(path):
                self.controls.set_recording(True, path)
                self.lbl_record.setText("● GRABANDO")
                self.lbl_record.setStyleSheet(f"color: {Colors.ERROR}; font-weight: bold;")
                self.console.append(f"Grabación iniciada → {path}", "ok")
            else:
                self.console.append(f"No se pudo abrir {path} para escritura", "error")
                self.controls.set_recording(False)
        else:
            rows = self.worker.stop_recording()
            self.controls.set_recording(False)
            self.lbl_record.setText("● SIN GRABAR")
            self.lbl_record.setStyleSheet(f"color: {Colors.TEXT_FAINT};")
            self.console.append(f"Grabación detenida ({rows} muestras)", "ok")

    def _set_echo(self, enabled: bool) -> None:
        self._echo = bool(enabled)

    # ---------------------------------------------------------- recepción
    def scan_ports(self) -> None:
        """Re-escanea los puertos en segundo plano."""
        if self.port_scanner is not None and self.port_scanner.isRunning():
            return
        self.port_scanner = PortScanThread(self)
        self.port_scanner.found.connect(self._on_ports_found)
        self.port_scanner.start()

    def _on_ports_found(self, ports) -> None:
        self.connection.set_ports(ports)
        self._apply_startup_options()
        if ports:
            self.console.append(
                f"Puertos detectados: {', '.join(p[0] for p in ports)}", "info")
        else:
            self.console.append(
                "Sin puertos series: usa el modo simulación o conecta el receptor USB.", "warn")

    def _apply_startup_options(self) -> None:
        """Respeta ``--port`` / ``--baud`` / ``--sim`` de la línea de comandos."""
        index = self.connection.baud_combo.findData(int(self._initial_baudrate))
        if index >= 0:
            self.connection.baud_combo.setCurrentIndex(index)

        port_index = self.connection.port_combo.findData(self._initial_port or "")
        if port_index >= 0 and self._initial_port:
            self.connection.port_combo.setCurrentIndex(port_index)
        elif self._force_simulation:
            self.connection.port_combo.setCurrentIndex(0)   # "— SIMULACIÓN —"

    def _on_telemetry(self, telemetry) -> None:
        """Actualiza todos los instrumentos con un paquete (slot en hilo GUI)."""
        self.ind_alt.set_value(telemetry.altitude)
        self.ind_vel.set_value(telemetry.velocity)
        self.ind_temp.set_value(telemetry.temperature)
        self.ind_press.set_value(telemetry.pressure)
        self.ind_volt.set_value(telemetry.voltage)
        self.ind_acc.set_value(telemetry.accel)

        self._max_altitude = max(self._max_altitude, telemetry.altitude)
        self.ind_st.set_time(
            telemetry.t,
            f"{telemetry.state_name} · máx {self._max_altitude:.1f} m",
        )

        self.attitude.set_attitude(telemetry.pitch, telemetry.roll, telemetry.yaw)
        self.attitude.set_mission_stage(
            telemetry.satellite, telemetry.chute, telemetry.altitude, telemetry.state
        )
        self.plots.add_sample(telemetry)
        self.web_mirror.publish(telemetry)

        if telemetry.rssi is not None:
            snr_txt = f" SNR {telemetry.snr:+.1f} dB" if telemetry.snr is not None else ""
            self.lbl_rf.setText(f"RF: {telemetry.rssi:.1f} dBm{snr_txt}")
        else:
            self.lbl_rf.setText("RF: —")

        if self._echo:
            rf_echo = (
                f" | RSSI {telemetry.rssi:.1f} dBm SNR {telemetry.snr:+.1f} dB"
                if telemetry.rssi is not None and telemetry.snr is not None
                else ""
            )
            self.console.append(
                f"RX T {telemetry.t:8.2f}s | alt {telemetry.altitude:7.1f} m | "
                f"vel {telemetry.velocity:+6.2f} m/s | acc {telemetry.accel:+6.2f} m/s² | "
                f"{telemetry.temperature:5.1f} °C | {telemetry.pressure:7.2f} hPa | "
                f"{telemetry.voltage:4.2f} V | P{telemetry.pitch:+6.1f} "
                f"R{telemetry.roll:+6.1f} Y{telemetry.yaw:+6.1f} | pkt {telemetry.packet}{rf_echo}",
                "rx")

    def _on_worker_log(self, message: str, level: str) -> None:
        self.console.append(message, level)

    def _on_linked(self, linked: bool, detail: str) -> None:
        self._linked = linked
        self.connection.set_connected(linked, detail)
        self.controls.set_link_active(linked)
        if not linked:
            self.lbl_link.setText("ENLACE: CERRADO")
            self.lbl_link.setStyleSheet(f"color: {Colors.TEXT_FAINT};")
            if self.controls.is_recording:
                self.controls.set_recording(False)
                self.lbl_record.setText("● SIN GRABAR")
                self.lbl_record.setStyleSheet(f"color: {Colors.TEXT_FAINT};")
        else:
            color = Colors.OK if detail.startswith("SIMULADOR") else Colors.ACCENT
            self.lbl_link.setText(f"ENLACE: {detail}")
            self.lbl_link.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _on_stats(self, packets: int, lost: float, rate: float) -> None:
        self.lbl_packets.setText(f"PAQUETES: {packets}")
        self.lbl_loss.setText(f"PERDIDOS: {int(lost)}")
        color = Colors.ERROR if lost > 0 else Colors.TEXT_DIM
        self.lbl_loss.setStyleSheet(f"color: {color};")
        self.lbl_rate.setText(f"CADENCIA: {rate:.1f} Hz")

    def _on_ui_tick(self) -> None:
        """Tarea periódica de la interfaz (no bloquea el hilo de datos)."""
        self.plots.redraw()

    # -------------------------------------------------------------- cierre
    def closeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self._ui_timer.stop()
        if self.controls.is_recording:
            rows = self.worker.stop_recording()
            self.console.append(f"Grabación cerrada al salir ({rows} muestras)", "warn")
        self.web_mirror.stop()
        self.worker.shutdown()
        if self.port_scanner is not None and self.port_scanner.isRunning():
            self.port_scanner.wait(1000)
        super().closeEvent(event)


def _status_label(text: str, color: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {color}; font-family: Consolas, monospace; font-size: 11px;")
    return label


class SpinningBadge3D(QWidget):
    """Medallón 3D giratorio que preserva el arte original PNG de la insignia."""

    def __init__(self, image_path: str, size: int = 52, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size + 8, size + 4)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._size = size
        self._angle = 0.0
        self._pixmap = QPixmap()
        self._edge_pixmap = QPixmap()

        if os.path.exists(image_path):
            raw = QPixmap(image_path)
            if not raw.isNull():
                # Renderizado a 2x para máxima nitidez al rotar
                self._pixmap = raw.scaled(
                    size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                # Silueta acero azulado oscuro para simular el grosor metálico del borde
                edge = QPixmap(self._pixmap.size())
                edge.fill(Qt.transparent)
                p = QPainter(edge)
                p.drawPixmap(0, 0, self._pixmap)
                p.setCompositionMode(QPainter.CompositionMode_SourceIn)
                p.fillRect(edge.rect(), QColor(42, 74, 110, 235))
                p.end()
                self._edge_pixmap = edge

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 FPS suave

    def _tick(self) -> None:
        self._angle = (self._angle + 1.8) % 360.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self._pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        rad = math.radians(self._angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        # Escala horizontal proyectada + espesor de moneda en los cantos
        scale_x = max(0.06, abs(cos_a))
        draw_w = self._size
        draw_h = self._size
        target = QRectF(-draw_w / 2.0, -draw_h / 2.0, draw_w, draw_h)

        # 1. Capas de canto metálico (profundidad 3D al girar de perfil)
        depth_px = 4.2 * abs(sin_a)
        side_dir = -1.0 if sin_a >= 0 else 1.0
        for layer in range(4, 0, -1):
            offset_x = side_dir * depth_px * (layer / 4.0)
            painter.save()
            painter.translate(cx + offset_x, cy)
            tf = QTransform()
            tf.scale(scale_x, 1.0)
            painter.setTransform(tf, True)
            painter.drawPixmap(target, self._edge_pixmap, QRectF(self._edge_pixmap.rect()))
            painter.restore()

        # 2. Cara principal con el arte original íntegro (legible en ambos lados)
        painter.save()
        painter.translate(cx, cy)
        tf = QTransform()
        tf.scale(scale_x, 1.0)
        painter.setTransform(tf, True)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))

        # 3. Reflejo metálico sutil al cruzar el ángulo frontal
        sheen = max(0.0, abs(cos_a) - 0.55) / 0.45
        if sheen > 0.01:
            grad = QLinearGradient(QPointF(-draw_w / 2.0, -draw_h / 2.0),
                                   QPointF(draw_w / 2.0, draw_h / 2.0))
            alpha = int(55 * sheen)
            grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.45, QColor(210, 232, 255, alpha))
            grad.setColorAt(0.55, QColor(255, 255, 255, 0))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            painter.fillRect(target, grad)
        painter.restore()
        painter.end()