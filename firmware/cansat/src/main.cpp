// cansat/src/main.cpp — Ordenador de a bordo de la etapa primaria.
//
// Misión: ascenso colgado del dron, caída libre, apertura del autogiro a
// 200 m sobre el punto de suelta, descenso estabilizado y transmisión
// permanente (≥ 10 s tras el aterrizaje, luego baliza lenta).
//
// Bucle principal a 50 Hz. La radio se usa de forma asíncrona para que la
// transmisión (≈ 90 ms) no retrase la detección de los 200 m: a 40 m/s de
// caída libre, cada 10 ms son 40 cm.

#include <Adafruit_BMP280.h>
#include <Arduino.h>
#include <RadioLib.h>
#include <SparkFun_BNO080_Arduino_Library.h>
#include <Wire.h>
#include <math.h>

#include "config.hpp"
#include "enlace.h"

using namespace enlace;

// ------------------------------------------------------------------- objetos
// Pines internos del SX1262 en la Heltec WiFi LoRa 32 V3.
SX1262 radio = new Module(8 /*NSS*/, 14 /*DIO1*/, 12 /*RST*/, 13 /*BUSY*/);

Adafruit_BMP280 bmp;
BNO080 imu;

// ------------------------------------------------------------------- estado
Estado estado = Estado::PRE;
uint8_t banderas = 0;

uint32_t t0Ms = 0;             // inicio de misión
uint32_t tEstadoMs = 0;        // entrada en el estado actual
uint32_t tAterrizajeMs = 0;
uint32_t tUltimaTxMs = 0;
uint32_t tUltimaMuestraMs = 0;
uint16_t secuencia = 0;

float presionSueloPa = 101325.0f;
float presionPa = 101325.0f;
float temperaturaC = 20.0f;
float altitudF = 0.0f;   // filtrada
float velocidadF = 0.0f; // filtrada, + arriba
float altitudMax = 0.0f;
float voltajeV = 8.0f;

float pitchDeg = 0.0f, rollDeg = 0.0f, yawDeg = 0.0f;
float accelVertical = 0.0f;
bool imuValida = false;

float distSecundaria = -1.0f;
bool rumboSecundario = false;
uint16_t rumboSecundariaDeg = 0;

bool autogiroDesplegado = false;
bool secundariaLiberada = false;
bool abortarDespliegue = false;

uint32_t tMuestraAnteriorMs = 0;

bool bmpOk();
bool imuOk();

// ------------------------------------------------------------------ servo
void servoInit() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_SERVO, 50, 16);
#else
  ledcSetup(0, 50, 16);
  ledcAttachPin(PIN_SERVO, 0);
#endif
}

void servoEscribir(float grados) {
  grados = constrain(grados, 0.0f, 180.0f);
  const float pulsoMs = 0.5f + grados / 180.0f * 2.0f;   // 0.5–2.5 ms
  const uint32_t duty = static_cast<uint32_t>(pulsoMs / 20.0f * 65535.0f);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_SERVO, duty);
#else
  ledcWrite(0, duty);
#endif
}

void pitido(uint16_t frecuencia, uint16_t duracionMs) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_BUZZER, frecuencia, 8);
  ledcWriteTone(PIN_BUZZER, frecuencia);
  delay(duracionMs);
  ledcWriteTone(PIN_BUZZER, 0);
  ledcDetach(PIN_BUZZER);
#else
  ledcSetup(1, frecuencia, 8);
  ledcAttachPin(PIN_BUZZER, 1);
  ledcWriteTone(1, frecuencia);
  delay(duracionMs);
  ledcWriteTone(1, 0);
#endif
}

// ------------------------------------------------------------------ sensores
float leerVoltaje() {
  // analogReadMilliVolts promedia internamente la calibración de fábrica.
  const uint32_t mv = analogReadMilliVolts(PIN_BATERIA);
  return static_cast<float>(mv) * DIVISOR_BATERIA / 1000.0f;
}

