"""Perfil de vuelo sintético del CanSat, independiente de Qt.

Este módulo concentra la física del simulador para que:

* la estación terrena pueda entrenar sin hardware,
* las pruebas automáticas puedan verificar el perfil sin arrancar la GUI,
* exista una única definición de la misión (450 m de suelta, autogiro a 200 m).

El perfil reproduce la misión real:

======  =====================================================  =====
fase    descripción                                            estado
======  =====================================================  =====
0       ascenso con el dron, 0 → 450 m a 5 m/s                 1
1       caída libre 450 → 200 m (arrastre cuadrático)          2
2       descenso con autogiro 200 → 0 m a 4.7 m/s              2
3       en el suelo, 30 s transmitiendo                        3
4       fin de misión                                          4
======  =====================================================  =====

Uso::

    perfil = FlightProfile()
    telemetria = perfil.sample(t)        # t en segundos de misión
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .protocol import Telemetry

G = 9.80665
#: Gradiente térmico estándar (K/m) y escala barométrica (m).
LAPSO = 0.0065
ESCALA_BAROMETRICA = 8434.5


@dataclass(frozen=True)
class MissionConfig:
    """Parámetros del perfil (prueba de caída desde 30 m con despliegue a 24 m)."""

    alt_suelta: float = 30.0
    alt_despliegue: float = 28.0
    v_ascenso: float = 3.0
    v_autogiro: float = 4.7
    v_terminal_libre: float = 41.0
    t_post_aterrizaje: float = 12.0
    presion_suelo_hpa: float = 1013.25
    temp_suelo_c: float = 24.0
    bateria_inicial_v: float = 8.40
    #: Viento que arrastra la carga secundaria durante su caída (m/s).
    viento_ms: float = 6.0
    rumbo_viento_deg: float = 245.0
    #: Deriva de la etapa primaria bajo el autogiro (m/s).
    deriva_autogiro_ms: float = 4.0
    rumbo_deriva_deg: float = 250.0


class FlightProfile:
    """Perfil de vuelo determinista, función pura del tiempo de misión."""

    def __init__(self, config: MissionConfig | None = None) -> None:
        self.config = config or MissionConfig()
        self.t_ascenso = self.config.alt_suelta / self.config.v_ascenso
        self.t_caida_libre = self._tiempo_de_caida(
            self.config.alt_suelta - self.config.alt_despliegue
        )
        self.t_despliegue = self.t_ascenso + self.t_caida_libre
        self.t_aterrizaje = self.t_despliegue + (
            self.config.alt_despliegue / self.config.v_autogiro
        )
        #: La carga secundaria cae sin paracaídas desde 200 m.
        self.t_aterrizaje_secundaria = self.t_despliegue + self._tiempo_de_caida(
            self.config.alt_despliegue
        )
        self.t_fin = self.t_aterrizaje + self.config.t_post_aterrizaje

    # ------------------------------------------------------------- física
    def _distancia_caida(self, t: float) -> float:
        """Distancia caída en caída libre con arrastre, desde el reposo.

        ``v(t) = v_t · tanh(g·t / v_t)``  ⇒  ``d(t) = (v_t²/g)·ln(cosh(g·t/v_t))``
        """
        vt = self.config.v_terminal_libre
        return (vt * vt / G) * math.log(math.cosh(G * t / vt))

    def _tiempo_de_caida(self, distancia: float) -> float:
        """Invierte :meth:`_distancia_caida` por bisección (monótona)."""
        lo, hi = 0.0, 30.0
        for _ in range(60):
            medio = 0.5 * (lo + hi)
            if self._distancia_caida(medio) < distancia:
                lo = medio
            else:
                hi = medio
        return 0.5 * (lo + hi)

    def altitud(self, t: float) -> float:
        c = self.config
        if t <= 0.0:
            return 0.0
        if t < self.t_ascenso:
            return c.v_ascenso * t
        if t < self.t_despliegue:
            caida = self._distancia_caida(t - self.t_ascenso)
            return max(c.alt_suelta - caida, c.alt_despliegue)
        if t < self.t_aterrizaje:
            return max(c.alt_despliegue - c.v_autogiro * (t - self.t_despliegue), 0.0)
        return 0.0

    def velocidad(self, t: float) -> float:
        """Velocidad vertical (m/s, + arriba). Derivada analítica de la altura."""
        c = self.config
        if t <= 0.0:
            return 0.0
        if t < self.t_ascenso:
            return c.v_ascenso
        if t <= self.t_despliegue:
            vt = c.v_terminal_libre
            return -vt * math.tanh(G * (t - self.t_ascenso) / vt)
        if t < self.t_aterrizaje:
            return -c.v_autogiro
        return 0.0

    def aceleracion(self, t: float, dt: float = 0.01) -> float:
        """Aceleración vertical (m/s², + arriba), derivada numérica central.

        Se limita a ±100 m/s² para que el pico de impacto del modelo no
        ensucie las gráficas ni las pruebas.
        """
        if t <= 0.0:
            return 0.0
        a = (self.velocidad(t + dt) - self.velocidad(t - dt)) / (2.0 * dt)
        return max(-100.0, min(100.0, a))

    # ------------------------------------------------------------ geografía
    def _desplazamiento(self, t: float, velocidad: float, rumbo_deg: float,
                        t_inicio: float, t_fin: float) -> tuple[float, float]:
        """Vector (norte, este) recorrido a ``velocidad`` entre dos instantes."""
        duracion = max(0.0, min(t, t_fin) - t_inicio)
        distancia = velocidad * duracion
        rumbo = math.radians(rumbo_deg)
        return distancia * math.cos(rumbo), distancia * math.sin(rumbo)

    def _posicion(self, t: float, secundaria: bool) -> tuple[float, float]:
        c = self.config
        if secundaria:
            return self._desplazamiento(
                t, c.viento_ms, c.rumbo_viento_deg,
                self.t_despliegue, self.t_aterrizaje_secundaria,
            )
        return self._desplazamiento(
            t, c.deriva_autogiro_ms, c.rumbo_deriva_deg,
            self.t_despliegue, self.t_aterrizaje,
        )

    def distancia_secundaria(self, t: float) -> float:
        """Distancia horizontal (m) de la etapa primaria a la secundaria."""
        n1, e1 = self._posicion(t, secundaria=False)
        n2, e2 = self._posicion(t, secundaria=True)
        return math.hypot(n1 - n2, e1 - e2)

    def rumbo_secundaria(self, t: float) -> float:
        """Rumbo (0-360°, 0 = norte, horario) desde la primaria a la secundaria."""
        n1, e1 = self._posicion(t, secundaria=False)
        n2, e2 = self._posicion(t, secundaria=True)
        dn, de = n2 - n1, e2 - e1
        if abs(dn) < 1e-9 and abs(de) < 1e-9:
            return 0.0
        return (math.degrees(math.atan2(de, dn)) + 360.0) % 360.0

    # ------------------------------------------------------------- estados
    def estado(self, t: float) -> int:
        """Estado según la convención de la estación terrena (0..4)."""
        if t < 0.0:
            return 0
        if t < self.t_ascenso:
            return 1
        if t < self.t_aterrizaje:
            return 2
        if t < self.t_fin:
            return 3
        return 4

    def satelite_desplegado(self, t: float) -> int:
        """1 desde la liberación de la etapa secundaria (200 m)."""
        return int(t >= self.t_despliegue)

    def autogiro_desplegado(self, t: float) -> int:
        """1 desde la apertura del autogiro (0.2 s después del despliegue)."""
        return int(t >= self.t_despliegue + 0.2)

    # ------------------------------------------------------- telemetría
    def sample(self, t: float) -> Telemetry:
        """Construye el paquete de telemetría para el instante ``t``."""
        c = self.config
        alt = self.altitud(t)
        estado = self.estado(t)

        # Ambiente: atmósfera estándar simplificada
        presion = c.presion_suelo_hpa * math.exp(-alt / ESCALA_BAROMETRICA)
        temperatura = c.temp_suelo_c - LAPSO * alt + 0.6 * math.sin(t / 9.0)

        # Batería: caída suave por consumo + escalón al mover el servo
        bateria = c.bateria_inicial_v - 0.35 * (1.0 - math.exp(-t / 400.0))
        if t >= self.t_despliegue:
            bateria -= 0.06 * math.exp(-(t - self.t_despliegue) / 3.0)
        if estado >= 3:
            bateria -= 0.01 * (t - self.t_aterrizaje) / 60.0

        # Actitud: giro lento + oscilación; se estabiliza bajo el autogiro
        if t < self.t_despliegue:
            pitch = 2.0 * math.sin(t / 6.0)
            roll = 3.5 * math.sin(t / 4.0 + 0.7)
            yaw = (t * 11.0) % 360.0
        else:
            pitch = 1.5 * math.sin(t / 3.0)
            roll = 6.0 * math.sin(t / 2.6)  # balanceo del autogiro
            yaw = (self.t_despliegue * 11.0 + (t - self.t_despliegue) * 2.0) % 360.0

        return Telemetry(
            t=float(t),
            altitude=float(max(alt, 0.0)),
            temperature=float(temperatura),
            pressure=float(presion),
            voltage=float(max(bateria, 6.0)),
            pitch=float(pitch),
            roll=float(roll),
            yaw=float(yaw),
            state=estado,
            satellite=self.satelite_desplegado(t),
            chute=self.autogiro_desplegado(t),
            packet=0,  # lo asigna el llamante
            velocity=float(self.velocidad(t)),
            accel=float(self.aceleracion(t)),
            sec_distance=float(self.distancia_secundaria(t)),
            sec_bearing=float(self.rumbo_secundaria(t)),
            rssi=round(-55.0 - 0.08 * max(alt, 0.0), 1),
            snr=round(9.5 - 0.008 * max(alt, 0.0), 1),
        )
