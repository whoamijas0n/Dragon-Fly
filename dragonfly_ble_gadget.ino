/*
 * DRAGON FLY BLE GADGET v1.0
 * Firmware para ESP32 con dos módulos nRF24L01+ (HSPI y VSPI) y OLED SSD1306.
 * Protocolo serie (115200 baud) compatible con gadget_handler.py.
 * 
 * Conexiones:
 *   OLED: SDA=4, SCL=5, VCC=3.3V, GND=GND
 *   nRF0 (HSPI): CE=16, CSN=15, SCK=14, MISO=12, MOSI=13
 *   nRF1 (VSPI): CE=22, CSN=21, SCK=18, MISO=19, MOSI=23
 *   Ambos comparten VCC(3.3V) y GND.
 *
 * Dependencias:
 *   - RF24 by TMRh20   (https://github.com/nRF24/RF24)
 *   - U8g2 by olikraus (https://github.com/olikraus/u8g2)
 */

#include <SPI.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <RF24.h>

// ========================== CONFIGURACIÓN DE PINES ==========================
// OLED
#define OLED_SDA  4
#define OLED_SCL  5

// Módulo 0 (HSPI)
#define HSPI_SCK  14
#define HSPI_MISO 12
#define HSPI_MOSI 13
#define NRF0_CE   16
#define NRF0_CSN  15

// Módulo 1 (VSPI)
#define VSPI_SCK  18
#define VSPI_MISO 19
#define VSPI_MOSI 23
#define NRF1_CE   22
#define NRF1_CSN  21

// ========================== CLASE BLE MÍNIMA ==========================
class BLERadio {
public:
  BLERadio(RF24& radio) : _radio(radio) {}

  void begin() {
    _radio.begin();
    _radio.setDataRate(RF24_250KBPS);
    _radio.setCRCLength(RF24_CRC_DISABLED); // BLE ya lleva su propio CRC
    _radio.setAutoAck(false);
    _radio.setPALevel(RF24_PA_MAX);
    _radio.setAddressWidth(4);

    // Dirección de acceso BLE (0x8E89BED6) en little‑endian
    uint8_t addr[4] = {0xD6, 0xBE, 0x89, 0x8E};
    _radio.openReadingPipe(0, addr);
    _radio.openWritingPipe(addr);
    _radio.startListening();
  }

  // Canal BLE (0‑39) -> canal RF (2‑41‑..‑80)
  void setChannel(int ble_channel) {
    int rf_ch = 2 + ble_channel;
    _radio.stopListening();
    _radio.setChannel(rf_ch);
    _radio.startListening();
  }

  void setMAC(const uint8_t* mac) {
    memcpy(_adv_mac, mac, 6);
  }

  // Construye paquete ADV_IND con Complete Local Name
  void createPacket(const char* name, uint8_t* packet, uint8_t& len) {
    int nameLen = strlen(name);
    int payloadLen = 6 + 5 + nameLen; // AdvA(6) + Flags(3) + Name(1+1+nameLen)
    packet[0] = 0x46;                 // ADV_IND, TxAdd=1 (random)
    packet[1] = payloadLen;
    memcpy(packet + 2, _adv_mac, 6);  // AdvA
    int pos = 8;
    // Flags AD
    packet[pos++] = 2;
    packet[pos++] = 0x01;
    packet[pos++] = 0x06;             // LE General Discoverable
    // Complete Local Name AD
    packet[pos++] = nameLen + 1;
    packet[pos++] = 0x09;
    memcpy(packet + pos, name, nameLen);
    pos += nameLen;
    len = pos;
  }

  void sendPacket(uint8_t* packet, uint8_t len) {
    _radio.stopListening();
    _radio.write(packet, len);
    _radio.startListening();
  }

  bool getPacket(uint8_t* packet, uint8_t& len) {
    if (_radio.available()) {
      len = _radio.getDynamicPayloadSize();
      _radio.read(packet, len);
      _radio.flush_rx();
      return true;
    }
    return false;
  }

private:
  RF24& _radio;
  uint8_t _adv_mac[6];
};

// ========================== OBJETOS GLOBALES ==========================
SPIClass hspi(HSPI);  // Bus SPI2 para módulo 0
SPIClass vspi(VSPI);  // Bus SPI3 para módulo 1

RF24 radio0(NRF0_CE, NRF0_CSN, &hspi);
RF24 radio1(NRF1_CE, NRF1_CSN, &vspi);

