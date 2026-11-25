// cansat_tx.ino — Firmware TX para CanSat (Heltec WiFi LoRa 32 V3, ESP32-S3)
//
// Target arduino-cli: esp32:esp32:heltec_wifi_lora_32_V3
// Librerías requeridas (ya compatibles con arduino-cli lib install):
//   - "RadioLib"
//   - "Adafruit BMP280 Library"
//   - "Adafruit BNO08x"
//   - "ESP8266 and ESP32 OLED driver for SSD1306 displays" (SSD1306Wire.h)
//
// Misión:
//   - Lectura de BMP280 (0x76 / 0x77) y BNO08x (0x4A / 0x4B) en Wire1 (pines 42/43).
//   - Filtrado de NaN y valores fuera de rango.
//   - Desacoplamiento / apertura de autogiro con servomotor SG90 cerca de 200 m.
//   - Visualización de estado en OLED 0.96" (Wire: SDA=17, SCL=18, RST=21).
//   - Transmisión CSV por LoRa SX1262 a 915.0 MHz compatible con ground_rx.ino y gs/.

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <math.h>

#include <Adafruit_BMP280.h>
#include <Adafruit_BNO08x.h>
#include <RadioLib.h>
#include <SSD1306Wire.h>

// ============================================================================
// CONFIGURACIÓN DE PINES — HELTEC WIFI LORA 32 V3 (ESP32-S3)
// ============================================================================

// --- Bus I2C secundario (Wire1) para sensores BMP280 y BNO08x ---
// Pines 41 (SDA) y 42 (SCL) libres en Heltec V3: no interfieren con la OLED
// (17/18), ni con el SX1262 (8..14), ni con UART0 TX (GPIO 43).
constexpr int PIN_I2C_SDA = 41;
constexpr int PIN_I2C_SCL = 42;
constexpr uint32_t I2C_SENSORS_HZ = 100000;

#define ENABLE_SERIAL_DEBUG 1

#if ENABLE_SERIAL_DEBUG
  #define DBG_PRINT(...)   Serial.print(__VA_ARGS__)
  #define DBG_PRINTLN(...) Serial.println(__VA_ARGS__)
  #define DBG_PRINTF(...)  Serial.printf(__VA_ARGS__)
#else
  #define DBG_PRINT(...)   do {} while (0)
  #define DBG_PRINTLN(...) do {} while (0)
  #define DBG_PRINTF(...)  do {} while (0)
#endif

// --- Direcciones I2C de sensores ---
constexpr uint8_t BMP280_ADDR_PRIMARY = 0x76;
constexpr uint8_t BMP280_ADDR_ALT     = 0x77;
constexpr uint8_t BNO08X_ADDR_PRIMARY = 0x4A;
constexpr uint8_t BNO08X_ADDR_ALT     = 0x4B;

// --- OLED integrada (bus Wire principal, no tocar) ---
constexpr int PIN_OLED_SDA = 17;
constexpr int PIN_OLED_SCL = 18;
constexpr int PIN_OLED_RST = 21;
constexpr int PIN_VEXT     = 36;  // LOW = alimentación OLED habilitada
constexpr uint8_t OLED_ADDR = 0x3C;

// --- Radio SX1262 integrada (no tocar) ---
constexpr int PIN_LORA_SCK  = 9;
constexpr int PIN_LORA_MISO = 11;
constexpr int PIN_LORA_MOSI = 10;
constexpr int PIN_LORA_CS   = 8;
constexpr int PIN_LORA_DIO1 = 14;
constexpr int PIN_LORA_RST  = 12;
constexpr int PIN_LORA_BUSY = 13;

// --- Actuadores y medición de batería ---
constexpr int PIN_SERVO   = 5;   // Señal PWM del SG90 (alimentar desde Mini360 5 V)
constexpr int PIN_BATTERY = 1;   // ADC1_CH0 a través de divisor resistivo
constexpr float BATTERY_DIVIDER = 2.0f;  // (R1 + R2) / R2

