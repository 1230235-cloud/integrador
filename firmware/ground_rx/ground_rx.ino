// ground_rx.ino — Firmware RX / Puente LoRa→USB (Heltec WiFi LoRa 32 V3)
//
// Target arduino-cli: esp32:esp32:heltec_wifi_lora_32_V3
// Librerías requeridas (ya compatibles con arduino-cli lib install):
//   - "RadioLib"
//   - "ESP8266 and ESP32 OLED driver for SSD1306 displays" (SSD1306Wire.h)
//
// Función:
//   - Recibe tramas CSV por LoRa SX1262 a 915.0 MHz desde cansat_tx.ino.
//   - Anexa RSSI (dBm) y SNR (dB) al final de la trama CSV.
//   - Envía la línea CSV limpia por USB Serial a 115200 baudios hacia Python.
//   - Muestra estado del enlace, paquetes, RSSI y SNR en la OLED 0.96".
//   - Reenvía comandos que lleguen por USB Serial (C,CAL,1 / C,DEP,DEPLOY / etc.)
//     hacia el CanSat por LoRa.

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

#include <RadioLib.h>
#include <SSD1306Wire.h>

#include "logo.h"

// ============================================================================
// PINES INTERNOS — HELTEC WIFI LORA 32 V3 (ESP32-S3)
// ============================================================================
constexpr int PIN_OLED_SDA = 17;
constexpr int PIN_OLED_SCL = 18;
constexpr int PIN_OLED_RST = 21;
constexpr int PIN_VEXT     = 36;  // LOW = alimentación OLED habilitada
constexpr uint8_t OLED_ADDR = 0x3C;

constexpr int PIN_LORA_SCK  = 9;
constexpr int PIN_LORA_MISO = 11;
constexpr int PIN_LORA_MOSI = 10;
constexpr int PIN_LORA_CS   = 8;
constexpr int PIN_LORA_DIO1 = 14;
constexpr int PIN_LORA_RST  = 12;
constexpr int PIN_LORA_BUSY = 13;

// ============================================================================
// PARÁMETROS LORA ALTA VELOCIDAD (IDÉNTICOS A cansat_tx.ino)
// ============================================================================
constexpr float    LORA_FREQ_MHZ  = 915.0f;
constexpr float    LORA_BW_KHZ    = 500.0f;
constexpr uint8_t  LORA_SF        = 7;
constexpr uint8_t  LORA_CR        = 5;
constexpr uint8_t  LORA_SYNC_WORD = 0x34;
constexpr int8_t   LORA_POWER_DBM = 20;
constexpr uint16_t LORA_PREAMBLE  = 6;
constexpr float    LORA_TCXO_V    = 1.8f;

constexpr uint8_t FRAME_MAGIC = 0xC5;

#pragma pack(push, 1)
struct TelemetryFrame {
  uint8_t  magic;
  uint8_t  state_flags;
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

constexpr uint32_t SERIAL_BAUD    = 115200;
constexpr uint32_t LINK_TIMEOUT_MS = 3500;
constexpr uint32_t OLED_PERIOD_MS  = 400;

// ============================================================================
// INSTANCIAS Y ESTADO
// ============================================================================
SX1262 radio = new Module(PIN_LORA_CS, PIN_LORA_DIO1, PIN_LORA_RST, PIN_LORA_BUSY);
SSD1306Wire display(OLED_ADDR, PIN_OLED_SDA, PIN_OLED_SCL, GEOMETRY_128_64, I2C_ONE);

volatile bool rxPacketFlag = false;
bool oledReady = false;
bool loraReady = false;
bool linkLost  = true;

uint32_t rxPackets    = 0;
uint32_t lastRxMs     = 0;
uint32_t lastOledMs   = 0;
float lastRssiDbm     = 0.0f;
float lastSnrDb       = 0.0f;
String lastSummary    = "Esperando TX...";
String serialLine;

#if defined(ESP8266) || defined(ESP32)
ICACHE_RAM_ATTR
#endif
void onLoraPacketReceived() {
  rxPacketFlag = true;
}

static void drawTeamSplash(const char *statusLine) {
  if (!oledReady) return;
  display.clear();
  display.drawXbm(0, 0, TEAM_LOGO_WIDTH, TEAM_LOGO_HEIGHT, TEAM_LOGO_XBM);
  display.setFont(ArialMT_Plain_10);
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.drawString(68, 4,  "PEPE EL");
  display.drawString(68, 16, "POLLO");
  display.drawString(68, 32, "CANSAT RX");
  display.drawString(68, 48, statusLine);
  display.display();
}

static void refreshOled(uint32_t nowMs) {
  if (!oledReady) return;
  if (rxPackets == 0) {
    drawTeamSplash(loraReady ? "WAIT 915" : "ERR RF");
    return;
  }

  const bool linked = (nowMs - lastRxMs < LINK_TIMEOUT_MS);
  char line[32];

  display.clear();
  display.setFont(ArialMT_Plain_10);
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  snprintf(line, sizeof(line), "Ground RX %s", linked ? "[OK]" : "[LOST]");
  display.drawString(0, 0, line);

  snprintf(line, sizeof(line), "LoRa %.1f MHz SF%u", LORA_FREQ_MHZ, LORA_SF);
  display.drawString(0, 12, line);

  snprintf(line, sizeof(line), "Pkts: %lu", static_cast<unsigned long>(rxPackets));
  display.drawString(0, 24, line);

  snprintf(line, sizeof(line), "RSSI:%.1f SNR:%.1f", lastRssiDbm, lastSnrDb);
  display.drawString(0, 36, line);

  display.drawString(0, 48, lastSummary);
  display.display();
}

static void processSerialCommands() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      serialLine.trim();
      if (serialLine.length() > 0 && loraReady) {
        if (serialLine.startsWith("C,")) {
          radio.clearDio1Action();
          const int16_t st = radio.transmit(serialLine);
          if (st == RADIOLIB_ERR_NONE) {
            Serial.printf("OK,CMD,%s\r\n", serialLine.c_str());
          } else {
            Serial.printf("E,error TX comando LoRa (%d)\r\n", st);
          }
          radio.setDio1Action(onLoraPacketReceived);
          radio.startReceive();
        }
      }
      serialLine = "";
    } else if (serialLine.length() < 64) {
      serialLine += c;
    }
  }
}

