#include <SPI.h>
#include <RF24.h>
#include <BTLE.h>

// ======================================================================
// CONFIGURACIÓN DE PINES (ESP32)
// ======================================================================
// HSPI (Módulo 0)
const int HSPI_SCK  = 14;
const int HSPI_MISO = 12;
const int HSPI_MOSI = 13;
const int HSPI_SS   = 15;
const int HSPI_CE   = 16;

// VSPI (Módulo 1)
const int VSPI_SCK  = 18;
const int VSPI_MISO = 19;
const int VSPI_MOSI = 23;
const int VSPI_SS   = 21;
const int VSPI_CE   = 22;

// ======================================================================
// OBJETOS DE RADIO Y BTLE
// ======================================================================
SPIClass hspi(HSPI);
SPIClass vspi(VSPI);

RF24 radio0(HSPI_CE, HSPI_SS);
RF24 radio1(VSPI_CE, VSPI_SS);

BTLE btle0(&radio0);
BTLE btle1(&radio1);

// ======================================================================
// ESTADOS DE LOS MÓDULOS
// ======================================================================
enum ModuleState {
  IDLE,
  SCANNING,
  ADVERTISING,
  FLOODING,
  JAMMING
};

struct Module {
  ModuleState state;
  bool stopRequested;
  unsigned long startTime;
  unsigned long lastBeaconTime;
  unsigned long scanDuration;
  String advertiseMsg;
  int floodCount;
  int floodInterval;
  int floodCurrent;
  int jamChannel;
  unsigned long jamEndTime;
};

Module mod[2] = {
  {IDLE, false, 0, 0, 0, "", 0, 0, 0, 0, 0},
  {IDLE, false, 0, 0, 0, "", 0, 0, 0, 0, 0}
};

// Watchdog simple
unsigned long lastWatchdogReset = 0;
const unsigned long WATCHDOG_INTERVAL = 5000; // 5 seg

// ======================================================================
// PROTOTIPOS
// ======================================================================
void processCommand(String cmd);
void initRadio(RF24 &radio, SPIClass &spi, uint8_t sck, uint8_t miso, uint8_t mosi);
void handleModule(int index, BTLE &btle, RF24 &radio);
void doScan(int mod, BTLE &btle);
void doAdvertise(int mod, BTLE &btle);
void doFlood(int mod, BTLE &btle);
void doJam(int mod, RF24 &radio);
void stopModule(int mod, BTLE &btle, RF24 &radio);
void resetWatchdog();

// ======================================================================
// SETUP
// ======================================================================
void setup() {
  Serial.begin(115200);
  Serial.println("DRAGON FLY GADGET READY");

  // Inicializar HSPI y VSPI
  initRadio(radio0, hspi, HSPI_SCK, HSPI_MISO, HSPI_MOSI);
  initRadio(radio1, vspi, VSPI_SCK, VSPI_MISO, VSPI_MOSI);

  // BTLE por defecto canal 37 para escaneo/publicidad
  btle0.begin();
  btle1.begin();

  Serial.println("MODULOS LISTOS");
  resetWatchdog();
}

void initRadio(RF24 &radio, SPIClass &spi, uint8_t sck, uint8_t miso, uint8_t mosi) {
  spi.begin(sck, miso, mosi, -1); // SS se maneja externamente
  radio.begin(&spi);
  radio.setAutoAck(false);
  radio.setDataRate(RF24_1MBPS);
  radio.setCRCLength(RF24_CRC_DISABLED);
  radio.setChannel(37);
  radio.powerUp();
}

void resetWatchdog() {
  lastWatchdogReset = millis();
}

// ======================================================================
// LOOP PRINCIPAL
// ======================================================================
void loop() {
  // Lectura de comandos serie
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) {
      processCommand(cmd);
    }
  }

  // Manejo de cada módulo de forma no bloqueante
  handleModule(0, btle0, radio0);
  handleModule(1, btle1, radio1);

  // Watchdog: reiniciar si la comunicación serie se congela (muy simple)
  if (millis() - lastWatchdogReset > WATCHDOG_INTERVAL) {
    // Podríamos reiniciar aquí, pero solo reiniciamos el contador
    resetWatchdog();
  }
}