// ============================================================================
// PARÁMETROS LORA ALTA VELOCIDAD (IDÉNTICOS EN cansat_tx.ino Y ground_rx.ino)
// ============================================================================
// BW 500 kHz + SF7 + trama binaria de 30 B => ~14 ms en el aire (>2 km LOS),
// permitiendo transmitir a 25 Hz (~60 paquetes en una caída de 2.5 s).
constexpr float    LORA_FREQ_MHZ  = 915.0f;
constexpr float    LORA_BW_KHZ    = 500.0f;
constexpr uint8_t  LORA_SF        = 7;
constexpr uint8_t  LORA_CR        = 5;     // 4/5
constexpr uint8_t  LORA_SYNC_WORD = 0x34;
constexpr int8_t   LORA_POWER_DBM = 20;
constexpr uint16_t LORA_PREAMBLE  = 6;
constexpr float    LORA_TCXO_V    = 1.8f;

constexpr uint8_t FRAME_MAGIC = 0xC5;

#pragma pack(push, 1)
struct TelemetryFrame {
  uint8_t  magic;        // 0xC5
  uint8_t  state_flags;  // bits 0..3: estado, bit 4: secundaria, bit 5: autogiro
  uint16_t packet;
  uint32_t t_ms;
  int32_t  alt_cm;
  int16_t  vel_cms;
  int16_t  acc_cms2;
  int16_t  temp_c100;
  uint32_t pres_pa;
  uint16_t volt_mv;
  int16_t  pitch_cdeg;
  int16_t  roll_cdeg;
  uint16_t yaw_cdeg;
};
#pragma pack(pop)
static_assert(sizeof(TelemetryFrame) == 30, "TelemetryFrame debe medir 30 bytes");

// ============================================================================
// PERFIL DE VUELO (1 = PRUEBA DESDE 30 m | 0 = COMPETENCIA OFICIAL 450 m)
// ============================================================================
#define MODO_PRUEBA_30M 1

#if MODO_PRUEBA_30M
  // Perfil de prueba desde ~30 m: armado temprano y despliegue inmediato al soltar
  constexpr const char *FLIGHT_MODE_TAG = "30M";
  constexpr float ALT_ASCENT_TRIGGER_M  = 6.0f;
  constexpr float VEL_ASCENT_MIN_MS     = 1.0f;
  constexpr uint32_t ASCENT_HOLD_MS     = 600;
  constexpr uint32_t APOGEE_HOLD_MS     = 250;
  constexpr float ALT_MIN_ARM_M         = 12.0f;  // Arma al superar 12 m
  constexpr float ALT_DEPLOY_TARGET_M   = 28.0f;  // Despliega a 28 m en caída desde ~30 m
  constexpr float ALT_FORCE_DEPLOY_M    = 24.0f;  // Respaldo forzado si aún no abrió
  constexpr float VEL_FALL_TRIGGER_MS   = -1.2f;
  constexpr float DEPLOY_MARGIN_M       = 1.0f;
#else
  // Perfil oficial PEUUM: suelta a 450 m, despliegue de autogiro a 200 m
  constexpr const char *FLIGHT_MODE_TAG = "450M";
  constexpr float ALT_ASCENT_TRIGGER_M  = 15.0f;
  constexpr float VEL_ASCENT_MIN_MS     = 1.5f;
  constexpr uint32_t ASCENT_HOLD_MS     = 1200;
  constexpr uint32_t APOGEE_HOLD_MS     = 800;
  constexpr float ALT_MIN_ARM_M         = 300.0f;
  constexpr float ALT_DEPLOY_TARGET_M   = 200.0f;
  constexpr float ALT_FORCE_DEPLOY_M    = 150.0f;
  constexpr float VEL_FALL_TRIGGER_MS   = -3.0f;
  constexpr float DEPLOY_MARGIN_M       = 2.0f;
#endif

constexpr float SERVO_DELAY_S       = 0.35f;
constexpr float SERVO_ANGLE_CLOSED  = 0.0f;
constexpr float SERVO_ANGLE_OPEN    = 85.0f;

constexpr uint32_t SAMPLE_PERIOD_MS    = 15;   // ~66 Hz sensores
constexpr uint32_t TX_PERIOD_PRE_MS    = 200;  // 5 Hz en tierra (con ventana de comandos)
constexpr uint32_t TX_PERIOD_FLIGHT_MS = 40;   // 25 Hz en ascenso y caída (~60 pkts en 2.5 s)
constexpr uint32_t OLED_PERIOD_MS      = 500;  // 2 Hz refresco OLED (pausado en descenso)

// Filtro alpha-beta para altitud y velocidad vertical
constexpr float FILTER_ALPHA = 0.45f;
constexpr float FILTER_BETA  = 0.06f;