BLERadio ble0(radio0);
BLERadio ble1(radio1);

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// ========================== MÁQUINA DE ESTADOS ==========================
enum Mode : uint8_t {
  IDLE,
  SCANNING,
  ADVERTISING,
  FLOOD,
  JAM,
  SWEEP
};

struct Module {
  Mode mode = IDLE;
  unsigned long startTime = 0;
  unsigned long lastAction = 0;
  bool stopRequested = false;

  // SCAN
  int scanChIdx = 0;
  static const unsigned long scanHopMs = 200;

  // ADVERTISE
  String advMsg;

  // FLOOD
  int floodCount = 0;
  int floodSent = 0;
  unsigned long floodIntervalMs = 100;

  // JAM
  int jamChannel = 0;
  int durationSec = 0;

  // SWEEP
  int sweepChannel = 0;
  static const unsigned long sweepHopMs = 200;
};

Module mod[2];

// ========================== PROTOTIPOS ==========================
void handleCommand(const String& cmd);
void startScan(int idx, int duration);
void startAdvertise(int idx, String msg);
void startFlood(int idx, int count, int interval);
void startJam(int idx, int channel, int duration);
void startSweep(int idx, int duration);
void stopModule(int idx);
void updateModule(int idx);
void updateOLED();
String modeToString(Mode m);

// ========================== SETUP ==========================
void setup() {
  Serial.begin(115200);
  delay(200);

  // Inicializar buses SPI
  hspi.begin(HSPI_SCK, HSPI_MISO, HSPI_MOSI);
  vspi.begin(VSPI_SCK, VSPI_MISO, VSPI_MOSI);

  // Inicializar radios BLE
  ble0.begin();
  ble1.begin();

  // OLED
  Wire.begin(OLED_SDA, OLED_SCL);
  u8g2.begin();
  u8g2.setFont(u8g2_font_ncenB08_tr);

  Serial.println("DRAGON FLY BLE GADGET v1.0");
  updateOLED();
}

// ========================== LOOP PRINCIPAL ==========================
void loop() {
  // Leer comandos por línea
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) {
      handleCommand(cmd);
    }
  }

  // Actualizar ambos módulos
  updateModule(0);
  updateModule(1);

  // Refrescar OLED cada 500 ms
  static unsigned long lastOled = 0;
  if (millis() - lastOled >= 500) {
    updateOLED();
    lastOled = millis();
  }
}

// ========================== COMANDOS ==========================
void handleCommand(const String& cmd) {
  char buf[128];
  cmd.toCharArray(buf, 128);

  char* token = strtok(buf, " ");
  if (!token) return;
  String command = String(token);
  command.toUpperCase();

  if (command == "SCAN") {
    int idx = atoi(strtok(NULL, " "));
    int dur = atoi(strtok(NULL, " "));
    if (idx < 0 || idx > 1) { Serial.println("ERROR:Invalid module"); return; }
    startScan(idx, dur);
  }
  else if (command == "STOP") {
    int idx = atoi(strtok(NULL, " "));
    if (idx < 0 || idx > 1) { Serial.println("ERROR:Invalid module"); return; }
    stopModule(idx);
  }
  else if (command == "ADVERTISE") {
    int idx = atoi(strtok(NULL, " "));
    char* msg = strtok(NULL, "");
    if (!msg) { Serial.println("ERROR:Missing message"); return; }
    if (idx < 0 || idx > 1) { Serial.println("ERROR:Invalid module"); return; }
    startAdvertise(idx, String(msg));
  }
  else if (command == "BEACON_FLOOD") {
    int idx = atoi(strtok(NULL, " "));
    int count = atoi(strtok(NULL, " "));
    int interval = atoi(strtok(NULL, " "));
    if (idx < 0 || idx > 1) { Serial.println("ERROR:Invalid module"); return; }
    startFlood(idx, count, interval);
  }
  else if (command == "JAM") {
    int idx = atoi(strtok(NULL, " "));
    int channel = atoi(strtok(NULL, " "));
    int duration = atoi(strtok(NULL, " "));
    if (idx < 0 || idx > 1) { Serial.println("ERROR:Invalid module"); return; }
    startJam(idx, channel, duration);
  }
  else if (command == "SWEEP_JAM") {
    int idx = atoi(strtok(NULL, " "));
    int duration = atoi(strtok(NULL, " "));
    if (idx < 0 || idx > 1) { Serial.println("ERROR:Invalid module"); return; }
    startSweep(idx, duration);
  }
  else if (command == "STATUS") {
    String status = "MOD0:" + modeToString(mod[0].mode) + 
                    " MOD1:" + modeToString(mod[1].mode);
    Serial.println(status);
  }
  else {
    Serial.println("ERROR:Unknown command");
  }
}

