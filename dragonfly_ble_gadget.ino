/*
 * ════════════════════════════════════════════════════════════════════════════
 *  DRAGON FLY BLE GADGET v1.0
 *  Firmware para ESP32 + 2× nRF24L01+PA+LNA + OLED SSD1306
 * ════════════════════════════════════════════════════════════════════════════
 *
 *  Controlado vía puerto serie USB a 115200 baud desde Raspberry Pi.
 *  Compatible con gadget_handler.py (Python / pyserial).
 *
 *  PROTOCOLO DE COMANDOS (líneas terminadas en \n):
 *  ─────────────────────────────────────────────────────────────────────────
 *  SCAN <mod> <seg>             → SCANNING_STARTED
 *                                 DEVICE:<mac>,<rssi>,<nombre>  (múltiples)
 *                                 SCAN_DONE | STOPPED
 *
 *  STOP <mod>                   → STOPPED
 *
 *  ADVERTISE <mod> <mensaje>    → ADVERTISING_STARTED
 *
 *  BEACON_FLOOD <mod> <n> <ms>  → FLOODING_STARTED
 *                                 FLOOD_DONE (si n > 0 y terminó)
 *
 *  JAM <mod> <canal> <seg>      → JAMMING_STARTED   [stub, sin RF]
 *                                 JAM_DONE | STOPPED
 *
 *  SWEEP_JAM <mod> <seg>        → SWEEP_JAMMING_STARTED  [stub, sin RF]
 *                                 SWEEP_DONE | STOPPED
 *
 *  STATUS                       → MOD0:<estado> MOD1:<estado>
 *
 *  CONEXIONES DE HARDWARE:
 *  ─────────────────────────────────────────────────────────────────────────
 *  OLED SSD1306 (I2C):  SDA→GPIO4   SCL→GPIO5   VCC→3.3 V  GND→GND
 *  nRF24 #0 (HSPI):     SCK→GPIO14  MISO→GPIO12 MOSI→GPIO13
 *                        CSN→GPIO15  CE→GPIO16   VCC→3.3 V  GND→GND
 *  nRF24 #1 (VSPI):     SCK→GPIO18  MISO→GPIO19 MOSI→GPIO23
 *                        CSN→GPIO21  CE→GPIO22   VCC→3.3 V  GND→GND
 *
 *  LIBRERÍAS REQUERIDAS (instalar desde el gestor de librerías de Arduino):
 *    • RF24   de TMRh20  ≥ 1.4.7
 *    • U8g2   de olikraus ≥ 2.35
 *
 *  NOTAS DE DISEÑO:
 *    • Las funciones JAM y SWEEP_JAM son stubs intencionales: responden el
 *      protocolo correctamente para compatibilidad con gadget_handler.py,
 *      pero NO emiten portadora de RF (startConstCarrier omitido por
 *      restricciones legales de interferencia de RF).
 *    • Todo el loop es no bloqueante (sin delay()); se usan millis() y
 *      máquinas de estado.
 *    • Implementación BLE sobre nRF24 basada en la técnica de Dmitry Grinberg
 *      (reversión de bits, data-whitening BLE, CRC24 BLE).
 * ════════════════════════════════════════════════════════════════════════════
 */

#include <SPI.h>
#include <Wire.h>
#include <RF24.h>
#include <U8g2lib.h>

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  PINES                                                                   ║
// ╚══════════════════════════════════════════════════════════════════════════╝

#define PIN_OLED_SDA  4
#define PIN_OLED_SCL  5

#define PIN_CE0       16    // nRF24 #0  Chip Enable
#define PIN_CSN0      15    // nRF24 #0  Chip Select
#define PIN_SCK0      14    // HSPI SCK
#define PIN_MISO0     12    // HSPI MISO
#define PIN_MOSI0     13    // HSPI MOSI

#define PIN_CE1       22    // nRF24 #1  Chip Enable
#define PIN_CSN1      21    // nRF24 #1  Chip Select
#define PIN_SCK1      18    // VSPI SCK
#define PIN_MISO1     19    // VSPI MISO
#define PIN_MOSI1     23    // VSPI MOSI

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  CONSTANTES BLE                                                          ║
// ╚══════════════════════════════════════════════════════════════════════════╝