void calibrarCero() {
  double suma = 0.0;
  uint16_t validas = 0;
  for (uint16_t i = 0; i < MUESTRAS_CALIBRACION; i++) {
    const float p = bmp.readPressure();
    if (isfinite(p) && p > 30000.0f && p < 110000.0f) {
      suma += p;
      validas++;
    }
    delay(10);
  }
  if (validas > 10) {
    presionSueloPa = static_cast<float>(suma / validas);
    altitudF = 0.0f;
    velocidadF = 0.0f;
    Serial.printf("E,cero barometrico %.1f Pa\n", presionSueloPa);
  } else {
    Serial.println("E,no se pudo calibrar el barometro");
  }
}

float altitudBarometrica(float presion) {
  if (presionSueloPa <= 0.0f) return 0.0f;
  return 44330.0f * (1.0f - powf(presion / presionSueloPa, 0.190295f));
}

void rotarPorCuaternion(float qw, float qx, float qy, float qz,
                        float vx, float vy, float vz,
                        float &ox, float &oy, float &oz) {
  const float tx = 2.0f * (qy * vz - qz * vy);
  const float ty = 2.0f * (qz * vx - qx * vz);
  const float tz = 2.0f * (qx * vy - qy * vx);
  ox = vx + qw * tx + (qy * tz - qz * ty);
  oy = vy + qw * ty + (qz * tx - qx * tz);
  oz = vz + qw * tz + (qx * ty - qy * tx);
}

void leerSensores(uint32_t ahora) {
  const float dt = (ahora - tMuestraAnteriorMs) / 1000.0f;
  tMuestraAnteriorMs = ahora;

  // ---------------------------------------------------------- barómetro
  if (bmpOk()) {
    const float p = bmp.readPressure();
    if (isfinite(p) && p > 30000.0f && p < 110000.0f) {
      presionPa = p;
      temperaturaC = bmp.readTemperature();
      const float medida = altitudBarometrica(p);

      // Filtro alpha-beta (equivalente estacionario del Kalman 1-D).
      const float paso = (dt > 0.0f && dt < 0.5f) ? dt : 0.02f;
      const float predicha = altitudF + velocidadF * paso;
      const float residuo = medida - predicha;
      altitudF = predicha + FILTRO_ALPHA * residuo;
      velocidadF += (FILTRO_BETA / paso) * residuo;
      if (altitudF > altitudMax) altitudMax = altitudF;
    }
  }

  // --------------------------------------------------------------- IMU
  if (imuOk() && imu.dataAvailable()) {
    const float p = imu.getPitch();
    const float r = imu.getRoll();
    const float y = imu.getYaw();
    if (isfinite(p) && isfinite(r) && isfinite(y)) {
      pitchDeg = p;
      rollDeg = r;
      yawDeg = fmodf(y + 720.0f, 360.0f);
      imuValida = true;

      float wx, wy, wz;
      rotarPorCuaternion(imu.getQuatReal(), imu.getQuatI(), imu.getQuatJ(),
                         imu.getQuatK(), imu.getAccelX(), imu.getAccelY(),
                         imu.getAccelZ(), wx, wy, wz);
      // En reposo el acelerómetro mide +g en el eje vertical del mundo;
      // restando g queda la aceleración propia (+ arriba).
      accelVertical = SIGNO_EJE_Z * wz - 9.80665f;
    }
  }

  voltajeV = leerVoltaje();
}

bool bmpOk() { return (banderas & BANDERA_BAROMETRO) != 0; }
bool imuOk() { return (banderas & BANDERA_IMU) != 0; }

