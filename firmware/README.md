# Firmware

Tres proyectos PlatformIO independientes que comparten
[`comun/include/enlace.h`](comun/include/enlace.h) (tramas, CRC y parámetros
de radio).

| Proyecto | Placa | Función |
|----------|-------|---------|
| `cansat` | Heltec WiFi LoRa 32 V3 | Ordenador de a bordo de la etapa primaria |
| `estacion` | Heltec WiFi LoRa 32 V3 | Puente LoRa → USB (CSV) |
| `baliza` | ESP32 genérico + SX1262 | Baliza de la carga secundaria |

## Compilar y flashear

```bash
cd firmware/cansat
pio run                 # compilar
pio run -t upload       # flashear
pio device monitor -b 115200
```

Repite en `firmware/estacion` y `firmware/baliza`.

Dependencias (las descarga PlatformIO sola):

* `jgromes/RadioLib@^7.2.0` — **no subir a 8.x**: cambió la API de `begin()`.
* `adafruit/Adafruit BMP280 Library` + `Adafruit Unified Sensor`.
* `SparkFun BNO080 Arduino Library` (desde GitHub, no está en el registro).

## Pines

El SX1262 y el OLED de la Heltec V3 van integrados. Lo único que se cablea:

| Señal | GPIO |
|-------|-----:|
| Servo | 5 |
| Zumbador | 6 |
| ADC batería | 1 |
| I²C SDA / SCL | 41 / 42 |

Detalle completo en [`../docs/hardware.md`](../docs/hardware.md).

## Estructura

```
firmware/
├── comun/include/enlace.h   # structs empaquetados, CRC-16, radio
├── cansat/
│   ├── platformio.ini
│   └── src/
│       ├── config.hpp       # TODO lo ajustable en campaña
│       └── main.cpp         # sensores, filtro, máquina de estados, radio
├── estacion/
│   └── src/main.cpp         # binario → CSV, CSV → comandos
└── baliza/
    └── src/main.cpp         # trama BALIZA cada 400 ms
```

## Verificado

Compilado con PlatformIO Core 6.2 y `espressif32@8.0.0`:

| Proyecto | Flash | RAM |
|----------|-------|-----|
| `cansat` | 11,7 % (391 kB) | 7,8 % (25,6 kB) |
| `estacion` | 10,0 % (336 kB) | 7,2 % (23,4 kB) |
| `baliza` | 23,9 % (314 kB) | 7,2 % (23,5 kB) |

## Advertencias

* **No cambies el sync word, el TCXO ni la frecuencia en un solo extremo**:
  el enlace deja de funcionar sin dar ningún error.
* El `delay(150)` del despliegue es intencionado: la secundaria debe caer
  antes de que las palas se abran.
* Si el BNO080 no responde, la misión continúa: el barómetro sigue dando
  altura y velocidad, y la bandera `IMU OK` avisa en tierra.