// ========================== INICIO DE OPERACIONES ==========================
void startScan(int idx, int duration) {
  stopModule(idx);  // detiene cualquier operación previa
  Module& m = mod[idx];
  m.mode = SCANNING;
  m.startTime = millis();
  m.lastAction = millis() - Module::scanHopMs; // fuerza salto inmediato
  m.scanChIdx = 2; // empezará en canal 37
  Serial.println("SCANNING_STARTED");
}

void startAdvertise(int idx, String msg) {
  stopModule(idx);
  Module& m = mod[idx];
  m.mode = ADVERTISING;
  m.advMsg = msg;
  m.lastAction = millis() - 100; // primera emisión inmediata
  // MAC fija para publicidad
  uint8_t mac[6] = {0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01};
  (idx == 0 ? ble0 : ble1).setMAC(mac);
  Serial.println("ADVERTISING_STARTED");
}

void startFlood(int idx, int count, int interval) {
  stopModule(idx);
  Module& m = mod[idx];
  m.mode = FLOOD;
  m.floodCount = count;
  m.floodSent = 0;
  m.floodIntervalMs = interval;
  m.lastAction = millis() - interval;
  Serial.println("FLOODING_STARTED");
}

void startJam(int idx, int channel, int duration) {
  stopModule(idx);
  Module& m = mod[idx];
  RF24& radio = (idx == 0) ? radio0 : radio1;
  int rf_ch = 2 + channel;
  radio.stopConstCarrier();
  radio.startConstCarrier(RF24_PA_MAX, rf_ch);
  m.mode = JAM;
  m.jamChannel = channel;
  m.durationSec = duration;
  m.startTime = millis();
  Serial.println("JAMMING_STARTED");
}

void startSweep(int idx, int duration) {
  stopModule(idx);
  Module& m = mod[idx];
  RF24& radio = (idx == 0) ? radio0 : radio1;
  m.mode = SWEEP;
  m.durationSec = duration;
  m.startTime = millis();
  m.sweepChannel = 39; // primer salto irá al 0
  m.lastAction = millis() - Module::sweepHopMs;
  radio.stopConstCarrier();
  Serial.println("SWEEP_JAMMING_STARTED");
}

// ========================== PARADA ==========================
void stopModule(int idx) {
  mod[idx].stopRequested = true;
  // El flag se procesa en updateModule()
}