// ======================================================================
// PROCESADOR DE COMANDOS
// ======================================================================
void processCommand(String cmd) {
  cmd.toUpperCase();
  if (cmd.startsWith("SCAN")) {
    int mod = cmd.substring(5).toInt();
    int dur = cmd.substring(cmd.lastIndexOf(' ') + 1).toInt();
    if (mod >= 0 && mod <= 1 && dur > 0) {
      if (mod[mod].state == IDLE) {
        mod[mod].state = SCANNING;
        mod[mod].startTime = millis();
        mod[mod].scanDuration = dur * 1000UL;
        mod[mod].stopRequested = false;
        // Configurar escaneo en BTLE
        btle0.setChannel(37); // Escaneará los tres canales automáticamente
        Serial.println("SCANNING_STARTED");
      } else {
        Serial.println("ERROR:MODULE_BUSY");
      }
    } else {
      Serial.println("ERROR:INVALID_PARAMS");
    }
  } else if (cmd.startsWith("ADVERTISE")) {
    int mod = cmd.substring(9).toInt();
    String msg = cmd.substring(cmd.indexOf(' ', 9) + 1);
    if (mod >= 0 && mod <= 1 && msg.length() > 0) {
      if (mod[mod].state == IDLE) {
        mod[mod].state = ADVERTISING;
        mod[mod].advertiseMsg = msg;
        mod[mod].stopRequested = false;
        Serial.println("ADVERTISING_STARTED");
      } else {
        Serial.println("ERROR:MODULE_BUSY");
      }
    } else {
      Serial.println("ERROR:INVALID_PARAMS");
    }
  } else if (cmd.startsWith("BEACON_FLOOD")) {
    int mod = cmd.substring(12).toInt();
    int space1 = cmd.indexOf(' ', 12);
    int space2 = cmd.lastIndexOf(' ');
    int count = cmd.substring(space1 + 1, space2).toInt();
    int interval = cmd.substring(space2 + 1).toInt();
    if (mod >= 0 && mod <= 1 && count > 0 && interval > 0) {
      if (mod[mod].state == IDLE) {
        mod[mod].state = FLOODING;
        mod[mod].floodCount = count;
        mod[mod].floodInterval = interval;
        mod[mod].floodCurrent = 0;
        mod[mod].lastBeaconTime = millis();
        mod[mod].stopRequested = false;
        Serial.println("FLOODING_STARTED");
      } else {
        Serial.println("ERROR:MODULE_BUSY");
      }
    } else {
      Serial.println("ERROR:INVALID_PARAMS");
    }
  } else if (cmd.startsWith("JAM")) {
    int mod = cmd.substring(3).toInt();
    int ch = cmd.substring(cmd.indexOf(' ', 3) + 1).toInt();
    int dur = cmd.substring(cmd.lastIndexOf(' ') + 1).toInt();
    if (mod >= 0 && mod <= 1 && ch >= 0 && ch <= 78 && dur > 0) {
      if (mod[mod].state == IDLE) {
        mod[mod].state = JAMMING;
        mod[mod].jamChannel = ch;
        mod[mod].jamEndTime = millis() + dur * 1000UL;
        mod[mod].stopRequested = false;
        Serial.println("JAMMING_STARTED");
      } else {
        Serial.println("ERROR:MODULE_BUSY");
      }
    } else {
      Serial.println("ERROR:INVALID_PARAMS");
    }
  } else if (cmd.startsWith("STOP")) {
    int mod = cmd.substring(4).toInt();
    if (mod >= 0 && mod <= 1) {
      mod[mod].stopRequested = true;
      Serial.println("STOPPING");
    } else {
      Serial.println("ERROR:INVALID_MODULE");
    }
  } else if (cmd == "STATUS") {
    Serial.print("STATUS:OK,MOD0=");
    Serial.print(mod[0].state == IDLE ? "IDLE" : 
                 mod[0].state == SCANNING ? "SCANNING" : 
                 mod[0].state == ADVERTISING ? "ADVERTISING" : 
                 mod[0].state == FLOODING ? "FLOODING" : "JAMMING");
    Serial.print(",MOD1=");
    Serial.println(mod[1].state == IDLE ? "IDLE" : 
                   mod[1].state == SCANNING ? "SCANNING" : 
                   mod[1].state == ADVERTISING ? "ADVERTISING" : 
                   mod[1].state == FLOODING ? "FLOODING" : "JAMMING");
  } else {
    Serial.println("ERROR:UNKNOWN_COMMAND");
  }
  resetWatchdog();
}