// ============================================================================
// INSTANCIAS DE HARDWARE
// ============================================================================
SX1262 radio = new Module(PIN_LORA_CS, PIN_LORA_DIO1, PIN_LORA_RST, PIN_LORA_BUSY);
Adafruit_BMP280 bmp(&Wire1);
Adafruit_BNO08x bno08x(-1);
sh2_SensorValue_t imuEvent;
SSD1306Wire display(OLED_ADDR, PIN_OLED_SDA, PIN_OLED_SCL, GEOMETRY_128_64, I2C_ONE);

// ============================================================================
// ESTADO DE LA MISIÓN
// ============================================================================
enum MissionState : uint8_t {
  STATE_PRE     = 0,
  STATE_ASCENT  = 1,
  STATE_DESCENT = 2,
  STATE_LANDED  = 3,
  STATE_DONE    = 4,
};

bool bmpReady  = false;
bool imuReady  = false;
bool oledReady = false;
bool loraReady = false;
volatile bool loraRxFlag = false;

#if defined(ESP8266) || defined(ESP32)
ICACHE_RAM_ATTR
#endif
void onTxBoardLoraRx() {
  loraRxFlag = true;
}

MissionState missionState = STATE_PRE;
bool chuteDeployed   = false;
bool secondaryFree   = false;
bool deployAborted   = false;

uint32_t missionStartMs   = 0;
uint32_t stateEnteredMs   = 0;
uint32_t landedAtMs       = 0;
uint32_t lastSampleMs     = 0;
uint32_t lastTxMs         = 0;
uint32_t lastOledMs       = 0;
uint32_t packetCounter    = 0;

float groundPressurePa = 101325.0f;
float pressureHpa      = 1013.25f;
float temperatureC     = 20.0f;
float altitudeM        = 0.0f;
float maxAltitudeM     = 0.0f;
float velocityMs       = 0.0f;
float accelVertMs2     = 0.0f;
float voltageV         = 8.4f;

float pitchDeg = 0.0f;
float rollDeg  = 0.0f;
float yawDeg   = 0.0f;

float qW = 1.0f, qX = 0.0f, qY = 0.0f, qZ = 0.0f;
// Cuaternión conjugado de tara (cancela cualquier ángulo de montaje del BNO08x)
float tareQW = 1.0f, tareQX = 0.0f, tareQY = 0.0f, tareQZ = 0.0f;
bool imuTared = false;

// ============================================================================
// UTILIDADES
// ============================================================================
static float sanitizeFloat(float value, float fallback, float minVal, float maxVal) {
  if (!isfinite(value) || value < minVal || value > maxVal) {
    return fallback;
  }
  return value;
}

// Nota ESP32-S3: el hardware LEDC del S3 soporta máximo 14 bits (16 bits falla).
// Usamos 12 bits (0..4095) a 50 Hz, 100 % compatible con ESP32 y ESP32-S3.
constexpr uint8_t  SERVO_PWM_BITS = 12;
constexpr float    SERVO_PWM_MAX  = 4095.0f;

static void servoInit() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_SERVO, 50, SERVO_PWM_BITS);
#else
  ledcSetup(0, 50, SERVO_PWM_BITS);
  ledcAttachPin(PIN_SERVO, 0);
#endif
}

static void servoWriteAngle(float degrees) {
  degrees = constrain(degrees, 0.0f, 180.0f);
  const float pulseMs = 0.5f + (degrees / 180.0f) * 2.0f;
  const uint32_t duty = static_cast<uint32_t>((pulseMs / 20.0f) * SERVO_PWM_MAX);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_SERVO, duty);
#else
  ledcWrite(0, duty);
#endif
}

static float readBatteryVoltage() {
  const uint32_t mv = analogReadMilliVolts(PIN_BATTERY);
  const float v = (static_cast<float>(mv) * BATTERY_DIVIDER) / 1000.0f;
  return sanitizeFloat(v, voltageV, 0.0f, 20.0f);
}

static float computeAltitude(float pressurePa) {
  if (groundPressurePa <= 0.0f || pressurePa <= 0.0f) return 0.0f;
  return 44330.0f * (1.0f - powf(pressurePa / groundPressurePa, 0.190295f));
}

