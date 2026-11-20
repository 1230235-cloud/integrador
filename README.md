# CanSat · Estación Terrestre y Ordenador de a Bordo

Sistema completo para la misión **CanSat "Satélite Enlatado"**: estación
terrestre en Python (PyQt5 + pyqtgraph), firmware de vuelo para la etapa
primaria, puente LoRa→USB y baliza para la carga secundaria.

La misión se suelta a **450 m**, la etapa primaria abre su **autogiro a 200 m
sobre el punto de suelta**, desciende estabilizada y transmite durante todo el
vuelo y **al menos 10 s tras el aterrizaje**. La etapa secundaria (un segundo
huevo) se libera en el mismo instante y cae libre.

![Dashboard de la estación terrestre](docs/dashboard.png)

---

## Arquitectura

```
   ┌──────────────────────┐         915 MHz          ┌──────────────────────┐
   │  ETAPA PRIMARIA      │        SF7 / BW125       │  RECEPTOR            │
   │  Heltec LoRa V3      │ ───────────────────────▶ │  Heltec LoRa V3      │
   │  BMP280 + BNO080     │ ◀─────────────────────── │  (puente)            │
   │  SG90 (autogiro)     │        comandos          │                      │
   └──────────────────────┘                          └──────────┬───────────┘
              ▲                                                 │ USB 115200
              │ 915 MHz (RSSI)                                  │ CSV
   ┌──────────┴───────────┐                          ┌──────────▼───────────┐
   │  BALIZA SECUNDARIA   │                          │  ESTACIÓN TERRESTRE  │
   │  ESP32 + SX1262      │                          │  Python / PyQt5      │
   │  (segundo huevo)     │                          │  + análisis postvuelo│
   └──────────────────────┘                          └──────────────────────┘
```

* El receptor es **transparente**: la estación terrestre sigue hablando CSV por
  un puerto serie normal, igual que si el CanSat estuviera cableado.
* El enlace binario CanSat↔receptor usa tramas de 42 B con CRC-16 (ver
  [`docs/protocolo.md`](docs/protocolo.md)).

## Estructura del repositorio

```
cansatterraria/
├── main.py                     # arranque de la estación terrestre
├── requirements.txt
├── gs/                         # estación terrestre (Python)
│   ├── protocol.py            #   Telemetry, parseo CSV, comandos
│   ├── flight_profile.py       #   física del vuelo sintético (sin Qt)
│   ├── serial_worker.py        #   hilo de recepción + simulador
│   ├── recording.py            #   grabación CSV thread-safe
│   ├── main_window.py          #   dashboard
│   ├── theme.py
│   └── widgets/                #   indicadores, gráficas, actitud 3D, consola
├── tools/
│   ├── generar_vuelo_sintetico.py   # CSV de vuelo reproducible
│   ├── replay.py                   # inyecta un CSV por puerto serie
│   └── analisis_vuelo.py           # métricas + gráficas + JSON
├── firmware/
│   ├── comun/include/enlace.h  #   tramas, CRC, parámetros de radio
│   ├── cansat/                 #   ordenador de a bordo (etapa primaria)
│   ├── estacion/               #   puente LoRa → USB
│   └── baliza/                 #   baliza de la carga secundaria
├── tests/                      # pytest (protocolo, física, análisis)
└── docs/
    ├── protocolo.md
    ├── hardware.md
    ├── logica-de-vuelo.md
    └── operacion.md
```

## Puesta en marcha rápida

```bash
pip install -r requirements.txt
python main.py --sim            # dashboard con vuelo sintético
```
Sin argumentos, el desplegable de puerto ofrece **— SIMULACIÓN —** y los
puertos COM/TTY detectados. Atajos: `Ctrl+O` conectar · `Ctrl+D` desconectar ·
`Ctrl+R` grabación · `Ctrl+L` limpiar consola.

### Con hardware

1. Flashea el receptor (`firmware/estacion`) y conéctalo por USB al PC.
2. Abre la estación, selecciona el puerto del receptor a **115200** y conecta.
3. Enciende el CanSat: verás `E,enlace con el CanSat establecido` y la
   telemetría a 4 Hz.

## Firmware

Cada proyecto es independiente (PlatformIO):

```bash
cd firmware/cansat    && pio run -t upload     # Heltec LoRa 32 V3 (etapa primaria)
cd firmware/estacion  && pio run -t upload     # Heltec LoRa 32 V3 (receptor)
cd firmware/baliza    && pio run -t upload     # ESP32 genérico + SX1262 (secundaria)
pio device monitor -b 115200
```

Estado verificado de compilación (PlatformIO 6.2, espressif32 8.0.0):

| Proyecto | Flash | RAM |
|----------|-------|-----|
| `cansat` | 11,7 % (391 kB) | 7,8 % (25,6 kB) |
| `estacion` | 10,0 % (336 kB) | 7,2 % (23,4 kB) |
| `baliza` | 23,9 % (314 kB) | 7,2 % (23,5 kB) |

Cableado, presupuesto de potencia y montaje: [`docs/hardware.md`](docs/hardware.md).

## Protocolo de telemetría (CSV)

Trama terminada en `\r` o `\n`. Las cuatro últimas columnas son opcionales:
los firmware antiguos de 13 campos siguen funcionando.