/*
 *  Mapeo de canales BLE de advertising → canal RF24.
 *  RF24 usa frecuencias de 2400 + N MHz (canal 0–125).
 *    BLE ch37 = 2402 MHz → RF24 ch  2
 *    BLE ch38 = 2426 MHz → RF24 ch 26
 *    BLE ch39 = 2480 MHz → RF24 ch 80
 */
static const uint8_t kBleRfCh[3]  = {2, 26, 80};
static const uint8_t kBleAdvCh[3] = {37, 38, 39};  // Número real de canal BLE (para whitening)

/*
 *  Access Address de advertising BLE: 0x8E89BED6.
 *  Para que el nRF24 lo reconozca, cada byte se invierte bit a bit:
 *    D6 → 6B,  BE → 7D,  89 → 91,  8E → 71
 *  Ref: Dmitry Grinberg – "Faking Bluetooth LE with nRF24L01+"
 */
static const uint8_t kBleAddrNrf[4] = {0x6B, 0x7D, 0x91, 0x71};

// Intervalos de temporización (ms)
#define SCAN_HOP_MS         100   // Frecuencia de cambio de canal durante escaneo
#define ADV_INTERVAL_MS     200   // Intervalo entre paquetes de advertising
#define OLED_REFRESH_MS     500   // Frecuencia de refresco de la OLED

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  OBJETOS GLOBALES                                                        ║
// ╚══════════════════════════════════════════════════════════════════════════╝

// OLED: HW I2C; los pines se asignan en setup() con Wire.begin()
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// Buses SPI separados para no tener conflictos entre módulos
SPIClass spi0(HSPI);
SPIClass spi1(VSPI);

// Objetos RF24 (CE, CSN)
RF24 radio0(PIN_CE0, PIN_CSN0);
RF24 radio1(PIN_CE1, PIN_CSN1);

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  MÁQUINA DE ESTADOS                                                      ║
// ╚══════════════════════════════════════════════════════════════════════════╝

enum ModState : uint8_t {
    MOD_IDLE,
    MOD_SCANNING,
    MOD_ADVERTISING,
    MOD_FLOODING,
    MOD_JAMMING,        // stub
    MOD_SWEEP_JAMMING   // stub
};

struct RadioModule {
    RF24*     radio;        // Puntero al objeto RF24 asociado
    ModState  state;        // Estado actual
    char      tag[12];      // Etiqueta corta para OLED / STATUS

    // ── SCAN ──────────────────────────────────────────────────────────────
    unsigned long scanStart;      // Timestamp de inicio del escaneo (ms)
    unsigned long scanDuration;   // Duración total (ms); 0 = hasta STOP
    uint8_t       scanChIdx;      // Índice 0-2 en kBleRfCh (canal actual)
    unsigned long lastHop;        // Último cambio de canal (ms)

    // ── ADVERTISE ─────────────────────────────────────────────────────────
    char     advMsg[64];    // Mensaje personalizado
    uint8_t  advMAC[6];     // MAC propia (aleatoria, generada una vez)
    unsigned long lastAdv;  // Último envío de advertising (ms)

    // ── FLOOD ─────────────────────────────────────────────────────────────
    int           floodCount;     // Número de beacons a enviar (0 = infinito)
    int           floodSent;      // Enviados hasta ahora
    unsigned long floodInterval;  // Intervalo entre beacons (ms)
    unsigned long lastFlood;      // Último beacon enviado (ms)

    // ── JAM / SWEEP (stub) ────────────────────────────────────────────────
    unsigned long jamStart;       // Inicio de la operación (ms)
    unsigned long jamDuration;    // Duración (ms); 0 = hasta STOP
};

RadioModule mod[2];

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  SERIAL                                                                  ║
// ╚══════════════════════════════════════════════════════════════════════════╝

static char serialBuf[256];
static int  serialPos = 0;

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  NOMBRES PARA FLOOD                                                      ║
// ╚══════════════════════════════════════════════════════════════════════════╝

static const char* const kNames[] = {
    "iPhone 15",  "Galaxy S24",  "Pixel 8",    "AirPods Pro",
    "Mi Band 8",  "Fitbit",      "GalaxyWatch", "JBL Go 4",
    "MacBook Air","ThinkPad X1", "iPad Pro",    "Kindle",
    "Xbox Ctrl",  "PS5 Ctrl",   "Bose QC45",   "Sony WH-1000"
};
static const uint8_t kNamesCount = sizeof(kNames) / sizeof(kNames[0]);