static void calibrateBarometer() {
  if (!bmpReady) return;
  double acc = 0.0;
  uint16_t valid = 0;
  for (uint16_t i = 0; i < 60; i++) {
    const float p = bmp.readPressure();
    if (isfinite(p) && p > 30000.0f && p < 110000.0f) {
      acc += p;
      valid++;
    }
    delay(10);
  }
  if (valid >= 10) {
    groundPressurePa = static_cast<float>(acc / valid);
    altitudeM = 0.0f;
    velocityMs = 0.0f;
    maxAltitudeM = 0.0f;
  }
}

static void enableImuReports() {
  if (!imuReady) return;
  bno08x.enableReport(SH2_ROTATION_VECTOR, 20000);       // 50 Hz
  bno08x.enableReport(SH2_LINEAR_ACCELERATION, 20000);   // 50 Hz
}

static void quatMul(float aw, float ax, float ay, float az,
                    float bw, float bx, float by, float bz,
                    float &ow, float &ox, float &oy, float &oz) {
  ow = aw * bw - ax * bx - ay * by - az * bz;
  ox = aw * bx + ax * bw + ay * bz - az * by;
  oy = aw * by - ax * bz + ay * bw + az * bx;
  oz = aw * bz + ax * by - ay * bx + az * bw;
}

static void tareImuFromCurrent() {
  const float norm = sqrtf(qW * qW + qX * qX + qY * qY + qZ * qZ);
  if (isfinite(norm) && norm > 0.1f) {
    tareQW =  qW / norm;
    tareQX = -qX / norm;
    tareQY = -qY / norm;
    tareQZ = -qZ / norm;
    imuTared = true;
  }
}

static void quatToEulerDeg(float qr, float qi, float qj, float qk,
                           float &outPitch, float &outRoll, float &outYaw) {
  const float sqr = qr * qr;
  const float sqi = qi * qi;
  const float sqj = qj * qj;
  const float sqk = qk * qk;

  const float yawRad = atan2f(2.0f * (qi * qj + qk * qr), (sqi - sqj - sqk + sqr));
  float sinp = -2.0f * (qi * qk - qj * qr) / (sqi + sqj + sqk + sqr);
  sinp = constrain(sinp, -1.0f, 1.0f);
  const float pitchRad = asinf(sinp);
  const float rollRad = atan2f(2.0f * (qj * qk + qi * qr), (-sqi - sqj + sqk + sqr));

  outPitch = sanitizeFloat(pitchRad * RAD_TO_DEG, outPitch, -180.0f, 180.0f);
  outRoll  = sanitizeFloat(rollRad * RAD_TO_DEG, outRoll, -180.0f, 180.0f);
  float y = yawRad * RAD_TO_DEG;
  if (isfinite(y)) {
    y = fmodf(y + 360.0f, 360.0f);
    outYaw = y;
  }
}

static float rotateZToWorld(float qr, float qi, float qj, float qk,
                            float ax, float ay, float az) {
  const float tx = 2.0f * (qj * az - qk * ay);
  const float ty = 2.0f * (qk * ax - qi * az);
  const float tz = 2.0f * (qi * ay - qj * ax);
  return az + qr * tz + (qi * ty - qj * tx);
}

static void deployAutogyro() {
  if (chuteDeployed) return;
  servoWriteAngle(SERVO_ANGLE_OPEN);
  secondaryFree = true;
  chuteDeployed = true;
}

static void testServo() {
  // Prueba en banco sin marcar despliegue: abre a 85°, espera 700 ms y cierra a 0°
  if (loraReady) {
    radio.clearDio1Action();
    radio.transmit("E,servo test GPIO5 ejecutado");
  }
  servoWriteAngle(SERVO_ANGLE_OPEN);
  delay(700);
  servoWriteAngle(SERVO_ANGLE_CLOSED);
  if (loraReady && (missionState == STATE_PRE || missionState == STATE_LANDED)) {
    loraRxFlag = false;
    radio.setDio1Action(onTxBoardLoraRx);
    radio.startReceive();
  }
}

