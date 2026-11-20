// config.hpp — Parámetros de la misión y cableado de la etapa primaria.
//
// Placa: Heltec WiFi LoRa 32 V3 (ESP32-S3FN8, SX1262 915 MHz, OLED 0.96").
// Todo lo que se puede ajustar en campaña vive aquí, no en main.cpp.

#pragma once

#include <stdint.h>

// ------------------------------------------------------------------ cableado
// El SX1262 y el OLED van integrados en la placa: no se cablean.
constexpr int PIN_SERVO = 5;    // señal PWM del SG90
constexpr int PIN_BUZZER = 6;   // aviso sonoro de despliegue
constexpr int PIN_BATERIA = 1;  // ADC del divisor de la batería

constexpr int I2C_SDA = 41;  // bus de sensores (libre en la V3)
constexpr int I2C_SCL = 42;

constexpr uint8_t DIR_BMP280 = 0x76;       // alternativa: 0x77
constexpr uint8_t DIR_BNO080 = 0x4A;       // alternativa: 0x4B

//: Relación del divisor de tensión de la batería (R1+R2)/R2.
constexpr float DIVISOR_BATERIA = 2.0f;

//: El BNO080 se monta con +Z hacia arriba. Si se monta al revés, poner -1.
constexpr float SIGNO_EJE_Z = 1.0f;

// ------------------------------------------------------------ despliegue
//: Altura objetivo sobre el punto de suelta (requisito de la misión).
constexpr float ALT_DESPLEGUE_M = 200.0f;
//: Tiempo que tarda el servo en abrir las palas (s). Se usa para adelantar
//: el disparo: en caída libre se recorre mucho terreno en ese tiempo.
constexpr float RETARDO_SERVO_S = 0.35f;
//: Margen de seguridad adicional (m).
constexpr float MARGEN_DESPLEGUE_M = 2.0f;
//: No se despliega si el vuelo no ha superado esta altura (evita disparos
//: en rampa o por ruido del barómetro).
constexpr float ALT_MINIMA_VUELO_M = 300.0f;
//: Si el disparo predictivo falla, se fuerza a esta altura.
constexpr float ALT_DESPLEGUE_FORZADO_M = 150.0f;
//: Failsafe absoluto: despliegue a los 10 minutos de misión.
constexpr uint32_t TIEMPO_FAILSAFE_MS = 600000UL;

// Ángulos del servo (grados).
constexpr float SERVO_REPOSO = 0.0f;
constexpr float SERVO_CARGA2 = 85.0f;   // suelta la etapa secundaria
constexpr float SERVO_PALAS = 40.0f;    // abre el autogiro
constexpr uint32_t RETARDO_CARGA2_MS = 150;  // entre soltar y abrir palas

// --------------------------------------------------------------- detección
constexpr float ALT_DESPEGUE_M = 15.0f;       // ascenso confirmado
constexpr float VEL_ASCENSO_MIN_MS = 1.5f;
constexpr uint32_t TIEMPO_ASCENSO_MS = 1200;  // sostenido para cambiar de estado
constexpr uint32_t TIEMPO_APOGEO_MS = 800;    // v < 0 sostenida
constexpr float VEL_ATERRIZAJE_MS = 0.35f;
constexpr float ALT_ATERRIZAJE_M = 4.0f;
constexpr uint32_t TIEMPO_ATERRIZAJE_MS = 2000;

// ------------------------------------------------------------- transmisión
constexpr uint32_t PERIODO_VUELO_MS = 250;  // 4 Hz en vuelo
//: Tras aterrizar se mantiene el ritmo alto este tiempo (requisito ≥ 10 s).
constexpr uint32_t TIEMPO_POST_ATERRIZAJE_MS = 30000;
//: Después, baliza lenta hasta agotar batería.
constexpr uint32_t PERIODO_BALIZA_MS = 5000;

// ----------------------------------------------------------------- filtros
//: Frecuencia del lazo de sensores.
constexpr uint32_t PERIODO_MUESTREO_MS = 20;  // 50 Hz
//: Filtro alpha-beta de altitud/velocidad.
constexpr float FILTRO_ALPHA = 0.45f;
constexpr float FILTRO_BETA = 0.06f;
//: Muestras para calibrar el cero barométrico en el suelo.
constexpr uint16_t MUESTRAS_CALIBRACION = 100;

//: Radio de referencia para el modelo log-distancia de RSSI (m).
constexpr float RSSI_D0_M = 10.0f;
//: Potencia recibida esperada a 10 m (dBm), ajustar en campo.
constexpr float RSSI_D0_DBM = -55.0f;
//: Exponente de pérdida de trayecto (2.0 = espacio libre, 2.7 = campo abierto).
constexpr float RSSI_N = 2.4f;