// ------------------------------------------------------------------ misión
void desplegar(bool automatico) {
  if (autogiroDesplegado) return;

  // 1) soltar la etapa secundaria, 2) abrir las palas. Las banderas se
  // marcan al final del recorrido: así la telemetría registra la altura
  // real de apertura (≈ 200 m) y no la del disparo anticipado.
  servoEscribir(SERVO_CARGA2);
  delay(RETARDO_CARGA2_MS);
  secundariaLiberada = true;
  banderas |= BANDERA_SECUNDARIA;

  servoEscribir(SERVO_PALAS);
  delay(200);  // recorrido mecánico de las palas

  autogiroDesplegado = true;
  banderas |= BANDERA_AUTOGIRO;
  if (automatico) banderas |= BANDERA_DESPLEGUE_AUTO;

  pitido(2700, 350);
  Serial.printf("E,despliegue a %.1f m (%.1f m/s)%s\n", altitudF, velocidadF,
                automatico ? " automatico" : " manual");
}

void actualizarEstado(uint32_t ahora) {
  const uint32_t enEstado = ahora - tEstadoMs;

  switch (estado) {
    case Estado::PRE:
      if (altitudF > ALT_DESPEGUE_M && velocidadF > VEL_ASCENSO_MIN_MS) {
        if (enEstado >= TIEMPO_ASCENSO_MS) {
          estado = Estado::ASCENSO;
          tEstadoMs = ahora;
          Serial.println("E,ascenso detectado");
        }
      } else {
        tEstadoMs = ahora;
      }
      break;

    case Estado::ASCENSO:
      if (velocidadF < -0.5f) {
        if (enEstado >= TIEMPO_APOGEO_MS) {
          estado = Estado::DESCENSO;
          tEstadoMs = ahora;
          Serial.println("E,apogeo: comienza el descenso");
        }
      } else {
        tEstadoMs = ahora;
      }
      break;

    case Estado::DESCENSO: {
      // Disparo predictivo: se adelanta el retardo del servo para que las
      // palas queden abiertas justo al cruzar los 200 m.
      const float retardoM = fabsf(velocidadF) * RETARDO_SERVO_S;
      const float umbral = ALT_DESPLEGUE_M + retardoM + MARGEN_DESPLEGUE_M;
      const bool vueloValido = altitudMax > ALT_MINIMA_VUELO_M;
      const bool cayendo = velocidadF < -3.0f;

      if (!abortarDespliegue && !autogiroDesplegado && vueloValido && cayendo &&
          altitudF <= umbral) {
        desplegar(true);
      }
      if (!abortarDespliegue && !autogiroDesplegado &&
          altitudF < ALT_DESPLEGUE_FORZADO_M) {
        Serial.println("E,despliegue forzado: el disparo predictivo no actuo");
        desplegar(true);
      }
      if (ahora - t0Ms > TIEMPO_FAILSAFE_MS && !autogiroDesplegado) {
        Serial.println("E,despliegue por failsafe de tiempo");
        desplegar(true);
      }

      if (altitudF < ALT_ATERRIZAJE_M && fabsf(velocidadF) < VEL_ATERRIZAJE_MS) {
        if (enEstado >= TIEMPO_ATERRIZAJE_MS) {
          estado = Estado::ATERRIZAJE;
          tEstadoMs = ahora;
          tAterrizajeMs = ahora;
          Serial.println("E,aterrizaje detectado: sigo transmitiendo");
        }
      } else {
        tEstadoMs = ahora;
      }
      break;
    }

    case Estado::ATERRIZAJE:
      if (ahora - tAterrizajeMs >= TIEMPO_POST_ATERRIZAJE_MS) {
        estado = Estado::FIN;
        tEstadoMs = ahora;
        Serial.println("E,fin de transmision rapida: paso a baliza");
      }
      break;

    case Estado::FIN:
      break;
  }
}

// -------------------------------------------------------------------- radio
bool radioListo = false;
bool txEnCurso = false;
uint32_t txInicioMs = 0;

void iniciarRadio() {
  const int16_t st = radio.begin(
      FRECUENCIA_MHZ, ANCHO_BANDA_KHZ, FACTOR_ESPARCIDO, CODIFICACION,
      SYNC_WORD, POTENCIA_DBM, PREAMBULO, TCXO_V);
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("E,radio no inicializada: %d\n", st);
    return;
  }
  radio.setCurrentLimit(140);  // el SX1262 del Heltec admite hasta 140 mA
  radioListo = true;
  Serial.println("E,radio lista");
}