// ============================================================================
// LECTURA DE SENSORES Y MÁQUINA DE ESTADOS
// ============================================================================
static void pollSensors(uint32_t nowMs) {
  const float dt = (nowMs - lastSampleMs) / 1000.0f;
  const float step = (dt > 0.002f && dt < 0.5f) ? dt : 0.02f;
  lastSampleMs = nowMs;

  if (bmpReady) {
    const float pPa = bmp.readPressure();
    const float tC  = bmp.readTemperature();
    if (isfinite(pPa) && pPa > 30000.0f && pPa < 110000.0f) {
      pressureHpa = pPa / 100.0f;
      const float measuredAlt = computeAltitude(pPa);
      if (isfinite(measuredAlt) && measuredAlt > -200.0f && measuredAlt < 5000.0f) {
        const float predicted = altitudeM + velocityMs * step;
        const float residual = measuredAlt - predicted;
        altitudeM = predicted + FILTER_ALPHA * residual;
        velocityMs += (FILTER_BETA / step) * residual;
        if (altitudeM > maxAltitudeM) {
          maxAltitudeM = altitudeM;
        }
      }
    }
    temperatureC = sanitizeFloat(tC, temperatureC, -50.0f, 95.0f);
  }

  if (imuReady) {
    if (bno08x.wasReset()) {
      enableImuReports();
    }
    while (bno08x.getSensorEvent(&imuEvent)) {
      if (imuEvent.sensorId == SH2_ROTATION_VECTOR) {
        const float r = imuEvent.un.rotationVector.real;
        const float i = imuEvent.un.rotationVector.i;
        const float j = imuEvent.un.rotationVector.j;
        const float k = imuEvent.un.rotationVector.k;
        if (isfinite(r) && isfinite(i) && isfinite(j) && isfinite(k)) {
          qW = r; qX = i; qY = j; qZ = k;
          if (!imuTared) {
            tareImuFromCurrent();
          }
          // q_rel = q_sensor * q_tare_conj: cancela cualquier inclinación de montaje
          float rw, rx, ry, rz;
          quatMul(qW, qX, qY, qZ, tareQW, tareQX, tareQY, tareQZ, rw, rx, ry, rz);
          quatToEulerDeg(rw, rx, ry, rz, pitchDeg, rollDeg, yawDeg);
        }
      } else if (imuEvent.sensorId == SH2_LINEAR_ACCELERATION) {
        const float ax = imuEvent.un.linearAcceleration.x;
        const float ay = imuEvent.un.linearAcceleration.y;
        const float az = imuEvent.un.linearAcceleration.z;
        if (isfinite(ax) && isfinite(ay) && isfinite(az)) {
          const float wz = rotateZToWorld(qW, qX, qY, qZ, ax, ay, az);
          accelVertMs2 = sanitizeFloat(wz, accelVertMs2, -160.0f, 160.0f);
        }
      }
    }
  }

  voltageV = readBatteryVoltage();
}

static void updateMissionState(uint32_t nowMs) {
  const uint32_t inStateMs = nowMs - stateEnteredMs;

  switch (missionState) {
    case STATE_PRE:
      if (altitudeM > ALT_ASCENT_TRIGGER_M && velocityMs > VEL_ASCENT_MIN_MS) {
        if (inStateMs >= ASCENT_HOLD_MS) {
          missionState = STATE_ASCENT;
          stateEnteredMs = nowMs;
        }
      } else {
        stateEnteredMs = nowMs;
      }
      break;

    case STATE_ASCENT:
      if (velocityMs < -0.5f) {
        if (inStateMs >= APOGEE_HOLD_MS) {
          missionState = STATE_DESCENT;
          stateEnteredMs = nowMs;
        }
      } else {
        stateEnteredMs = nowMs;
      }
      break;

    case STATE_DESCENT: {
      const float leadM = fabsf(velocityMs) * SERVO_DELAY_S;
      const float triggerM = ALT_DEPLOY_TARGET_M + leadM + DEPLOY_MARGIN_M;
      const bool validFlight = maxAltitudeM > ALT_MIN_ARM_M;
      const bool falling = velocityMs < VEL_FALL_TRIGGER_MS;

      if (!deployAborted && !chuteDeployed && validFlight && falling && altitudeM <= triggerM) {
        deployAutogyro();
      }
      if (!deployAborted && !chuteDeployed && validFlight && altitudeM < ALT_FORCE_DEPLOY_M) {
        deployAutogyro();
      }

      if (altitudeM < 4.0f && fabsf(velocityMs) < 0.35f) {
        if (inStateMs >= 2000) {
          missionState = STATE_LANDED;
          stateEnteredMs = nowMs;
          landedAtMs = nowMs;
        }
      } else {
        stateEnteredMs = nowMs;
      }
      break;
    }

    case STATE_LANDED:
      if (nowMs - landedAtMs >= 30000UL) {
        missionState = STATE_DONE;
        stateEnteredMs = nowMs;
      }
      break;

    case STATE_DONE:
      break;
  }
}