static void processIncomingLora(uint32_t nowMs) {
  if (!rxPacketFlag) return;
  rxPacketFlag = false;

  uint8_t buf[64];
  const size_t len = radio.getPacketLength();
  if (len == 0 || len > sizeof(buf)) {
    radio.startReceive();
    return;
  }

  const int16_t st = radio.readData(buf, len);
  radio.startReceive();

  if (st != RADIOLIB_ERR_NONE) {
    if (st == RADIOLIB_ERR_CRC_MISMATCH) {
      Serial.println("E,trama LoRa con error CRC");
    }
    return;
  }

  lastRssiDbm = radio.getRSSI();
  lastSnrDb   = radio.getSNR();
  rxPackets++;
  lastRxMs = nowMs;

  if (linkLost) {
    linkLost = false;
    Serial.println("E,enlace con el CanSat establecido");
  }

  // Trama binaria de alta velocidad (30 bytes) -> reemite CSV limpio por USB
  if (len == sizeof(TelemetryFrame) && buf[0] == FRAME_MAGIC) {
    TelemetryFrame f{};
    memcpy(&f, buf, sizeof(f));
    const unsigned state = f.state_flags & 0x0F;
    const unsigned sat   = (f.state_flags & (1u << 4)) ? 1u : 0u;
    const unsigned chute = (f.state_flags & (1u << 5)) ? 1u : 0u;
    const float altM     = f.alt_cm / 100.0f;

    Serial.printf(
        "T,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%u,%u,%u,%u,%.2f,%.2f,-1,-1,%.1f,%.1f\r\n",
        f.t_ms / 1000.0f,
        altM,
        f.temp_c100 / 100.0f,
        f.pres_pa / 100.0f,
        f.volt_mv / 1000.0f,
        f.pitch_cdeg / 100.0f,
        f.roll_cdeg / 100.0f,
        f.yaw_cdeg / 100.0f,
        state,
        sat,
        chute,
        static_cast<unsigned>(f.packet),
        f.vel_cms / 100.0f,
        f.acc_cms2 / 100.0f,
        lastRssiDbm,
        lastSnrDb);

    char sum[24];
    snprintf(sum, sizeof(sum), "Alt:%.1fm S:%u %s", altM, state, chute ? "OPEN" : "ARM");
    lastSummary = sum;
    return;
  }

  // Respaldo: tramas de texto/eventos
  String raw;
  raw.reserve(len);
  for (size_t i = 0; i < len; i++) {
    raw += static_cast<char>(buf[i]);
  }
  raw.trim();
  if (raw.length() > 0) {
    Serial.printf("%s\r\n", raw.c_str());
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);

  pinMode(PIN_VEXT, OUTPUT);
  digitalWrite(PIN_VEXT, LOW);
  pinMode(PIN_OLED_RST, OUTPUT);
  digitalWrite(PIN_OLED_RST, LOW);
  delay(20);
  digitalWrite(PIN_OLED_RST, HIGH);
  delay(50);

  oledReady = display.init();
  if (oledReady) {
    display.flipScreenVertically();
    drawTeamSplash("FITEC");
    delay(2500);
  }

  SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_CS);
  const int16_t st = radio.begin(LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR,
                                 LORA_SYNC_WORD, LORA_POWER_DBM, LORA_PREAMBLE,
                                 LORA_TCXO_V, false);
  if (st == RADIOLIB_ERR_NONE) {
    radio.setCRC(true);
    radio.setDio1Action(onLoraPacketReceived);
    radio.startReceive();
    loraReady = true;
    Serial.println("E,receptor LoRa 915 MHz listo");
  } else {
    Serial.printf("E,fallo al iniciar SX1262 (%d)\r\n", st);
    lastSummary = "Error SX1262";
  }

  refreshOled(millis());
}

void loop() {
  const uint32_t nowMs = millis();

  processSerialCommands();
  processIncomingLora(nowMs);

  if (!linkLost && rxPackets > 0 && (nowMs - lastRxMs >= LINK_TIMEOUT_MS)) {
    linkLost = true;
    Serial.println("E,sin telemetria desde hace 3.5 s");
  }

  if (nowMs - lastOledMs >= OLED_PERIOD_MS) {
    lastOledMs = nowMs;
    refreshOled(nowMs);
  }
}
