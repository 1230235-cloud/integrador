# Hardware, cableado y potencia

## Material

| Elemento | Uso |
|----------|-----|
| Heltec WiFi LoRa 32 V3 (ESP32-S3 + SX1262 915 MHz + OLED) | Ordenador de a bordo de la etapa primaria |
| Heltec WiFi LoRa 32 V3 (segunda unidad) | Receptor/puente LoRa → USB |
| ESP32 genérico + módulo SX1262 suelto | Baliza de la carga secundaria |
| BMP280 | Presión y temperatura |
| BNO080 (9 ejes) | Actitud y aceleración |
| SG90 | Liberación de la secundaria y apertura del autogiro |
| Batería 9 V + regulador Mini360 | Alimentación (ver advertencia) |

## Conexionado de la etapa primaria

El SX1262 y el OLED van **integrados** en la Heltec V3: no se cablean.

| Señal | GPIO | Notas |
|-------|-----:|-------|
| Servo (PWM) | 5 | Señal del SG90; alimentación aparte |
| Zumbador | 6 | Opcional, solo aviso de despliegue |
| ADC batería | 1 | Divisor de tensión, `ADC1_CH0` |
| I²C SDA | 41 | Bus de sensores |
| I²C SCL | 42 | |
| SX1262 NSS | 8 | Interno |
| SX1262 SCK | 9 | Interno |
| SX1262 MOSI | 10 | Interno |
| SX1262 MISO | 11 | Interno |
| SX1262 RST | 12 | Interno |
| SX1262 BUSY | 13 | Interno |
| SX1262 DIO1 | 14 | Interno |
| OLED SDA | 17 | Interno |
| OLED SCL | 18 | Interno |
| OLED RST | 21 | Interno |
| Vext (alimentación auxiliar) | 36 | **LOW = encendida** |

### Direcciones I²C

| Sensor | Dirección | Alternativa |
|--------|-----------|-------------|
| BMP280 | `0x76` | `0x77` (el firmware prueba ambas) |
| BNO080 | `0x4A` | `0x4B` (el firmware prueba ambas) |

El firmware solo activa un sensor si responde; si el BNO080 falla, la misión
continúa con el barómetro y las banderas de telemetría indican `IMU OK = 0`.

### Divisor de batería

```
BAT+ ──[ R1 ]──┬── GPIO1
               │
             [ R2 ]
               │
              GND
```

`DIVISOR_BATERIA = (R1 + R2) / R2` en `firmware/cansat/src/config.hpp`.
Con R1 = R2 = 100 kΩ el divisor es 2,0. Añadir un condensador de 100 nF de
GPIO1 a GND para estabilizar la lectura.

## Alimentación: la parte que hunde los CanSat

### El problema del 9 V

Una pila alcalina de 9 V tiene una resistencia interna de 1–2 Ω. El SG90
consume **700 mA** al arrancar y el SX1262 picos de **120 mA** al transmitir:

* 700 mA × 1,5 Ω ≈ **1 V de caída** instantánea.
* El Mini360 necesita al menos ~1 V de margen sobre su salida: con la pila
  a 2/3 de su vida el regulador entra en *dropout* y el ESP32 se reinicia
  justo en el despliegue.

**Síntoma típico:** el CanSat transmite bien, pero al mover el servo se
reinicia o la telemetría se corta 1–2 s.

### Recomendación

| Solución | Detalle |
|----------|---------|
| **Preferida** | LiPo 2S 300–500 mAh (7,4–8,4 V) → Mini360 a 5,0 V |
| Condensador | **1000 µF** electrolítico en la entrada del regulador y **470 µF** en la salida de 5 V, junto al servo |
| Servo aparte | Alimentar el servo desde la salida de 5 V del regulador con su propia pareja de cables, no desde el pin 3V3 de la placa |
| Masa común | El GND del servo, el del regulador y el de la Heltec deben unirse en un solo punto |

**Nunca** alimentes el SG90 desde el pin `3V3` de la Heltec: su regulador no
entrega los 700 mA del servo.

### Consumo estimado (etapa primaria)