```
T,t,alt,temp,pres,vol,pitch,roll,yaw,state,sat,chute,packet,vel,acc,sec_dist,sec_bear
T,125.40,1042.6,22.8,891.4,8.61,3.1,-2.4,179.8,2,1,1,1254,-4.70,0.12,38.5,-1.0
```

| Campo | Unidad | Descripción |
|-------|--------|-------------|
| `t` | s | Tiempo de misión |
| `alt` | m | Altitud sobre el punto de suelta |
| `temp` | °C | Temperatura |
| `pres` | hPa | Presión atmosférica |
| `vol` | V | Tensión de batería |
| `pitch`, `roll`, `yaw` | ° | Actitud (BNO080) |
| `state` | — | 0 pre-lanzamiento · 1 ascenso · 2 descenso · 3 aterrizaje · 4 fin |
| `sat` | — | Etapa secundaria liberada |
| `chute` | — | Autogiro desplegado |
| `packet` | — | Contador (detecta pérdidas) |
| `vel` | m/s | Velocidad vertical (+ arriba) |
| `acc` | m/s² | Aceleración vertical (+ arriba) |
| `sec_dist` | m | Distancia a la carga secundaria (−1 = sin dato) |
| `sec_bear` | ° | Rumbo a la carga secundaria (−1 = sin dato) |

También se aceptan `E,<texto>` (eventos) y `OK/CMD/ACK` (confirmaciones).
Detalle completo y tramas binarias: [`docs/protocolo.md`](docs/protocolo.md).

### Comandos

| Botón de la estación | Trama enviada | Efecto en el CanSat |
|----------------------|---------------|---------------------|
| Calibrar barómetro | `C,CAL,1` | Fija el cero de altitud en el suelo |
| Desplegar autogiro | `C,DEP,DEPLOY` | Abre el autogiro de inmediato |
| Reiniciar misión | `C,SYS,RESET` | Vuelve a PRE conservando el cero |
| Abortar despliegue | `C,CHUTE,CUT` | Cancela el despliegue automático |

## Funcionalidades de la estación

1. **Panel de conexión** — puerto, baudrate (9600…921600), estado del enlace.
2. **Indicadores** — altitud, velocidad vertical, temperatura, presión,
   batería (alerta < 6,8 V), aceleración vertical, reloj de misión con la
   **altura máxima** y distancia/rumbo a la carga secundaria.
3. **Gráficas** — altitud con la línea de despliegue a 200 m, velocidad y
   aceleración (eje doble) y temperatura/presión. Buffers de 1500 muestras,
   redibujado a 4 Hz.
4. **Actitud 3D** — satélite con mallas OpenGL rotado según pitch/roll/yaw;
   respaldo 2D si no hay OpenGL.
5. **Control y logs** — comandos, grabación CSV, consola con colores.
6. **Hilo dedicado** — `SerialWorker` (QThread) nunca bloquea la interfaz.

## Análisis post-vuelo

```bash
python tools/generar_vuelo_sintetico.py --hz 10 --ruido 0.4
python tools/analisis_vuelo.py grabaciones/vuelo_sintetico.csv --masa 0.30
```

Genera `<nombre>_procesado.csv`, `<nombre>_resumen.json` y las gráficas de
altura, velocidad y actitud. Métricas: altura máxima, instante de apogeo,
altura y error de despliegue, velocidades máxima de ascenso y descenso,
velocidad y energía de impacto, tiempo transmitiendo tras el aterrizaje y
distancia final a la carga secundaria.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 32 pruebas: protocolo, física, troceado y análisis
```

## Cumplimiento de requisitos

| Requisito | Dónde se resuelve |
|-----------|-------------------|
| Presión, temperatura y orientación en vuelo | BMP280 + BNO080 → tramas `T` |
| Aceleración en ascenso y caída libre | BNO080, aceleración vertical en el mundo |
| Velocidad en toda la trayectoria | Filtro alpha-beta sobre el barómetro |
| Altura máxima | `altitudMax` en el CanSat y métrica del análisis |
| Despliegue a 200 m | Disparo predictivo con retardo del servo |
| Dos huevos (primaria y secundaria) | Etapa primaria + baliza independiente |
| ≥ 10 s transmitiendo tras aterrizar | 30 s a 2 Hz y luego baliza lenta |
| Distancia y rumbo a la secundaria | RSSI (distancia) · rumbo: ver limitaciones |
| Entrega de toda la información | CSV grabado + `analisis_vuelo.py` + JSON |

## Limitaciones conocidas

* **Rumbo a la carga secundaria**: con una antena omnidireccional el RSSI da
  distancia, no dirección. El firmware reserva el campo `sec_rumbo_deg` y la
  estación lo muestra como «rumbo n/d» hasta que la baliza lleve GPS o se use
  una antena directiva. Ver [`docs/hardware.md`](docs/hardware.md).
* La distancia por RSSI tiene un error típico de ±30-50 % en campo abierto;
  se calibra con `RSSI_D0_DBM` y `RSSI_N` en `firmware/cansat/src/config.hpp`.
* La batería de 9 V alimenta el servo con mucha caída de tensión; se
  recomienda LiPo 2S + condensador (ver [`docs/hardware.md`](docs/hardware.md)).
* El huevo secundario cae libre desde 200 m (≈ 36 m/s): necesita un freno
  aerodinámico pasivo para sobrevivir.

## Licencia

Uso educativo y de competición. Sin garantías: verifica siempre el montaje y
las pruebas de despliegue en banco antes de volar.