static unsigned long lastOledRefresh = 0;

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  UTILIDADES BLE (técnica Dmitry Grinberg)                                ║
// ╚══════════════════════════════════════════════════════════════════════════╝

/**
 * Invierte los 8 bits de un byte.
 * nRF24L01 envía los bits de cada byte en orden invertido respecto a BLE,
 * por lo que todos los bytes del paquete deben procesarse con esta función
 * antes de transmitir (TX) y después de recibir (RX).
 */
static inline uint8_t reverseByte(uint8_t b) {
    b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4);
    b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2);
    b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1);
    return b;
}

/**
 * Calcula el coeficiente de whitening para un canal BLE dado.
 * Según la implementación de referencia de Dmitry Grinberg.
 */
static uint8_t whitenCoeff(uint8_t bleCh) {
    return reverseByte(bleCh) | 2;
}

/**
 * Aplica data-whitening BLE al buffer in-place.
 * Cada canal BLE usa una semilla diferente derivada de su número.
 * Se llama tanto antes de transmitir (TX) como después de recibir (RX)
 * (la operación es su propio inverso al ser XOR).
 */
static void bleWhiten(uint8_t* data, uint8_t len, uint8_t bleCh) {
    uint8_t coeff = whitenCoeff(bleCh);
    for (uint8_t i = 0; i < len; i++) {
        uint8_t m;
        for (m = 1; m; m <<= 1) {
            if (coeff & 0x80) {
                coeff ^= 0x11;
                data[i] ^= m;
            }
            coeff <<= 1;
        }
    }
}

/**
 * Calcula el CRC24 BLE.
 * Polinomio: x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1 (0x65B).
 * Seed inicial: 0x555555.
 */
static uint32_t bleCRC24(const uint8_t* data, uint8_t len) {
    uint32_t crc = 0x555555;
    while (len--) {
        crc ^= ((uint32_t)(*data++)) << 16;
        for (uint8_t i = 0; i < 8; i++) {
            crc <<= 1;
            if (crc & 0x1000000) crc ^= 0x65B;
        }
    }
    return crc & 0xFFFFFF;
}

/**
 * Construye un paquete de advertising BLE completo listo para transmitir
 * con el nRF24 (con inversión de bits y whitening ya aplicados).
 *
 * Parámetros:
 *   out      : buffer de salida (mínimo 32 bytes)
 *   mac      : 6 bytes de AdvA (MAC de origen)
 *   name     : nombre del dispositivo (Complete Local Name, hasta 24 chars)
 *   chIdx    : índice 0-2 en kBleAdvCh[] (para whitening correcto)
 *
 * Retorna: longitud del paquete en bytes (máximo 32).
 *
 * Estructura interna antes de whitening/reversión:
 *   [PDU Header][PDU Len][MAC×6][AD: len, 0x09, name...][CRC×3]
 */
static uint8_t buildAdvPacket(uint8_t* out, const uint8_t* mac,
                               const char* name, uint8_t chIdx) {
    uint8_t bleCh = kBleAdvCh[chIdx];
    uint8_t namelen = (uint8_t)strlen(name);
    if (namelen > 24) namelen = 24;

    // PDU Header:
    //   Bits [3:0] = tipo PDU: ADV_NONCONN_IND (0b0010)
    //   Bit 6      = TxAdd = 1 (dirección aleatoria)
    //   → byte = 0x42
    uint8_t pdu[40];
    uint8_t pLen = 0;
    pdu[pLen++] = 0x42;

    // Longitud del PDU: AdvA(6) + AD_structure(2+namelen)
    uint8_t pduPayloadLen = 6 + (namelen > 0 ? (2 + namelen) : 0);
    pdu[pLen++] = pduPayloadLen;

    // AdvA: MAC en orden inverso (BLE la envía LSB first)
    for (int i = 5; i >= 0; i--) pdu[pLen++] = mac[i];

    // AD structure: Complete Local Name (tipo 0x09)
    if (namelen > 0) {
        pdu[pLen++] = 1 + namelen;  // longitud = tipo(1) + datos(namelen)
        pdu[pLen++] = 0x09;          // tipo: Complete Local Name
        memcpy(pdu + pLen, name, namelen);
        pLen += namelen;
    }

    // CRC24 sobre toda la PDU (antes de whitening)
    uint32_t crc = bleCRC24(pdu, pLen);
    pdu[pLen++] = (uint8_t)(crc & 0xFF);
    pdu[pLen++] = (uint8_t)((crc >> 8) & 0xFF);
    pdu[pLen++] = (uint8_t)((crc >> 16) & 0xFF);

    // Aplicar data-whitening BLE
    bleWhiten(pdu, pLen, bleCh);

    // Invertir bits de cada byte para compatibilidad con nRF24
    uint8_t outLen = (pLen > 32) ? 32 : pLen;
    for (uint8_t i = 0; i < outLen; i++) out[i] = reverseByte(pdu[i]);

    return outLen;
}

