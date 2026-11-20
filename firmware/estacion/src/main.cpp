// estacion/src/main.cpp — Puente LoRa → USB para la estación terrestre.
//
// Recibe las tramas binarias del CanSat por LoRa y las reescribe como el
// protocolo CSV que entiende ``gs/protocol.py``. En sentido contrario,
// toma las líneas de comando que llegan por USB y las radia al CanSat.
//
// Al ser un puente transparente, la estación terrestre no necesita saber
// nada de LoRa: sigue abriendo un puerto serie a 115200 baudios.

#include <Arduino.h>
#include <RadioLib.h>

#include "enlace.h"

using namespace enlace;

// Pines internos del SX1262 en la Heltec WiFi LoRa 32 V3.
SX1262 radio = new Module(8 /*NSS*/, 14 /*DIO1*/, 12 /*RST*/, 13 /*BUSY*/);

uint32_t ultimoPaqueteMs = 0;
uint32_t paquetes = 0;
bool enlaceCaido = true;
String lineaSerie;

// ------------------------------------------------------------------ salida
void emitirTelemetria(const Telemetria &t) {
  const float alt = t.alt_cm / 100.0f;
  const float vel = t.vel_cms / 100.0f;
  const float acc = t.acc_cmg / 1000.0f;
  const int secDist = (t.sec_dist_m < 0) ? -1 : t.sec_dist_m;
  const float secRumbo = (t.sec_rumbo_deg == RUMBO_DESCONOCIDO)
                             ? -1.0f
                             : static_cast<float>(t.sec_rumbo_deg);

  Serial.printf(
      "T,%.2f,%.2f,%.2f,%.2f,%.3f,%.2f,%.2f,%.2f,%u,%u,%u,%u,%.2f,%.2f,%d,%.1f\r\n",
      t.t_ms / 1000.0f,
      alt,
      t.temp_c100 / 100.0f,
      t.pres_pa / 100.0f,
      t.volt_mv / 1000.0f,
      t.pitch_cdeg / 100.0f,
      t.roll_cdeg / 100.0f,
      t.yaw_cdeg / 100.0f,
      static_cast<unsigned>(t.estado),
      (t.banderas & BANDERA_SECUNDARIA) ? 1u : 0u,
      (t.banderas & BANDERA_AUTOGIRO) ? 1u : 0u,
      static_cast<unsigned>(t.secuencia),
      vel,
      acc,
      secDist,
      secRumbo);
}

// ------------------------------------------------------------------ comandos
void procesarSerie() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (lineaSerie.length() > 0) {
        ComandoTrama cmd{};
        cmd.sync0 = SYNC0;
        cmd.sync1 = SYNC1;
        cmd.tipo = TIPO_COMANDO;

        bool valido = true;
        if (lineaSerie.indexOf("CAL") >= 0) {
          cmd.cmd = static_cast<uint8_t>(Comando::CALIBRAR);
        } else if (lineaSerie.indexOf("DEP") >= 0) {
          cmd.cmd = static_cast<uint8_t>(Comando::DESPLEGAR);
        } else if (lineaSerie.indexOf("CUT") >= 0 ||
                   lineaSerie.indexOf("ABORT") >= 0) {
          cmd.cmd = static_cast<uint8_t>(Comando::ABORTAR);
        } else if (lineaSerie.indexOf("RESET") >= 0) {
          cmd.cmd = static_cast<uint8_t>(Comando::REINICIAR);
        } else {
          valido = false;  // ignorar tramas desconocidas
        }

        if (valido) {
          cmd.arg = 0;
          sellar(cmd);
          const int16_t st =
              radio.transmit(reinterpret_cast<uint8_t *>(&cmd), sizeof(cmd));
          if (st == RADIOLIB_ERR_NONE) {
            Serial.printf("OK,CMD,%u\r\n", static_cast<unsigned>(cmd.cmd));
          } else {
            Serial.printf("E,error al radiar comando %d\r\n", st);
          }
        }
        lineaSerie = "";
      }
    } else if (lineaSerie.length() < 48) {
      lineaSerie += c;
    }
  }
}

// -------------------------------------------------------------------- setup
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("E,receptor LoRa listo");

  const int16_t st = radio.begin(
      FRECUENCIA_MHZ, ANCHO_BANDA_KHZ, FACTOR_ESPARCIDO, CODIFICACION,
      SYNC_WORD, POTENCIA_DBM, PREAMBULO, TCXO_V);
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("E,radio no inicializada: %d\r\n", st);
  } else {
    radio.setCurrentLimit(140);
    radio.startReceive();
  }
}

// --------------------------------------------------------------------- loop
void loop() {
  procesarSerie();

  uint8_t buffer[64];
  const int16_t st = radio.receive(buffer, sizeof(buffer), 200);
  const uint32_t ahora = millis();

  if (st == RADIOLIB_ERR_NONE) {
    const size_t n = radio.getPacketLength();
    if (n == sizeof(Telemetria)) {
      Telemetria t{};
      memcpy(&t, buffer, sizeof(t));
      if (valida(t) && t.tipo == TIPO_TELEMETRIA) {
        emitirTelemetria(t);
        paquetes++;
        ultimoPaqueteMs = ahora;
        if (enlaceCaido) {
          enlaceCaido = false;
          Serial.printf("E,enlace con el CanSat establecido\r\n");
        }
      }
    }
    // Las tramas de baliza recibidas en tierra se ignoran: la distancia
    // solo la calcula el CanSat (es quien la necesita para buscar).
    radio.startReceive();
  }

  if (!enlaceCaido && ahora - ultimoPaqueteMs > 3000) {
    enlaceCaido = true;
    Serial.printf("E,sin telemetria desde hace 3 s (%lu paquetes)\r\n",
                  static_cast<unsigned long>(paquetes));
  }
}