// ========================== ACTUALIZACIÓN DE MÓDULOS ==========================
void updateModule(int idx) {
  Module& m = mod[idx];
  BLERadio& ble = (idx == 0) ? ble0 : ble1;
  RF24& radio = (idx == 0) ? radio0 : radio1;

  // Procesar solicitud de parada
  if (m.stopRequested) {
    switch (m.mode) {
      case JAM:
        radio.stopConstCarrier();
        Serial.println("STOPPED");
        break;
      case SWEEP:
        radio.stopConstCarrier();
        Serial.println("STOPPED");
        break;
      case SCANNING:
        Serial.println("STOPPED");
        break;
      case ADVERTISING:
        Serial.println("STOPPED");
        break;
      case FLOOD:
        Serial.println("STOPPED");
        break;
      default: break;
    }
    m.mode = IDLE;
    m.stopRequested = false;
    return;
  }

  // Máquina de estados
  switch (m.mode) {
    // ---------- IDLE ----------
    case IDLE: break;

    // ---------- SCANNING ----------
    case SCANNING: {
      if (m.durationSec > 0 && (millis() - m.startTime) >= m.durationSec * 1000UL) {
        m.mode = IDLE;
        Serial.println("SCAN_DONE");
        break;
      }
      // Salto de canal
      if (millis() - m.lastAction >= Module::scanHopMs) {
        m.scanChIdx = (m.scanChIdx + 1) % 3;
        int bleCh = (m.scanChIdx == 0) ? 37 : (m.scanChIdx == 1 ? 38 : 39);
        ble.setChannel(bleCh);
        m.lastAction = millis();
      }
      // Capturar paquete
      uint8_t packet[32];
      uint8_t len;
      if (ble.getPacket(packet, len)) {
        // Analizar ADV_IND (tipo 0x00)
        if (len >= 2 && (packet[0] & 0x0F) == 0x00) {
          // MAC en bytes 2..7 (big endian)
          char macStr[18];
          sprintf(macStr, "%02X:%02X:%02X:%02X:%02X:%02X",
                  packet[2], packet[3], packet[4], packet[5], packet[6], packet[7]);

          // RSSI aproximado mediante RPD
          int rssi = radio.testRPD() ? -50 : -80;

          // Extraer Complete Local Name (0x09)
          String name = "";
          int pos = 8; // inicio de AdvData
          while (pos < len) {
            uint8_t fieldLen = packet[pos];
            if (fieldLen == 0) break;
            uint8_t type = packet[pos + 1];
            if (type == 0x09) {
              for (int i = 0; i < fieldLen - 1; i++)
                name += (char)packet[pos + 2 + i];
              break;
            }
            pos += fieldLen + 1;
          }
          Serial.print("DEVICE:");
          Serial.print(macStr);
          Serial.print(",");
          Serial.print(rssi);
          Serial.print(",");
          Serial.println(name);
        }
      }
      break;
    }

    // ---------- ADVERTISING ----------
    case ADVERTISING: {
      if (millis() - m.lastAction >= 100) {
        uint8_t packet[32];
        uint8_t len;
        ble.createPacket(m.advMsg.c_str(), packet, len);
        ble.sendPacket(packet, len);
        m.lastAction = millis();
      }
      break;
    }

    // ---------- FLOOD ----------
    case FLOOD: {
      if (m.floodCount == 0 || m.floodSent < m.floodCount) {
        if (millis() - m.lastAction >= m.floodIntervalMs) {
          // MAC aleatoria
          uint8_t rndMac[6];
          for (int i = 0; i < 6; i++) rndMac[i] = random(256);
          ble.setMAC(rndMac);
          // Nombre aleatorio de 4 caracteres
          char rndName[8];
          for (int i = 0; i < 4; i++) rndName[i] = 'A' + random(26);
          rndName[4] = '\0';
          uint8_t packet[32];
          uint8_t len;
          ble.createPacket(rndName, packet, len);
          ble.sendPacket(packet, len);
          m.floodSent++;
          m.lastAction = millis();
          // Si cuenta finita y hemos terminado, pasar a IDLE
          if (m.floodCount > 0 && m.floodSent >= m.floodCount) {
            m.mode = IDLE;
            // No se envía FLOOD_DONE porque el protocolo no lo contempla
          }
        }
      }
      break;
    }

    // ---------- JAM ----------
    case JAM: {
      if (m.durationSec > 0 && (millis() - m.startTime) >= m.durationSec * 1000UL) {
        radio.stopConstCarrier();
        m.mode = IDLE;
        Serial.println("JAM_DONE");
      }
      break;
    }

    // ---------- SWEEP ----------
    case SWEEP: {
      if (m.durationSec > 0 && (millis() - m.startTime) >= m.durationSec * 1000UL) {
        radio.stopConstCarrier();
        m.mode = IDLE;
        Serial.println("SWEEP_DONE");
        break;
      }
      if (millis() - m.lastAction >= Module::sweepHopMs) {
        m.sweepChannel = (m.sweepChannel + 1) % 40; // 0‑39
        int rfCh = 2 + m.sweepChannel;
        radio.stopConstCarrier();
        radio.startConstCarrier(RF24_PA_MAX, rfCh);
        m.lastAction = millis();
      }
      break;
    }
  }
}

// ========================== OLED ==========================
void updateOLED() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_ncenB08_tr);
  u8g2.drawStr(0, 10, "DRAGON FLY");
  String line0 = "M0: " + modeToString(mod[0].mode);
  String line1 = "M1: " + modeToString(mod[1].mode);
  u8g2.drawStr(0, 30, line0.c_str());
  u8g2.drawStr(0, 45, line1.c_str());
  u8g2.sendBuffer();
}

String modeToString(Mode m) {
  switch (m) {
    case IDLE:        return "IDLE";
    case SCANNING:    return "SCAN";
    case ADVERTISING: return "ADV";
    case FLOOD:       return "FLOOD";
    case JAM:         return "JAM";
    case SWEEP:       return "SWEEP";
  }
  return "?";
}