| Bloque | Reposo | Pico |
|--------|-------:|-----:|
| Heltec V3 (ESP32-S3 + LoRa) | 45 mA | 130 mA |
| BMP280 | 1 mA | 1 mA |
| BNO080 | 5 mA | 5 mA |
| SG90 | 20 mA | 700 mA |
| **Total** | **≈ 71 mA** | **≈ 840 mA** |

Con una LiPo 2S de 500 mAh útiles, la etapa primaria aguanta ≈ 6 h en baliza
lenta y ≈ 4 h transmitiendo a 4 Hz; los picos del servo son de milisegundos y
los absorben los condensadores.

## Mecánica del autogiro

El autogiro se dimensiona para que la etapa primaria descienda a **4,7 m/s**:

| Masa de la etapa primaria | Diámetro de rotor | Régimen ≈ |
|--------------------------:|------------------:|----------:|
| 0,25 kg | Ø 400 mm | ≈ 720 rpm |
| 0,30 kg | Ø 430 mm | ≈ 785 rpm |
| 0,35 kg | Ø 460 mm | ≈ 850 rpm |

* 3 palas de perfil plano con **paso negativo** (ala que gira en autorrotación).
* Rodamiento de bolas en el eje; sin él el rotor no arranca y el descenso se
  convierte en caída libre.
* **Prueba de caída obligatoria** desde 10–15 m antes de volar: mide el tiempo
  de descenso y comprueba que el rotor se mantiene girando.

### Secuencia del servo

```
t = 0        servo a 85°  → suelta la etapa secundaria
t = 150 ms   servo a 40°  → libera las palas del autogiro
```

Los 150 ms evitan que la secundaria golpee las palas al caer. El ángulo de
40° es el que deja las palas libres sin golpear el fuselaje; ajústalo en banco
con `SERVO_PALAS` y `SERVO_CARGA2`.

## Etapa secundaria

* Segundo huevo, sin servo ni autogiro.
* Cae libre desde 200 m: **≈ 36 m/s** y **≈ 100 J** de energía de impacto con
  0,15 kg. Un huevo no sobrevive a eso.
* Solución: **freno aerodinámico pasivo** (cono o paracaídas de cinta que se
  abre al soltarse) para bajar a 8–12 m/s, más nido de espuma.
* Baliza: ESP32 genérico + SX1262, antena vertical, batería propia.

Cableado de la baliza (ESP32 genérico, editable en `firmware/baliza/src/main.cpp`):

| Señal SX1262 | GPIO |
|--------------|-----:|
| NSS | 5 |
| DIO1 | 27 |
| RST | 33 |
| BUSY | 26 |
| ADC batería | 34 |

## Antena y montaje

* Antena de latón/PCB **vertical** y libre de masa metálica: el fuselaje no
  debe rodearla.
* Mantén la antena lejos del servo y de los cables de potencia.
* El huevo va en un nido de espuma con holgura de 2–3 mm; el huevo no debe
  tocar paredes rígidas.
* Sujeta la tapa con tornillos, no con cinta: la vibración del dron la suelta.
* Lastra el morro para que la etapa primaria caiga con la antena hacia arriba.

## Limitación: rumbo a la carga secundaria

La etapa primaria estima la **distancia** por RSSI:

```
d = d₀ · 10^((P₀ − RSSI) / (10 · n))
```

con `d₀ = 10 m`, `P₀ = −55 dBm` y `n = 2,4` (ajustables en `config.hpp`).

Con una antena **omnidireccional no hay información de dirección**: el RSSI
depende de la distancia y de la orientación relativa, pero no del rumbo. Para
obtener el rumbo hay dos caminos:

1. **GPS en la baliza** (recomendado): la baliza transmite lat/lon y la
   primaria calcula el rumbo con su propio GPS.
2. **Antena directiva** en la primaria y barrido por rotación: frágil y lento.

Mientras no se añada ninguno, el firmware deja `sec_rumbo_deg = 0xFFFF` y la
estación muestra **«rumbo n/d»**. El campo ya está reservado: no hay que
cambiar el protocolo para añadirlo.