// ============================================================================
// COMANDOS DESDE ESTACIÓN TERRENA Y TELEMETRÍA LORA
// ============================================================================
static void handleGroundCommand(const String &cmd) {
  if (cmd.indexOf("CAL") >= 0) {
    calibrateBarometer();
    tareImuFromCurrent();
  } else if (cmd.indexOf("SERVO") >= 0 || cmd.indexOf("TEST") >= 0) {
    testServo();
  } else if (cmd.indexOf("DEP") >= 0) {
    deployAutogyro();
  } else if (cmd.indexOf("CUT") >= 0 || cmd.indexOf("ABORT") >= 0) {
    deployAborted = true;
  } else if (cmd.indexOf("RESET") >= 0) {
    missionState = STATE_PRE;
    chuteDeployed = false;
    secondaryFree = false;
    deployAborted = false;
    maxAltitudeM = 0.0f;
    missionStartMs = millis();
    stateEnteredMs = missionStartMs;
    servoWriteAngle(SERVO_ANGLE_CLOSED);
  }
}

static void transmitTelemetry(uint32_t nowMs) {
  if (!loraReady) return;

  packetCounter++;

  TelemetryFrame f{};
  f.magic = FRAME_MAGIC;
  f.state_flags = static_cast<uint8_t>(missionState & 0x0F) |
                  (secondaryFree ? (1u << 4) : 0u) |
                  (chuteDeployed ? (1u << 5) : 0u);
  f.packet     = static_cast<uint16_t>(packetCounter & 0xFFFF);
  f.t_ms       = nowMs - missionStartMs;
  f.alt_cm     = static_cast<int32_t>(lroundf(altitudeM * 100.0f));
  f.vel_cms    = static_cast<int16_t>(constrain(lroundf(velocityMs * 100.0f), -32000L, 32000L));
  f.acc_cms2   = static_cast<int16_t>(constrain(lroundf(accelVertMs2 * 100.0f), -32000L, 32000L));
  f.temp_c100  = static_cast<int16_t>(constrain(lroundf(temperatureC * 100.0f), -32000L, 32000L));
  f.pres_pa    = static_cast<uint32_t>(constrain(lroundf(pressureHpa * 100.0f), 0L, 200000L));
  f.volt_mv    = static_cast<uint16_t>(constrain(lroundf(voltageV * 1000.0f), 0L, 65000L));
  f.pitch_cdeg = static_cast<int16_t>(constrain(lroundf(pitchDeg * 100.0f), -32000L, 32000L));
  f.roll_cdeg  = static_cast<int16_t>(constrain(lroundf(rollDeg * 100.0f), -32000L, 32000L));
  f.yaw_cdeg   = static_cast<uint16_t>(constrain(lroundf(yawDeg * 100.0f), 0L, 36000L));

  radio.clearDio1Action();
  radio.transmit(reinterpret_cast<uint8_t *>(&f), sizeof(f));

  // En tierra (PRE/LANDED) dejar el radio escuchando de forma continua entre
  // envíos (por interrupción DIO1) para no perder ningún comando de banco.
  if (missionState == STATE_PRE || missionState == STATE_LANDED) {
    loraRxFlag = false;
    radio.setDio1Action(onTxBoardLoraRx);
    radio.startReceive();
  }
}

static void pollGroundCommands() {
  if (!loraReady || !loraRxFlag) return;
  loraRxFlag = false;

  String rxCmd;
  const int16_t st = radio.readData(rxCmd);
  if (missionState == STATE_PRE || missionState == STATE_LANDED) {
    radio.startReceive();
  }
  if (st == RADIOLIB_ERR_NONE && rxCmd.length() > 0) {
    handleGroundCommand(rxCmd);
  }
}

