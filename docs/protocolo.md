# Protocolo de comunicaciones

Hay dos protocolos distintos y conviene no mezclarlos:

1. **CanSat ↔ receptor**: binario, por LoRa (915 MHz).
2. **Receptor ↔ estación terrestre**: texto CSV, por USB.

El receptor traduce del primero al segundo, de modo que la estación terrestre
no necesita saber nada de LoRa.

---

## 1. Enlace LoRa (binario)

### Parámetros de radio

| Parámetro | Valor |
|-----------|-------|
| Frecuencia | 915,0 MHz (ISM América) · usar 868,0 en Europa |
| Ancho de banda | 125 kHz |
| Factor de esparcido | SF7 |
| Codificación | 4/5 |
| Preámbulo | 8 símbolos |
| Potencia | 14 dBm |
| Sync word | `0x12` (privado) |
| TCXO | 1,8 V (obligatorio en la Heltec V3) |

Se fijan en `firmware/comun/include/enlace.h`. **Ambos extremos deben usar
exactamente los mismos valores**: si el sync word o el TCXO no coinciden, el
radio no recibe nada y no hay ningún error visible.

### Trama de telemetría (CanSat → receptor) — 42 bytes

Little-endian, empaquetada, CRC-16/CCITT-FALSE al final.

| Offset | Tipo | Campo | Escala |
|-------:|------|-------|--------|
| 0 | `u8` | `sync0` | `0xA5` |
| 1 | `u8` | `sync1` | `0x5A` |
| 2 | `u8` | `tipo` | `0x01` |
| 3 | `u8` | `estado` | 0…4 |
| 4 | `u8` | `banderas` | bits (abajo) |
| 5 | `u8` | `reservado` | 0 |
| 6 | `u16` | `secuencia` | — |
| 8 | `u32` | `t_ms` | ms de misión |
| 12 | `i32` | `alt_cm` | cm |
| 16 | `i32` | `vel_cms` | cm/s |
| 20 | `i16` | `temp_c100` | °C × 100 |
| 22 | `u32` | `pres_pa` | Pa |
| 26 | `u16` | `volt_mv` | mV |
| 28 | `i16` | `pitch_cdeg` | ° × 100 |
| 30 | `i16` | `roll_cdeg` | ° × 100 |
| 32 | `u16` | `yaw_cdeg` | ° × 100 (0…35999) |
| 34 | `i16` | `acc_cmg` | m/s² × 1000 |
| 36 | `i16` | `sec_dist_m` | m (−1 = desconocida) |
| 38 | `u16` | `sec_rumbo_deg` | ° (0xFFFF = desconocido) |
| 40 | `u16` | `crc` | CRC-16/CCITT |

**Banderas** (`bit`): 0 = secundaria liberada · 1 = autogiro desplegado ·
2 = barómetro OK · 3 = IMU OK · 4 = baliza oída · 5 = despliegue automático.

### Trama de comando (receptor → CanSat) — 8 bytes

| Offset | Tipo | Campo |
|-------:|------|-------|
| 0 | `u8` | `sync0` = `0xA5` |
| 1 | `u8` | `sync1` = `0x5A` |
| 2 | `u8` | `tipo` = `0x02` |
| 3 | `u8` | `cmd` |
| 4 | `i16` | `arg` |
| 6 | `u16` | `crc` |

| `cmd` | Nombre | Efecto |
|------:|--------|--------|
| 1 | `CALIBRAR` | Recalibra el cero barométrico |
| 2 | `DESPLEGAR` | Abre el autogiro ya |
| 3 | `ABORTAR` | Cancela el despliegue automático |
| 4 | `REINICIAR` | Vuelve a PRE conservando el cero |

### Trama de baliza (secundaria → primaria) — 12 bytes

| Offset | Tipo | Campo |
|-------:|------|-------|
| 0 | `u8` | `sync0` = `0xA5` |
| 1 | `u8` | `sync1` = `0x5A` |
| 2 | `u8` | `tipo` = `0x03` |
| 3 | `u8` | `id` (1) |
| 4 | `u16` | `secuencia` |
| 6 | `u16` | `volt_mv` |
| 8 | `u16` | `alt_cm` (0 si no hay barómetro) |
| 10 | `u16` | `crc` |

### CRC-16/CCITT-FALSE

Polinomio `0x1021`, valor inicial `0xFFFF`, sin reflexión ni XOR final:

```c
uint16_t crc16(const uint8_t *d, size_t n) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= (uint16_t)d[i] << 8;
    for (uint8_t b = 0; b < 8; b++)
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  }
  return crc;
}
```

Cálculo equivalente en Python, por si hace falta depurar:

```python
def crc16(datos: bytes) -> int:
    crc = 0xFFFF
    for byte in datos:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc
```

### Temporización

| Fase | Telemetría | Escucha de baliza |
|------|-----------|-------------------|
| PRE | 1 Hz | 300 ms por ciclo |
| ASCENSO | 4 Hz | **no** (cada ms cuenta) |
| DESCENSO antes de desplegar | 4 Hz | **no** |
| DESCENSO con autogiro | 4 Hz | 120 ms tras cada TX |
| ATERRIZAJE (30 s) | 2 Hz | 120 ms |
| FIN | 0,2 Hz | 120 ms |

El tiempo de aire de 42 B a SF7/BW125 es ≈ 90 ms. El CanSat lo gestiona de
forma **asíncrona** (`startTransmit` → muestrear → `finishTransmit`), de modo
que la detección de los 200 m no se retrasa durante la transmisión.

---

## 2. Enlace USB (CSV)

Trama terminada en `\r` o `\n`:

```
T,t,alt,temp,pres,vol,pitch,roll,yaw,state,sat,chute,packet,vel,acc,sec_dist,sec_bear
```

Ejemplo:

```
T,125.40,1042.6,22.8,891.4,8.61,3.1,-2.4,179.8,2,1,1,1254,-4.70,0.12,38.5,-1.0
```

* Las **cuatro últimas columnas son opcionales**. Un firmware de 13 campos
  sigue siendo válido: `gs/protocol.py` rellena `vel=0`, `acc=0`,
  `sec_dist=-1`, `sec_bear=-1`.
* Si un campo numérico llega vacío se usa 0.
* Se rechazan ángulos fuera de ±360° y presiones negativas (se cuentan como
  paquete perdido y se registran en consola).
* `E,<texto>` es un evento; `OK…`, `CMD…`, `ACK…` son confirmaciones.

### Comandos desde la estación

La estación envía las líneas ya existentes en `gs/protocol.py`. El receptor
las reconoce por subcadena y las radia como `ComandoTrama`:

| Línea | Comando |
|-------|---------|
| `C,CAL,1` | CALIBRAR |
| `C,INJ,1` | *(sin efecto)* |
| `C,DEP,DEPLOY` | DESPLEGAR |
| `C,CHUTE,CUT` | ABORTAR |
| `C,SYS,RESET` | REINICIAR |

Las líneas desconocidas se ignoran silenciosamente para no radiar basura.
