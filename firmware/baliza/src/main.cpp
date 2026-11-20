// baliza/src/main.cpp — Baliza de la carga secundaria.
//
// Va dentro del huevo secundario, sin servo ni autogiro. Cada 400 ms emite
// una trama corta con su identificador, contador y tensión de batería.
// La etapa primaria mide el RSSI de esas tramas y estima la distancia.
//
// El ESP32 genérico se cablea al módulo SX1262 con los pines de abajo.

#include <Arduino.h>
#include <RadioLib.h>

#include "enlace.h"

using namespace enlace;

// --------------------------------------------------------------- cableado
constexpr int PIN_NSS = 5;
constexpr int PIN_DIO1 = 27;
constexpr int PIN_RST = 33;
constexpr int PIN_BUSY = 26;
constexpr int PIN_BATERIA = 34;
constexpr float DIVISOR_BATERIA = 2.0f;

constexpr uint8_t ID_CARGA = 1;
constexpr uint32_t PERIODO_MS = 400;

SX1262 radio = new Module(PIN_NSS, PIN_DIO1, PIN_RST, PIN_BUSY);

uint16_t secuencia = 0;
uint32_t ultimaTxMs = 0;

float leerVoltaje() {
  const uint32_t mv = analogReadMilliVolts(PIN_BATERIA);
  return static_cast<float>(mv) * DIVISOR_BATERIA / 1000.0f;
}

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("E,baliza secundaria arrancando");

  analogReadResolution(12);
  analogSetPinAttenuation(PIN_BATERIA, ADC_11db);

  const int16_t st = radio.begin(
      FRECUENCIA_MHZ, ANCHO_BANDA_KHZ, FACTOR_ESPARCIDO, CODIFICACION,
      SYNC_WORD, POTENCIA_DBM, PREAMBULO, TCXO_V);
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("E,radio no inicializada: %d\n", st);
  } else {
    radio.setCurrentLimit(140);
    Serial.println("E,baliza lista");
  }
}

void loop() {
  const uint32_t ahora = millis();
  if (ahora - ultimaTxMs < PERIODO_MS) return;
  ultimaTxMs = ahora;

  Baliza b{};
  b.sync0 = SYNC0;
  b.sync1 = SYNC1;
  b.tipo = TIPO_BALIZA;
  b.id = ID_CARGA;
  b.secuencia = ++secuencia;
  b.volt_mv = static_cast<uint16_t>(leerVoltaje() * 1000.0f);
  b.alt_cm = 0;  // sin barómetro: la altura la aporta la etapa primaria
  sellar(b);

  radio.transmit(reinterpret_cast<uint8_t *>(&b), sizeof(b));
}