static void refreshOled() {
  if (!oledReady) return;
  char line[32];
  display.clear();
  display.setFont(ArialMT_Plain_10);
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  snprintf(line, sizeof(line), "TX[%s] S:%u %s",
           FLIGHT_MODE_TAG, static_cast<unsigned>(missionState),
           chuteDeployed ? "OPEN" : "ARM");
  display.drawString(0, 0, line);

  snprintf(line, sizeof(line), "BMP:%s IMU:%s RF:%s",
           bmpReady ? "OK" : "--", imuReady ? "OK" : "--", loraReady ? "OK" : "--");
  display.drawString(0, 12, line);

  snprintf(line, sizeof(line), "Alt:%6.1fm V:%+5.1f", altitudeM, velocityMs);
  display.drawString(0, 24, line);

  snprintf(line, sizeof(line), "T:%4.1fC P:%6.1f", temperatureC, pressureHpa);
  display.drawString(0, 36, line);

  snprintf(line, sizeof(line), "Bat:%4.2fV Pkt:%lu",
           voltageV, static_cast<unsigned long>(packetCounter));
  display.drawString(0, 48, line);

  display.display();
}

// ============================================================================
// SETUP Y LOOP
// ============================================================================
void setup() {
#if ENABLE_SERIAL_DEBUG
  Serial.begin(115200);
  delay(200);
#endif

  // 1. Habilitar alimentación externa Vext y reset de la OLED (Heltec V3)
  pinMode(PIN_VEXT, OUTPUT);
  digitalWrite(PIN_VEXT, LOW);
  pinMode(PIN_OLED_RST, OUTPUT);
  digitalWrite(PIN_OLED_RST, LOW);
  delay(20);
  digitalWrite(PIN_OLED_RST, HIGH);
  delay(50);

  // 2. OLED en bus Wire principal (pines 17 y 18)
  oledReady = display.init();
  if (oledReady) {
    display.flipScreenVertically();
    display.setFont(ArialMT_Plain_10);
    display.clear();
    display.drawString(0, 0, "CanSat TX init...");
    display.display();
  }

  // 3. Servo en posición cerrada y ADC batería
  analogReadResolution(12);
  servoInit();
  servoWriteAngle(SERVO_ANGLE_CLOSED);

  // 4. Bus I2C secundario Wire1 en pines 42 (SDA) y 43 (SCL)
  Wire1.begin(PIN_I2C_SDA, PIN_I2C_SCL, I2C_SENSORS_HZ);

  bmpReady = bmp.begin(BMP280_ADDR_PRIMARY) || bmp.begin(BMP280_ADDR_ALT);
  if (bmpReady) {
    bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                    Adafruit_BMP280::SAMPLING_X2,
                    Adafruit_BMP280::SAMPLING_X16,
                    Adafruit_BMP280::FILTER_X16,
                    Adafruit_BMP280::STANDBY_MS_1);
    calibrateBarometer();
  }

  imuReady = bno08x.begin_I2C(BNO08X_ADDR_PRIMARY, &Wire1) ||
             bno08x.begin_I2C(BNO08X_ADDR_ALT, &Wire1);
  if (imuReady) {
    enableImuReports();
  }

  // 5. Radio LoRa SX1262 a 915.0 MHz
  SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_CS);
  const int16_t st = radio.begin(LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR,
                                 LORA_SYNC_WORD, LORA_POWER_DBM, LORA_PREAMBLE,
                                 LORA_TCXO_V, false);
  if (st == RADIOLIB_ERR_NONE) {
    radio.setCRC(true);
    loraReady = true;
  }

  missionStartMs = millis();
  stateEnteredMs = missionStartMs;
  lastSampleMs = missionStartMs;
  refreshOled();
}

void loop() {
  const uint32_t nowMs = millis();

  pollGroundCommands();

  if (nowMs - lastSampleMs >= SAMPLE_PERIOD_MS) {
    pollSensors(nowMs);
    updateMissionState(nowMs);
  }

  uint32_t txInterval = TX_PERIOD_PRE_MS;
  if (missionState == STATE_ASCENT || missionState == STATE_DESCENT) {
    txInterval = TX_PERIOD_FLIGHT_MS;  // 25 Hz en vuelo
  } else if (missionState == STATE_DONE) {
    txInterval = 2000UL;
  }

  if (nowMs - lastTxMs >= txInterval) {
    lastTxMs = nowMs;
    transmitTelemetry(nowMs);
  }

  // Pausar refresco OLED durante el descenso para no perder milisegundos en I2C
  if (missionState != STATE_DESCENT && (nowMs - lastOledMs >= OLED_PERIOD_MS)) {
    lastOledMs = nowMs;
    refreshOled();
  }
}