/**
 * Genera una MAC aleatoria de 6 bytes.
 * Los dos bits más significativos del primer byte se fijan a 1
 * para indicar "dirección aleatoria estática" según BLE.
 */
static void randomMAC(uint8_t* mac) {
    for (int i = 0; i < 6; i++) mac[i] = (uint8_t)random(256);
    mac[0] |= 0xC0;    // Bits 6 y 7 = 1 → random static address
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  CONFIGURACIÓN DE RADIO                                                  ║
// ╚══════════════════════════════════════════════════════════════════════════╝

/**
 * Aplica la configuración base BLE a un radio nRF24:
 *   • 1 Mbps (BLE usa GFSK 1 Mbps)
 *   • CRC deshabilitado (BLE tiene su propio CRC de 24 bits)
 *   • Auto-ACK deshabilitado
 *   • Potencia máxima
 *   • Payload fijo de 32 bytes
 */
static void applyBLEConfig(RF24* r) {
    r->setDataRate(RF24_1MBPS);
    r->setCRCLength(RF24_CRC_DISABLED);
    r->setAutoAck(false);
    r->setPALevel(RF24_PA_MAX);
    r->setPayloadSize(32);
    r->disableDynamicPayloads();
}

/**
 * Configura el radio en modo TX sobre el canal de advertising indicado.
 * chIdx: índice 0-2 en kBleRfCh[].
 */
static void setTX(RF24* r, uint8_t chIdx) {
    r->stopListening();
    r->setChannel(kBleRfCh[chIdx]);
    applyBLEConfig(r);
    r->openWritingPipe(kBleAddrNrf);
}

/**
 * Configura el radio en modo RX sobre el canal de advertising indicado.
 * chIdx: índice 0-2 en kBleRfCh[].
 */
static void setRX(RF24* r, uint8_t chIdx) {
    r->stopListening();
    r->setChannel(kBleRfCh[chIdx]);
    applyBLEConfig(r);
    r->openReadingPipe(1, kBleAddrNrf);
    r->startListening();
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  GESTIÓN DE MÓDULOS                                                      ║
// ╚══════════════════════════════════════════════════════════════════════════╝

// Declaración adelantada (stopModule se usa en handleCommand)
static void stopModule(int idx);

/**
 * Inicializa un módulo de radio.
 * Retorna true si el nRF24 responde correctamente.
 */
static bool initModule(int idx, RF24* r, SPIClass* spi,
                       uint8_t sck, uint8_t miso, uint8_t mosi, uint8_t csn) {
    spi->begin(sck, miso, mosi, csn);
    bool ok = r->begin(spi);
    if (ok) {
        applyBLEConfig(r);
        r->stopListening();
    }
    mod[idx].radio        = r;
    mod[idx].state        = MOD_IDLE;
    strcpy(mod[idx].tag, "IDLE");
    mod[idx].lastAdv      = 0;
    mod[idx].lastFlood    = 0;
    mod[idx].lastHop      = 0;
    mod[idx].floodCount   = 0;
    mod[idx].floodSent    = 0;
    mod[idx].advMsg[0]    = '\0';
    randomMAC(mod[idx].advMAC);
    return ok;
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  FUNCIONES DE ACTUALIZACIÓN DE ESTADO (no bloqueantes)                   ║
// ╚══════════════════════════════════════════════════════════════════════════╝

// ── updateScan ────────────────────────────────────────────────────────────────
/**
 * Máquina de estado para escaneo BLE.
 * Rota entre los 3 canales de advertising cada SCAN_HOP_MS ms.
 * Por cada paquete recibido, intenta parsear MAC, RSSI y nombre.
 *
 * LIMITACIÓN nRF24: el registro RPD (Received Power Detector) solo indica
 * si la señal supera −64 dBm (1) o no (0), no el RSSI exacto.
 * Se mapea a valores aproximados: −55 dBm o −90 dBm.
 */
static void updateScan(int idx) {
    RadioModule* m = &mod[idx];
    unsigned long now = millis();

    // Verificar expiración del tiempo de escaneo
    if (m->scanDuration > 0 && (now - m->scanStart) >= m->scanDuration) {
        m->radio->stopListening();
        m->state = MOD_IDLE;
        strcpy(m->tag, "IDLE");
        Serial.println("SCAN_DONE");
        return;
    }

    // Rotar entre canales de advertising
    if ((now - m->lastHop) >= SCAN_HOP_MS) {
        m->scanChIdx = (m->scanChIdx + 1) % 3;
        m->lastHop   = now;
        setRX(m->radio, m->scanChIdx);
    }

    // Leer paquete si disponible
    if (!m->radio->available()) return;

    uint8_t raw[32] = {0};
    m->radio->read(raw, 32);

    // RSSI aproximado vía Received Power Detector
    int8_t rssi = m->radio->testRPD() ? -55 : -90;

    // Revertir bits y quitar whitening para obtener el PDU en bruto
    uint8_t pkt[32];
    uint8_t bleCh = kBleAdvCh[m->scanChIdx];
    for (int i = 0; i < 32; i++) pkt[i] = reverseByte(raw[i]);
    bleWhiten(pkt, 32, bleCh);

    // Validar cabecera PDU básica
    //   pkt[0] bits[3:0]: tipo PDU (0=ADV_IND, 1=ADV_DIRECT, 2=ADV_NONCONN, 5=ADV_SCAN)
    //   pkt[1]: longitud del PDU (debe ser 6..37)
    uint8_t pduType = pkt[0] & 0x0F;
    uint8_t pduLen  = pkt[1];
    if (pduType > 5 || pduLen < 6 || pduLen > 37) return;

    // Extraer MAC: AdvA = pkt[2..7], BLE la envía LSB first → mostrar invertida
    char macStr[18];
    snprintf(macStr, sizeof(macStr),
             "%02X:%02X:%02X:%02X:%02X:%02X",
             pkt[7], pkt[6], pkt[5], pkt[4], pkt[3], pkt[2]);

    // Buscar campo de nombre en AdvData (a partir de pkt[8])
    // Formato AD: [len][type][data...][len][type][data...]...
    //   tipo 0x08 = Shortened Local Name
    //   tipo 0x09 = Complete Local Name
    char name[32] = "";
    uint8_t adOff = 8;
    uint8_t adEnd = (uint8_t)(2 + pduLen);   // Fin de AdvData (sin CRC de 3 bytes)
    if (adEnd > 29) adEnd = 29;              // Límite seguro dentro del buffer de 32 B

    while (adOff < adEnd) {
        uint8_t adLen  = pkt[adOff];
        if (adLen == 0 || (adOff + adLen) >= 32) break;
        uint8_t adType = pkt[adOff + 1];

        if (adType == 0x09 || adType == 0x08) {
            uint8_t nLen = adLen - 1;
            if (nLen > 31) nLen = 31;
            memcpy(name, pkt + adOff + 2, nLen);
            name[nLen] = '\0';
            // Filtrar caracteres no imprimibles
            for (uint8_t k = 0; k < nLen; k++) {
                if ((uint8_t)name[k] < 32 || (uint8_t)name[k] > 126) name[k] = '?';
            }
            break;
        }
        adOff += 1 + adLen;
    }

    Serial.printf("DEVICE:%s,%d,%s\n", macStr, rssi, name);
}

// ── updateAdvertise ───────────────────────────────────────────────────────────
/**
 * Emite paquetes de advertising BLE periódicamente en los 3 canales.
 * Usa la MAC propia almacenada en m->advMAC y el mensaje en m->advMsg.
 */
static void updateAdvertise(int idx) {
    RadioModule* m   = &mod[idx];
    unsigned long now = millis();
    if ((now - m->lastAdv) < ADV_INTERVAL_MS) return;
    m->lastAdv = now;

    // Transmitir en los 3 canales de advertising BLE
    for (uint8_t ch = 0; ch < 3; ch++) {
        uint8_t pkt[32];
        uint8_t pktLen = buildAdvPacket(pkt, m->advMAC, m->advMsg, ch);
        setTX(m->radio, ch);
        m->radio->write(pkt, pktLen);
    }
}

// ── updateFlood ───────────────────────────────────────────────────────────────
/**
 * Genera y transmite beacons BLE con MACs y nombres aleatorios.
 * Si floodCount > 0, se detiene al alcanzar ese número.
 * Si floodCount == 0, continúa hasta recibir STOP.
 */
static void updateFlood(int idx) {
    RadioModule* m   = &mod[idx];
    unsigned long now = millis();
    if ((now - m->lastFlood) < m->floodInterval) return;
    m->lastFlood = now;

    // Verificar límite de beacons
    if (m->floodCount > 0 && m->floodSent >= m->floodCount) {
        m->radio->stopListening();
        m->state = MOD_IDLE;
        strcpy(m->tag, "IDLE");
        Serial.println("FLOOD_DONE");
        return;
    }

    // MAC y nombre aleatorios para este beacon
    uint8_t mac[6];
    randomMAC(mac);
    const char* name = kNames[random(kNamesCount)];

    // Transmitir en los 3 canales
    for (uint8_t ch = 0; ch < 3; ch++) {
        uint8_t pkt[32];
        uint8_t pktLen = buildAdvPacket(pkt, mac, name, ch);
        setTX(m->radio, ch);
        m->radio->write(pkt, pktLen);
    }
    m->floodSent++;
}

// ── updateJam (stub) ──────────────────────────────────────────────────────────
/**
 * Gestiona el temporizador del comando JAM.
 * NOTA INTENCIONAL: No se llama a radio->startConstCarrier().
 * El firmware responde el protocolo pero NO emite portadora de RF.
 */
static void updateJam(int idx) {
    RadioModule* m = &mod[idx];
    if (m->jamDuration == 0) return;    // Duración 0 = hasta STOP manual
    if ((millis() - m->jamStart) >= m->jamDuration) {
        m->state = MOD_IDLE;
        strcpy(m->tag, "IDLE");
        Serial.println("JAM_DONE");
    }
}

// ── updateSweep (stub) ────────────────────────────────────────────────────────
/**
 * Gestiona el temporizador del comando SWEEP_JAM.
 * NOTA INTENCIONAL: No se emite RF. Solo gestión de estado.
 */
static void updateSweep(int idx) {
    RadioModule* m = &mod[idx];
    if (m->jamDuration == 0) return;
    if ((millis() - m->jamStart) >= m->jamDuration) {
        m->state = MOD_IDLE;
        strcpy(m->tag, "IDLE");
        Serial.println("SWEEP_DONE");
    }
}

/**
 * Dispatcher principal: llama a la función correcta según el estado del módulo.
 */
static void updateModule(int idx) {
    switch (mod[idx].state) {
        case MOD_SCANNING:      updateScan(idx);      break;
        case MOD_ADVERTISING:   updateAdvertise(idx); break;
        case MOD_FLOODING:      updateFlood(idx);     break;
        case MOD_JAMMING:       updateJam(idx);       break;
        case MOD_SWEEP_JAMMING: updateSweep(idx);     break;
        case MOD_IDLE:          /* nada */             break;
    }
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  STOP                                                                    ║
// ╚══════════════════════════════════════════════════════════════════════════╝

/**
 * Detiene cualquier operación en curso del módulo indicado y lo pone en IDLE.
 * No envía "STOPPED" por serial (eso lo hace el caller si corresponde).
 */
static void stopModule(int idx) {
    mod[idx].radio->stopListening();
    mod[idx].state = MOD_IDLE;
    strcpy(mod[idx].tag, "IDLE");
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  PARSER DE COMANDOS                                                      ║
// ╚══════════════════════════════════════════════════════════════════════════╝

/**
 * Procesa una línea de comando recibida por el puerto serie.
 * Los comandos están documentados en la cabecera del archivo.
 *
 * Formato de parseo:
 *   Se usa sscanf para extraer hasta 4 tokens separados por espacios.
 *   Para ADVERTISE, el mensaje se extrae manualmente desde la línea original
 *   para preservar espacios internos.
 */
static void handleCommand(const char* line) {
    char cmd[32]  = "";
    char a1[64]   = "";
    char a2[32]   = "";
    char a3[32]   = "";

    int argc = sscanf(line, "%31s %63s %31s %31s", cmd, a1, a2, a3);
    if (argc < 1) return;

    // ── STATUS ──────────────────────────────────────────────────────────────
    if (strcmp(cmd, "STATUS") == 0) {
        Serial.printf("MOD0:%s MOD1:%s\n", mod[0].tag, mod[1].tag);
        return;
    }

    // ── Comandos que requieren número de módulo ───────────────────────────
    if (argc < 2) {
        Serial.println("ERROR:faltan argumentos");
        return;
    }
    int idx = atoi(a1);
    if (idx != 0 && idx != 1) {
        Serial.println("ERROR:modulo invalido, usa 0 o 1");
        return;
    }
    RadioModule* m = &mod[idx];

    // ── STOP ────────────────────────────────────────────────────────────────
    if (strcmp(cmd, "STOP") == 0) {
        stopModule(idx);
        Serial.println("STOPPED");
        return;
    }

    // ── SCAN ─────────────────────────────────────────────────────────────────
    if (strcmp(cmd, "SCAN") == 0) {
        if (argc < 3) { Serial.println("ERROR:SCAN requiere <mod> <segundos>"); return; }
        stopModule(idx);
        m->state        = MOD_SCANNING;
        m->scanDuration = (unsigned long)atoi(a2) * 1000UL;
        m->scanStart    = millis();
        m->scanChIdx    = 0;
        m->lastHop      = millis();
        strcpy(m->tag, "SCAN");
        setRX(m->radio, 0);
        Serial.println("SCANNING_STARTED");
        return;
    }

    // ── ADVERTISE ────────────────────────────────────────────────────────────
    if (strcmp(cmd, "ADVERTISE") == 0) {
        if (argc < 3) { Serial.println("ERROR:ADVERTISE requiere <mod> <mensaje>"); return; }
        stopModule(idx);

        // Extraer mensaje completo (puede tener espacios):
        //   Saltar "ADVERTISE " + número de módulo + espacio
        const char* p = line;
        while (*p && !isspace((unsigned char)*p)) p++;   // saltar "ADVERTISE"
        while (*p && isspace((unsigned char)*p))  p++;   // saltar espacios
        while (*p && !isspace((unsigned char)*p)) p++;   // saltar "<mod>"
        while (*p && isspace((unsigned char)*p))  p++;   // saltar espacios → inicio del msg

        strncpy(m->advMsg, p, 63);
        m->advMsg[63] = '\0';

        m->state   = MOD_ADVERTISING;
        m->lastAdv = 0;    // Forzar envío inmediato
        strcpy(m->tag, "ADV");
        Serial.println("ADVERTISING_STARTED");
        return;
    }

    // ── BEACON_FLOOD ──────────────────────────────────────────────────────────
    if (strcmp(cmd, "BEACON_FLOOD") == 0) {
        if (argc < 4) { Serial.println("ERROR:BEACON_FLOOD requiere <mod> <count> <interval_ms>"); return; }
        stopModule(idx);
        m->floodCount    = atoi(a2);
        m->floodSent     = 0;
        m->floodInterval = (unsigned long)atoi(a3);
        if (m->floodInterval < 10) m->floodInterval = 10;  // Mínimo seguro
        m->lastFlood     = 0;
        m->state         = MOD_FLOODING;
        strcpy(m->tag, "FLOOD");
        Serial.println("FLOODING_STARTED");
        return;
    }

    // ── JAM (stub) ────────────────────────────────────────────────────────────
    if (strcmp(cmd, "JAM") == 0) {
        if (argc < 4) { Serial.println("ERROR:JAM requiere <mod> <canal> <segundos>"); return; }
        stopModule(idx);
        // canal BLE (a2) es informativo, no se usa en el stub
        m->jamDuration = (unsigned long)atoi(a3) * 1000UL;
        m->jamStart    = millis();
        m->state       = MOD_JAMMING;
        strcpy(m->tag, "JAM");
        Serial.println("JAMMING_STARTED");
        // Stub: NO se emite portadora de RF (startConstCarrier omitido)
        return;
    }

    // ── SWEEP_JAM (stub) ──────────────────────────────────────────────────────
    if (strcmp(cmd, "SWEEP_JAM") == 0) {
        if (argc < 3) { Serial.println("ERROR:SWEEP_JAM requiere <mod> <segundos>"); return; }
        stopModule(idx);
        m->jamDuration = (unsigned long)atoi(a2) * 1000UL;
        m->jamStart    = millis();
        m->state       = MOD_SWEEP_JAMMING;
        strcpy(m->tag, "SWEEP");
        Serial.println("SWEEP_JAMMING_STARTED");
        // Stub: NO se emite portadora de RF
        return;
    }

    // Comando desconocido
    Serial.printf("ERROR:comando desconocido '%s'\n", cmd);
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  OLED                                                                    ║
// ╚══════════════════════════════════════════════════════════════════════════╝

/**
 * Actualiza la pantalla OLED con:
 *   • Logo "DRAGON FLY v1.0"
 *   • Estado de cada módulo
 *   • Uptime del sistema
 *
 * Se llama desde loop() cada OLED_REFRESH_MS ms para no impactar la latencia.
 */
static void updateOLED() {
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_6x10_tf);

    // ── Título / Logo ────────────────────────────────────────────────────────
    u8g2.drawStr(0, 10, "DRAGON FLY v1.0");
    u8g2.drawHLine(0, 13, 128);

    // ── Estado de módulos ────────────────────────────────────────────────────
    char lineBuf[32];
    snprintf(lineBuf, sizeof(lineBuf), "MOD0: %-8s", mod[0].tag);
    u8g2.drawStr(0, 27, lineBuf);
    snprintf(lineBuf, sizeof(lineBuf), "MOD1: %-8s", mod[1].tag);
    u8g2.drawStr(0, 40, lineBuf);

    // ── Uptime ───────────────────────────────────────────────────────────────
    u8g2.drawHLine(0, 50, 128);
    unsigned long s = millis() / 1000;
    snprintf(lineBuf, sizeof(lineBuf), "UP %02lu:%02lu:%02lu",
             s / 3600, (s % 3600) / 60, s % 60);
    u8g2.drawStr(0, 62, lineBuf);

    u8g2.sendBuffer();
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  setup()                                                                 ║
// ╚══════════════════════════════════════════════════════════════════════════╝

void setup() {
    Serial.begin(115200);
    delay(300);

    // ── OLED ─────────────────────────────────────────────────────────────────
    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
    u8g2.begin();
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_6x10_tf);
    u8g2.drawStr(0, 20, "DRAGON FLY");
    u8g2.drawStr(0, 35, "BLE GADGET v1.0");
    u8g2.drawStr(0, 50, "Iniciando...");
    u8g2.sendBuffer();

    Serial.println("DRAGON FLY BLE GADGET v1.0");

    // ── nRF24 #0 (HSPI) ──────────────────────────────────────────────────────
    bool ok0 = initModule(0, &radio0, &spi0,
                           PIN_SCK0, PIN_MISO0, PIN_MOSI0, PIN_CSN0);
    Serial.printf("[MOD0] nRF24 HSPI: %s\n", ok0 ? "OK" : "FALLO – revisar cableado");

    // ── nRF24 #1 (VSPI) ──────────────────────────────────────────────────────
    bool ok1 = initModule(1, &radio1, &spi1,
                           PIN_SCK1, PIN_MISO1, PIN_MOSI1, PIN_CSN1);
    Serial.printf("[MOD1] nRF24 VSPI: %s\n", ok1 ? "OK" : "FALLO – revisar cableado");

    // Semilla aleatoria desde el generador de hardware del ESP32
    randomSeed(esp_random());

    // ── OLED: estado inicial ──────────────────────────────────────────────────
    delay(500);
    updateOLED();

    Serial.println("READY");
}

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  loop()                                                                  ║
// ╚══════════════════════════════════════════════════════════════════════════╝

void loop() {
    // ── Lectura de comandos por serial (no bloqueante) ────────────────────────
    //   Se acumulan caracteres en serialBuf hasta recibir '\n' o '\r'.
    //   Máximo SCAN_HOP_MS ms de latencia (el loop es muy rápido).
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (serialPos > 0) {
                serialBuf[serialPos] = '\0';
                handleCommand(serialBuf);
                serialPos = 0;
            }
        } else if (serialPos < (int)(sizeof(serialBuf) - 1)) {
            serialBuf[serialPos++] = c;
        }
    }

    // ── Actualizar estado de cada módulo ──────────────────────────────────────
    updateModule(0);
    updateModule(1);

    // ── Refresco periódico de la OLED ─────────────────────────────────────────
    if ((millis() - lastOledRefresh) >= OLED_REFRESH_MS) {
        lastOledRefresh = millis();
        updateOLED();
    }
}
