# Operación: de la maleta al informe

## 1. Montaje (día anterior)

- [ ] Cargar las tres baterías al 100 %.
- [ ] Flashear `firmware/cansat`, `firmware/estacion` y `firmware/baliza`.
- [ ] Prueba de despliegue en banco: `C,DEP,DEPLOY` abre las palas en < 1 s.
- [ ] Prueba de radio a 100 m en campo abierto (≥ 90 % de paquetes).
- [ ] Pesar la etapa primaria; comprobar que el rotor es el de la tabla.
- [ ] Nido de espuma de los dos huevos montado y con holgura.

## 2. Antes del despegue (en el campo)

1. Encender el receptor y abrirlo en la estación terrestre (**115200**).
2. Encender el CanSat **en el suelo, quieto, 5 s**: calibra el cero
   barométrico con 100 muestras.
3. Comprobar en la consola:
   - `E,BMP280 listo`, `E,BNO080 listo`, `E,radio lista`;
   - telemetría a 1 Hz con `alt ≈ 0`, `state = 0`;
   - la batería por encima de **7,0 V**.
4. Opcional: pulsar **Calibrar barómetro** otra vez si ha cambiado la presión.
5. Empezar la grabación CSV (**Ctrl+R**) antes de colgar el CanSat del dron.

### Criterios go / no-go

| Comprobación | Go | No-go |
|--------------|----|-------|
| Batería | ≥ 7,0 V | < 6,8 V |
| Presión en reposo | estable ± 0,5 hPa | oscila > 2 hPa |
| Autogiro en banco | abre en < 1 s | roza o no abre |
| Enlace a 100 m | ≥ 90 % paquetes | < 70 % |
| Huevo | encaja sin holgura lateral | golpea paredes |

## 3. Vuelo

No hay que hacer nada durante el vuelo: el CanSat detecta el ascenso, el
apogeo y el descenso por sí solo. En la estación vigila:

* `state` debe pasar 1 → 2 al soltar el dron.
* Alrededor de **200 m** debe aparecer `chute = 1`. Si no, pulsa
  **Desplegar autogiro** (el enlace debe estar vivo).
* Tras el aterrizaje, `state = 3` y la telemetría sigue **≥ 10 s** (son 30 s).
* `sec_dist` empieza a dar valores cuando la primaria oye la baliza.

## 4. Recogida

- [ ] Detener la grabación (**Ctrl+R**) y anotar el nombre del archivo.
- [ ] Recoger la etapa primaria y la secundaria.
- [ ] Comprobar el estado de los huevos **antes** de desmontar.
- [ ] Anotar el punto de impacto de cada etapa respecto al centro de la diana.

## 5. Análisis post-vuelo

```bash
python tools/analisis_vuelo.py grabaciones/vuelo01.csv --masa 0.30
```

Genera:

| Archivo | Contenido |
|---------|-----------|
| `vuelo01_procesado.csv` | `t`, altura y velocidad suavizadas |
| `vuelo01_resumen.json` | todas las métricas del informe |
| `vuelo01_altura.png` | perfil de altura con la línea de 200 m |
| `vuelo01_velocidad.png` | velocidad vertical |
| `vuelo01_actitud.png` | pitch / roll / yaw |

### Métricas que hay que reportar

| Métrica | Clave del JSON |
|---------|----------------|
| Altura máxima | `altura_max_m` |
| Instante de apogeo | `t_apogeo_s` |
| Altura de despliegue | `altura_despliegue_m` |
| Error de despliegue | `error_despliegue_m` |
| Velocidad máx. de ascenso | `vel_max_ascenso_ms` |
| Velocidad máx. de descenso | `vel_max_descenso_ms` |
| Velocidad de impacto | `vel_impacto_ms` |
| Energía de impacto | `energia_impacto_j` |
| Tiempo transmitiendo tras aterrizar | `transmision_post_aterrizaje_s` |
| Distancia final a la secundaria | `sec_distancia_final_m` |
| Rango de actitud | `pitch_rango_deg`, `roll_rango_deg`, `yaw_rango_deg` |

## 6. Diagnóstico rápido

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| La estación no ve el puerto | Driver CP210x | Instalar driver, revisar cable |
| `sin telemetria desde hace 3 s` | Fuera de alcance / antena | Antena vertical, SF mayor |
| Reinicio al mover el servo | Caída de tensión del 9 V | LiPo 2S + condensador 1000 µF |
| `alt` se queda en 0 | Cero calibrado en vuelo | Reiniciar en el suelo, `C,CAL,1` |
| Despliegue a 186 m | `RETARDO_SERVO_S` corto | Medir el servo y ajustarlo |
| No despliega | `altitudMax < 300 m` | Vuelo demasiado bajo; usar `C,DEP,DEPLOY` |
| `rumbo n/d` en la secundaria | Sin GPS en la baliza | Ver `docs/hardware.md` |

## 7. Qué adjuntar al informe

1. `vuelo01_resumen.json` (datos brutos de las métricas).
2. Las tres gráficas PNG.
3. El CSV original **sin recortar**.
4. Foto del montaje y del punto de impacto.
5. Tabla go/no-go firmada antes del lanzamiento.