void iniciarTx(uint32_t ahora) {
  if (!radioListo || txEnCurso) return;

  Telemetria t{};
  t.sync0 = SYNC0;
  t.sync1 = SYNC1;
  t.tipo = TIPO_TELEMETRIA;
  t.estado = static_cast<uint8_t>(estado);
  t.banderas = banderas;
  t.secuencia = ++secuencia;
  t.t_ms = ahora - t0Ms;
  t.alt_cm = static_cast<int32_t>(lroundf(altitudF * 100.0f));
  t.vel_cms = static_cast<int32_t>(lroundf(velocidadF * 100.0f));
  t.temp_c100 = static_cast<int16_t>(lroundf(temperaturaC * 100.0f));
  t.pres_pa = static_cast<uint32_t>(lroundf(presionPa));
  t.volt_mv = static_cast<uint16_t>(lroundf(voltajeV * 1000.0f));
  t.pitch_cdeg = static_cast<int16_t>(lroundf(constrain(pitchDeg, -90.0f, 90.0f) * 100.0f));
  t.roll_cdeg = static_cast<int16_t>(lroundf(constrain(rollDeg, -180.0f, 180.0f) * 100.0f));
  t.yaw_cdeg = static_cast<uint16_t>(lroundf(yawDeg * 100.0f));
  t.acc_cmg = static_cast<int16_t>(lroundf(constrain(accelVertical, -80.0f, 80.0f) * 1000.0f));
  t.sec_dist_m = (distSecundaria < 0.0f)
                     ? DISTANCIA_DESCONOCIDA
                     : static_cast<int16_t>(constrain(distSecundaria, 0.0f, 32000.0f));
  t.sec_rumbo_deg = rumboSecundario ? rumboSecundariaDeg : RUMBO_DESCONOCIDO;
  sellar(t);

  if (radio.startTransmit(reinterpret_cast<uint8_t *>(&t), sizeof(t)) ==
      RADIOLIB_ERR_NONE) {
    txEnCurso = true;
    txInicioMs = ahora;
    tUltimaTxMs = ahora;
  }
}

void cerrarTx() {
  if (!txEnCurso) return;
  radio.finishTransmit();
  txEnCurso = false;
}

void aplicarComando(uint8_t cmd, int16_t arg) {
  (void)arg;
  switch (static_cast<Comando>(cmd)) {
    case Comando::CALIBRAR:
      calibrarCero();
      break;
    case Comando::DESPLEGAR:
      desplegar(false);
      break;
    case Comando::ABORTAR:
      abortarDespliegue = true;
      Serial.println("E,despliegue automatico cancelado");
      break;
    case Comando::REINICIAR:
      estado = Estado::PRE;
      tEstadoMs = millis();
      abortarDespliegue = false;
      Serial.println("E,mision reiniciada");
      break;
  }
}

void escuchar(uint16_t ventanaMs) {
  if (!radioListo) return;

  uint8_t buffer[64];
  const int16_t st = radio.receive(buffer, sizeof(buffer), ventanaMs);
  if (st != RADIOLIB_ERR_NONE) return;

  const size_t n = radio.getPacketLength();
  if (n == sizeof(Baliza)) {
    Baliza b{};
    memcpy(&b, buffer, sizeof(b));
    if (!valida(b) || b.tipo != TIPO_BALIZA) return;
    const float rssi = radio.getRSSI();
    // Modelo log-distancia: d = d0 · 10^((P0 − RSSI) / (10·n))
    float d = RSSI_D0_M * powf(10.0f, (RSSI_D0_DBM - rssi) / (10.0f * RSSI_N));
    d = constrain(d, 0.5f, 5000.0f);
    distSecundaria = d;
    banderas |= BANDERA_BALIZA;
    Serial.printf("E,baliza %u rssi %.1f dBm -> %.0f m\n", b.id, rssi, d);
  } else if (n == sizeof(ComandoTrama)) {
    ComandoTrama c{};
    memcpy(&c, buffer, sizeof(c));
    if (valida(c) && c.tipo == TIPO_COMANDO) {
      aplicarComando(c.cmd, c.arg);
    }
  }
}

