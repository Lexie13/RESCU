#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#define FALL_SERVICE_UUID    "18a0ceb2-c728-41f4-af01-f06e15051107"
#define FALL_ALERT_UUID      "44c94768-6610-4039-83eb-07919b82d665"
#define BATTERY_SERVICE_UUID "fe39738b-d108-4571-9ece-8ee6bd1633c9"
#define BATTERY_LEVEL_UUID   "3dd2fe2e-ce13-442e-8165-3dd67b99ce5d"

#define LED_PIN 12

BLEServer *pServer = nullptr;
BLECharacteristic *pFallAlert = nullptr;
BLECharacteristic *pBatteryLevel = nullptr;

bool deviceConnected = false;
bool needsAdvertisingRestart = false;
unsigned long lastBatteryTime = 0;
int fakeBattery = 85;
int fallCount = 0;

String getReadableTime() {
    unsigned long s = millis() / 1000;
    char buffer[10];
    sprintf(buffer, "%02lu:%02lu:%02lu", (s/3600), (s%3600)/60, s%60);
    return String(buffer);
}

void sendFallAlert() {
    if (deviceConnected) {
        fallCount++;
        String payload = "{\"type\":\"FALL\",\"device_id\":\"RESCU_001\",\"fall_count\":" + String(fallCount) + ",\"timestamp\":\"" + getReadableTime() + "\"}";
        pFallAlert->setValue(payload.c_str());
        pFallAlert->notify();
        Serial.println("Fall Alert: " + payload);
    }
}

void sendBatteryLevel() {
    fakeBattery = max(0, fakeBattery - 1);
    String payload = "{\"type\":\"BATTERY\",\"device_id\":\"RESCU_001\",\"battery_pct\":" + String(fakeBattery) + ",\"timestamp\":\"" + getReadableTime() + "\"}";
    pBatteryLevel->setValue(payload.c_str());
    pBatteryLevel->notify();
}

class ServerCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        deviceConnected = true;
        // Turn on LED
        digitalWrite(LED_PIN, HIGH);
        // Trigger immediate battery update upon connection
        sendBatteryLevel();
    }
    void onDisconnect(BLEServer* pServer) {
        deviceConnected = false;
        // Turn off LED
        digitalWrite(LED_PIN, LOW);
        needsAdvertisingRestart = true;
    }
};

void setup() {
    Serial.begin(115200);
    pinMode(LED_PIN, OUTPUT);

    BLEDevice::init("RESCU_DEVICE");
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());

    // Fall Service
    BLEService* pFallService = pServer->createService(FALL_SERVICE_UUID);
    pFallAlert = pFallService->createCharacteristic(FALL_ALERT_UUID, BLECharacteristic::PROPERTY_NOTIFY);
    pFallAlert->addDescriptor(new BLE2902());
    pFallService->start();

    // Battery Service
    BLEService* pBattService = pServer->createService(BATTERY_SERVICE_UUID);
    pBatteryLevel = pBattService->createCharacteristic(BATTERY_LEVEL_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
    pBatteryLevel->addDescriptor(new BLE2902());
    pBattService->start();

    // SCALABILITY: Add the Service UUID to Advertising
    BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(FALL_SERVICE_UUID); // Critical for the browser filter
    pAdvertising->setScanResponse(true);
    pAdvertising->setMinPreferred(0x06);
    pAdvertising->setMinPreferred(0x12);
    BLEDevice::startAdvertising();

    Serial.println("Advertising with Service UUID...");
}

void loop() {
    if (Serial.available() > 0 && Serial.readStringUntil('\n').indexOf("fall!") > -1) {
        sendFallAlert();
    }

    if (needsAdvertisingRestart) {
        delay(100);
        BLEDevice::startAdvertising();
        needsAdvertisingRestart = false;
    }

    if (deviceConnected) {
        if (millis() - lastBatteryTime > 10000) {
            sendBatteryLevel();
            lastBatteryTime = millis();
        }
    } else {
    }
    delay(10);
}