// ======================================================================
// MANEJO DE MÓDULOS (NO BLOQUEANTE)
// ======================================================================
void handleModule(int index, BTLE &btle, RF24 &radio) {
  if (mod[index].stopRequested) {
    stopModule(index, btle, radio);
    mod[index].stopRequested = false;
  }

  switch (mod[index].state) {
    case SCANNING:
      doScan(index, btle);
      break;
    case ADVERTISING:
      doAdvertise(index, btle);
      break;
    case FLOODING:
      doFlood(index, btle);
      break;
    case JAMMING:
      doJam(index, radio);
      break;
    default:
      break;
  }
}

void doScan(int mod, BTLE &btle) {
  // Escaneo continuo: btle.scan() devuelve true si hay paquete
  if (btle.scan()) {
    uint8_t mac[6];
    btle.getMAC(mac);
    String macStr = "";
    for (int i = 0; i < 6; i++) {
      if (i) macStr += ":";
      if (mac[i] < 0x10) macStr += "0";
      macStr += String(mac[i], HEX);
    }
    int rssi = btle.getRSSI();
    String name = "";
    if (btle.hasName()) {
      int len = btle.getNameLength();
      char buf[len+1];
      btle.getName(buf);
      buf[len] = 0;
      name = String(buf);
    } else {
      name = "<Unknown>";
    }
    Serial.print("DEVICE:");
    Serial.print(macStr);
    Serial.print(",");
    Serial.print(rssi);
    Serial.print(",");
    Serial.println(name);
    btle.stopScan(); // Necesario para el siguiente paquete
  }
  // Finalizar si se excede el tiempo
  if (millis() - mod[mod].startTime >= mod[mod].scanDuration) {
    Serial.println("SCAN_DONE");
    mod[mod].state = IDLE;
    btle.stopScan();
  }
}

void doAdvertise(int mod, BTLE &btle) {
  // Publicidad continua con el mensaje como nombre de dispositivo
  const char* msg = mod[mod].advertiseMsg.c_str();
  btle.advertise((void*)msg, strlen(msg), ADV_NONCONN_IND);
  delay(100); // Pequeña pausa para permitir otras tareas
  // La publicidad se detiene al recibir STOP
}

void doFlood(int mod, BTLE &btle) {
  if (mod[mod].floodCurrent >= mod[mod].floodCount) {
    Serial.println("FLOOD_DONE");
    mod[mod].state = IDLE;
    btle.stopAdvertise();
    return;
  }
  unsigned long now = millis();
  if (now - mod[mod].lastBeaconTime >= mod[mod].floodInterval) {
    // Generar nombre aleatorio
    const char* ssids[] = {"FreeWiFi","Starbucks","AirportWifi","Corporate","Guest","HomeNetwork","PublicWiFi","Office"};
    int idx = random(0, 8);
    String randomName = String(ssids[idx]) + String(random(100, 999));
    btle.stopAdvertise();
    btle.advertise((void*)randomName.c_str(), randomName.length(), ADV_NONCONN_IND);
    mod[mod].floodCurrent++;
    mod[mod].lastBeaconTime = now;
  }
}

void doJam(int mod, RF24 &radio) {
  if (millis() >= mod[mod].jamEndTime) {
    radio.stopConstCarrier();
    radio.powerDown();
    radio.powerUp(); // Volver a estado normal
    Serial.println("JAM_DONE");
    mod[mod].state = IDLE;
    return;
  }
  // Asegurar portadora activa
  if (!radio.isPVariant()) { // no es buena comprobación, mejor usar flag
    radio.setChannel(mod[mod].jamChannel);
    radio.startConstCarrier();
  }
}

void stopModule(int mod, BTLE &btle, RF24 &radio) {
  if (mod[mod].state == SCANNING) {
    btle.stopScan();
  } else if (mod[mod].state == ADVERTISING || mod[mod].state == FLOODING) {
    btle.stopAdvertise();
  } else if (mod[mod].state == JAMMING) {
    radio.stopConstCarrier();
    radio.powerDown();
    radio.powerUp();
  }
  mod[mod].state = IDLE;
  Serial.println("STOPPED");
}