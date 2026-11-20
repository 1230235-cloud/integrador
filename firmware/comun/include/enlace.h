// enlace.h — Enlace LoRa del CanSat: tramas, CRC y parámetros de radio.
//
// Se comparte entre el ordenador de a bordo (cansat), la estación
// repetidora (estacion) y la baliza de la carga secundaria (baliza).
//
// Todas las tramas son little-endian, empaquetadas (sin relleno) y
// terminan en un CRC-16/CCITT calculado sobre los bytes anteriores.

#pragma once

#include <Arduino.h>
#include <stddef.h>
#include <stdint.h>

namespace enlace {

// ------------------------------------------------------------------ constantes
constexpr uint8_t SYNC0 = 0xA5;
constexpr uint8_t SYNC1 = 0x5A;

constexpr uint8_t TIPO_TELEMETRIA = 0x01;
constexpr uint8_t TIPO_COMANDO = 0x02;
constexpr uint8_t TIPO_BALIZA = 0x03;

//: Rumbo desconocido (la carga secundaria aún no se ha oído).
constexpr uint16_t RUMBO_DESCONOCIDO = 0xFFFF;
//: Distancia desconocida.
constexpr int16_t DISTANCIA_DESCONOCIDA = -1;

//: Bits de ``Telemetria::banderas``.
enum Banderas : uint8_t {
  BANDERA_SECUNDARIA = 1u << 0,  // etapa secundaria liberada
  BANDERA_AUTOGIRO = 1u << 1,    // palas desplegadas
  BANDERA_BAROMETRO = 1u << 2,   // BMP280 operativo
  BANDERA_IMU = 1u << 3,         // BNO080 operativo
  BANDERA_BALIZA = 1u << 4,      // se ha oído la baliza secundaria
  BANDERA_DESPLEGUE_AUTO = 1u << 5,  // el despliegue lo decidió el firmware
};

//: Estados de misión, alineados con ``gs/protocol.py``.
enum class Estado : uint8_t {
  PRE = 0,
  ASCENSO = 1,
  DESCENSO = 2,
  ATERRIZAJE = 3,
  FIN = 4,
};

//: Comandos que llegan desde la estación terrestre.
enum class Comando : uint8_t {
  CALIBRAR = 1,   // recalibrar el cero barométrico en el suelo
  DESPLEGAR = 2,  // forzar la apertura del autogiro
  ABORTAR = 3,    // cancelar un despliegue automático pendiente
  REINICIAR = 4,  // reiniciar la misión conservando el cero
};

// ---------------------------------------------------------------- telemetría
#pragma pack(push, 1)

/// Trama de telemetría del CanSat → estación. 42 bytes.
struct Telemetria {
  uint8_t sync0;
  uint8_t sync1;
  uint8_t tipo;      // TIPO_TELEMETRIA
  uint8_t estado;    // enlace::Estado
  uint8_t banderas;  // bits BANDERA_*
  uint8_t reservado;

  uint16_t secuencia;
  uint32_t t_ms;  // tiempo de misión

  int32_t alt_cm;    // altitud sobre el punto de suelta
  int32_t vel_cms;   // velocidad vertical, + arriba
  int16_t temp_c100; // °C × 100
  uint32_t pres_pa;  // presión absoluta en Pa
  uint16_t volt_mv;  // batería en mV

  int16_t pitch_cdeg;  // °  × 100
  int16_t roll_cdeg;
  uint16_t yaw_cdeg;   // 0..35999
  int16_t acc_cmg;     // m/s² × 1000 (aceleración vertical)

  int16_t sec_dist_m;     // distancia a la baliza, -1 si desconocida
  uint16_t sec_rumbo_deg; // 0..359, RUMBO_DESCONOCIDO si no hay

  uint16_t crc;
};

/// Comando estación → CanSat. 8 bytes.
struct ComandoTrama {
  uint8_t sync0;
  uint8_t sync1;
  uint8_t tipo;  // TIPO_COMANDO
  uint8_t cmd;   // enlace::Comando
  int16_t arg;
  uint16_t crc;
};

/// Baliza de la carga secundaria. 12 bytes.
struct Baliza {
  uint8_t sync0;
  uint8_t sync1;
  uint8_t tipo;  // TIPO_BALIZA
  uint8_t id;    // identificador de la carga (1)
  uint16_t secuencia;
  uint16_t volt_mv;
  uint16_t alt_cm;  // altitud estimada por su barómetro (0 si no hay)
  uint16_t crc;
};

#pragma pack(pop)

static_assert(sizeof(Telemetria) == 42, "trama de telemetría inesperada");
static_assert(sizeof(ComandoTrama) == 8, "trama de comando inesperada");
static_assert(sizeof(Baliza) == 12, "trama de baliza inesperada");

// ---------------------------------------------------------------------- CRC
/// CRC-16/CCITT-FALSE (polinomio 0x1021, valor inicial 0xFFFF).
inline uint16_t crc16(const uint8_t *datos, size_t longitud) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < longitud; i++) {
    crc ^= static_cast<uint16_t>(datos[i]) << 8;
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
                           : static_cast<uint16_t>(crc << 1);
    }
  }
  return crc;
}

/// Sella una trama: rellena el campo ``crc`` final.
template <typename T>
inline void sellar(T &trama) {
  trama.crc = crc16(reinterpret_cast<const uint8_t *>(&trama),
                    sizeof(T) - sizeof(trama.crc));
}

/// Comprueba sincronismo y CRC de una trama recibida.
template <typename T>
inline bool valida(const T &trama) {
  if (trama.sync0 != SYNC0 || trama.sync1 != SYNC1) return false;
  return trama.crc ==
         crc16(reinterpret_cast<const uint8_t *>(&trama),
               sizeof(T) - sizeof(trama.crc));
}

// -------------------------------------------------------------------- radio
//: Región 915 MHz (ISM de América). Cambiar a 868.0 en Europa.
constexpr float FRECUENCIA_MHZ = 915.0;
constexpr float ANCHO_BANDA_KHZ = 125.0;
constexpr uint8_t FACTOR_ESPARCIDO = 7;  // SF7
constexpr uint8_t CODIFICACION = 5;      // 4/5
constexpr uint8_t PREAMBULO = 8;
constexpr int8_t POTENCIA_DBM = 14;
constexpr uint8_t SYNC_WORD = 0x12;  // privado del proyecto
constexpr float TCXO_V = 1.8;        // el SX1262 del Heltec V3 lo necesita
constexpr uint32_t TIEMPO_AEREO_MS = 90;  // 42 B a SF7/BW125 ≈ 80 ms

//: Ciclo de radio del bucle de vuelo.
constexpr uint32_t PERIODO_TELEMETRIA_MS = 250;  // 4 Hz
constexpr uint32_t VENTANA_RX_MS = 120;          // escucha de la baliza

}  // namespace enlace
