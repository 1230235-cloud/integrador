# Lógica de vuelo

El firmware de la etapa primaria corre un lazo de **50 Hz** con una máquina de
estados de cinco fases. Todo el vuelo se decide a bordo: el enlace no es
imprescindible para que el CanSat abra el autogiro a 200 m.

## Máquina de estados

```
            alt > 15 m  y  v > 1,5 m/s  durante 1,2 s
   ┌────────┐ ─────────────────────────────────────────▶ ┌─────────┐
   │  PRE   │                                            │ ASCENSO │
   └────────┘ ◀───────────────────────────────────────── └─────────┘
        │            comando RESET                        │
        │                                                 │ v < −0,5 m/s durante 0,8 s
        │                                                 ▼
        │                                            ┌──────────┐
        │                                            │ DESCENSO │
        │                                            └──────────┘
        │                                                 │
        │              v < −3 m/s y alt ≤ 200+|v|·0,35+2  │
        │                        ▼                        │
        │                   ┌─────────┐  palas abiertas   │
        │                   │ despliegue │ ───────────────┘
        │                   └─────────┘
        │                                                 │ alt < 4 m y |v| < 0,35 m/s
        │                                                 │ durante 2 s
        │                                                 ▼
        │                                          ┌────────────┐
        │                                          │ ATERRIZAJE │
        │                                          └────────────┘
        │                                                 │ 30 s
        │                                                 ▼
        │                                            ┌──────┐
        └──────────────────────────────────────────  │ FIN  │ (baliza lenta)
                                                     └──────┘
```

## Cronología esperada (misión nominal)

| Evento | Instante | Altura | Velocidad |
|--------|---------:|-------:|----------:|
| Despegue (dron, 5 m/s) | 0 s | 0 m | +5,0 m/s |
| Suelta a 450 m | 90,0 s | 450 m | 0 |
| Inicio de caída libre | 90,0 s | 450 m | 0 |
| **Disparo del despliegue** | 98,5 s | ≈ 216 m | ≈ −39,9 m/s |
| **Apertura del autogiro** | 98,9 s | **≈ 200 m** | ≈ −39,9 m/s |
| Descenso estabilizado | 98,9–141,5 s | 200 → 0 m | −4,7 m/s |
| Aterrizaje | 141,5 s | 0 m | −4,7 m/s |
| Fin de transmisión rápida | 171,5 s | 0 m | 0 |

La etapa secundaria cae libre desde 200 m y llega al suelo en **7,6 s**
(≈ 106,6 s de misión), unos 35 s antes que la primaria.

## Disparo predictivo de los 200 m

En caída libre la etapa baja a **40 m/s**: 4 cm por milisegundo. Si se
disparara el servo al cruzar los 200 m, las palas se abrirían a
`200 − 40 × 0,35 ≈ 186 m`.

Por eso el firmware adelanta el disparo:

```
umbral = 200 + |v| · t_servo + margen
       = 200 + 39,9 · 0,35 + 2,0
       ≈ 216 m
```

`t_servo = 0,35 s` es el tiempo total desde el comando hasta que las palas
están libres (150 ms para soltar la secundaria + 200 ms de recorrido). El
margen de 2 m absorbe el ruido del barómetro y la latencia del filtro.

**Las banderas de despliegue se marcan al final del recorrido**, no al dar la
orden. Así la telemetría registra la altura real de apertura y el análisis
post-vuelo mide el error contra los 200 m con sentido.

### Condiciones de seguridad

El disparo automático exige **todas** estas condiciones:

1. `altitudMax > 300 m` — el vuelo superó la altura mínima (evita disparos en
   rampa o por un golpe de viento).
2. `v < −3 m/s` — está cayendo de verdad.
3. `alt ≤ umbral` — está llegando a los 200 m.

Si a pesar de todo no se dispara:

| Failsafe | Condición | Acción |
|----------|-----------|--------|
| Altura | `alt < 150 m` y sin desplegar | Despliegue forzado |
| Tiempo | `t > 600 s` y sin desplegar | Despliegue forzado |

## Filtro de altitud y velocidad

El BMP280 entrega presión; la altura se calcula con la fórmula barométrica:

```
alt = 44330 · (1 − (p / p₀)^0,190295)
```

donde `p₀` es la presión media de 100 muestras tomadas en el suelo al arrancar
(o al recibir `C,CAL,1`).

La altura y la velocidad se estiman con un **filtro alpha-beta** (la versión
estacionaria del Kalman 1-D):

```
predicha = alt + vel · dt
residuo  = medida − predicha
alt      = predicha + α · residuo
vel      = vel + (β / dt) · residuo
```

con `α = 0,45` y `β = 0,06` (`config.hpp`). Con 50 Hz el filtro suaviza el
ruido del barómetro sin retrasar la detección más de ~60 ms.

## Cadencia de radio

| Fase | Telemetría | Escucha |
|------|-----------|---------|
| PRE | 1 Hz | 300 ms por ciclo |
| ASCENSO | 4 Hz | no |
| DESCENSO (antes de desplegar) | 4 Hz | **no** |
| DESCENSO (con autogiro) | 4 Hz | 120 ms |
| ATERRIZAJE | 2 Hz (30 s) | 120 ms |
| FIN | 0,2 Hz | 120 ms |

Durante el ascenso y la caída libre **no se escucha la baliza**: una ventana
de recepción de 120 ms a 40 m/s son 4,8 m de error en el disparo. La escucha
empieza cuando el autogiro ya está abierto y el descenso es de 4,7 m/s.

## Ajustes de campaña

Todos en `firmware/cansat/src/config.hpp`:

| Constante | Efecto |
|-----------|--------|
| `ALT_DESPLEGUE_M` | Altura objetivo (200 m por reglamento) |
| `RETARDO_SERVO_S` | Tiempo del servo; **medirlo en banco** |
| `MARGEN_DESPLEGUE_M` | Colchón ante ruido |
| `ALT_MINIMA_VUELO_M` | Altura mínima para permitir el disparo |
| `FILTRO_ALPHA` / `FILTRO_BETA` | Suavizado vs respuesta |
| `PERIODO_VUELO_MS` | Cadencia de telemetría |
| `RSSI_D0_DBM` / `RSSI_N` | Calibración de la distancia por RSSI |

## Pruebas de banco antes de volar

1. **Servo**: medir con cronómetro el tiempo desde `C,DEP,DEPLOY` hasta que
   las palas quedan libres; ajustar `RETARDO_SERVO_S` a ese valor.
2. **Barómetro**: subir el CanSat 10 m en ascensor/escalera y comprobar que la
   altura leída es 10 ± 1 m.
3. **Simulación de vuelo**: con una bomba de vacío o jeringa acoplada al
   BMP280, generar una rampa de presión y comprobar que el despliegue salta a
   la altura correcta.
4. **Radio**: separar 100 m en campo abierto y verificar que la estación
   mantiene ≥ 90 % de paquetes.
5. **Caída del autogiro**: desde 10–15 m, medir el tiempo de descenso y que el
   rotor gire hasta el suelo.