// ------------------------------------------------------------- comandos USB
String lineaSerie;

void procesarSerie() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (lineaSerie.length() > 0) {
        if (lineaSerie.indexOf("CAL") >= 0) {
          calibrarCero();
        } else if (lineaSerie.indexOf("DEP") >= 0) {
          desplegar(false);
        } else if (lineaSerie.indexOf("CUT") >= 0) {
          abortarDespliegue = true;
          Serial.println("E,despliegue automatico cancelado");
        } else if (lineaSerie.indexOf("RESET") >= 0) {
          aplicarComando(static_cast<uint8_t>(Comando::REINICIAR), 0);
        }
        lineaSerie = "";
      }
    } else if (lineaSerie.length() < 48) {
      lineaSerie += c;
    }
  }
}

// ------------------------------------------------------------------- setup
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("E,CanSat etapa primaria arrancando");

  pinMode(PIN_BATERIA, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_BATERIA, ADC_11db);

  servoInit();
  servoEscribir(SERVO_REPOSO);

  Wire.begin(I2C_SDA, I2C_SCL);

  if (bmp.begin(DIR_BMP280) || bmp.begin(0x77)) {
    bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                    Adafruit_BMP280::SAMPLING_X2,   // temperatura
                    Adafruit_BMP280::SAMPLING_X16,  // presión
                    Adafruit_BMP280::FILTER_X16,
                    Adafruit_BMP280::STANDBY_MS_1);
    banderas |= BANDERA_BAROMETRO;
    Serial.println("E,BMP280 listo");
  } else {
    Serial.println("E,BMP280 no responde");
  }

  if (imu.begin(DIR_BNO080, Wire, 255) || imu.begin(0x4B, Wire, 255)) {
    imu.enableRotationVector(20);
    imu.enableAccelerometer(20);
    banderas |= BANDERA_IMU;
    Serial.println("E,BNO080 listo");
  } else {
    Serial.println("E,BNO080 no responde");
  }

  iniciarRadio();
  calibrarCero();

  t0Ms = millis();
  tEstadoMs = t0Ms;
  tUltimaMuestraMs = t0Ms;
  tMuestraAnteriorMs = t0Ms;
  Serial.println("E,mision armada");
}

// -------------------------------------------------------------------- loop
void loop() {
  const uint32_t ahora = millis();

  procesarSerie();
  // La transmisión es asíncrona: startTransmit deja el radio emitiendo y el
  // bucle sigue muestreando. Solo se cierra cuando ya ha terminado el aire.
  if (txEnCurso && ahora - txInicioMs >= TIEMPO_AEREO_MS) {
    cerrarTx();
  }

  // Muestreo a 50 Hz, independiente de la radio.
  if (ahora - tUltimaMuestraMs >= PERIODO_MUESTREO_MS) {
    tUltimaMuestraMs = ahora;
    leerSensores(ahora);
    actualizarEstado(ahora);
  }

  // Cadencia de telemetría según la fase.
  uint32_t periodo = PERIODO_VUELO_MS;
  if (estado == Estado::PRE) {
    periodo = 1000;
  } else if (estado == Estado::ATERRIZAJE) {
    periodo = 500;
  } else if (estado == Estado::FIN) {
    periodo = PERIODO_BALIZA_MS;
  }

  if (ahora - tUltimaTxMs >= periodo && !txEnCurso) {
    iniciarTx(ahora);
  }

  // La escucha de la baliza solo tiene sentido tras soltar la secundaria.
  // Durante la caída libre no se escucha: cada milisegundo cuenta.
  if (!txEnCurso && estado != Estado::ASCENSO &&
      (estado == Estado::PRE || autogiroDesplegado)) {
    const uint16_t ventana = (estado == Estado::PRE) ? 300 : VENTANA_RX_MS;
    escuchar(ventana);
  }
}
