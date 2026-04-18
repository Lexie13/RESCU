#include <Wire.h>
#include "JoyIT_LSM6DS3TR-C.h"
#include <SparkFun_MAX1704x_Fuel_Gauge_Arduino_Library.h>
#include "TensorFlowLite_ESP32.h"
#include "esp32_fall_detector_waist.h"
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "esp_sleep.h"
#include "driver/rtc_io.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ── No new libraries needed ───────────────────────────────────────────────
// BLEDevice, BLEServer, BLEUtils, BLE2902 are all part of the ESP32 Arduino core
// freertos headers are also built-in

LSM6DS3TR_C  imu;
SFE_MAX1704X lipo;

// ── Pins ──────────────────────────────────────────────────────────────────
#define I2C_SCL     20
#define I2C_SDA     22
#define LED_STATUS  15   // bluetooth
#define LED_POWER   33   // power
#define LED_BAT     32   // low battery
#define BTN_DEFAULT 38   // sleep / wake
#define BTN_POWER   34   // 34 - original
#define BTN_ALERT   39   // 39 - original

// ── Fall detection config ─────────────────────────────────────────────────
#define WINDOW_SIZE         476
#define CHANNELS            6
#define FALL_THRESH         0.958f
#define SAMPLE_US           4202
#define SVM_TRIGGER_G       2.5f
#define GYR_TRIGGER_DPS     100.0f
#define CNN_DELAY_MS        1336UL
#define STILLNESS_STD_DEV_G 0.15f
#define STILLNESS_SAMPLES   50
#define ALERT_TIMEOUT_MS    10000UL
#define COOLDOWN_MS         5000UL
#define BATTERY_READ_MS     3000UL
#define SLEEP_HOLD_MS       3000UL
#define CALIB_SAMPLES       50

// ── BLE config ────────────────────────────────────────────────────────────
#define DEVICE_ID            "RESCU_001"
#define BLE_BATTERY_MS       10000UL   // send battery over BLE every 10s

// Fall alert characteristic has both NOTIFY (device→app) and WRITE (app→device)
// App writes any value to cancel the fall alert remotely
#define FALL_SERVICE_UUID    "18a0ceb2-c728-41f4-af01-f06e15051107"
#define FALL_ALERT_UUID      "44c94768-6610-4039-83eb-07919b82d665"
#define BATTERY_SERVICE_UUID "fe39738b-d108-4571-9ece-8ee6bd1633c9"
#define BATTERY_LEVEL_UUID   "3dd2fe2e-ce13-442e-8165-3dd67b99ce5d"

// ── Axis layout ───────────────────────────────────────────────────────────
// X = vertical, Y = side-to-side, Z = front-to-back
// CNN channels: [Y, X*sign, Z, gyroY, gyroX*sign, gyroZ]

// ── Scaler ────────────────────────────────────────────────────────────────
const float SCALER_MEAN[6]  = { 0.067819f, -0.734005f, -0.018085f,
                                  0.821446f, -0.108692f,  0.314144f };
const float SCALER_SCALE[6] = { 0.434421f,  0.577117f,  0.473865f,
                                 39.104501f, 66.392083f, 49.89272f };

float vertical_sign = -1.0f;

// ── State machine ─────────────────────────────────────────────────────────
enum SystemState { IDLE, WAITING_FOR_CNN, RUNNING_CNN, FALL_DETECTED, EMERGENCY };

// volatile so both cores see changes immediately
volatile SystemState state = IDLE;

// ── Shared variables between cores ───────────────────────────────────────
volatile bool  fall_signal         = false;
volatile bool  emergency_signal    = false;
volatile bool  ble_cancel_request  = false;
volatile float battery_soc_shared  = 0.0f;
volatile bool  device_connected    = false;

volatile uint32_t ble_alert_timeout_ms = ALERT_TIMEOUT_MS;  // default 10000ms, updated by app

SemaphoreHandle_t state_mutex;

// ── Fall detection globals (Core 1 only) ─────────────────────────────────
float circ_buf[WINDOW_SIZE][CHANNELS];
int   write_head   = 0;
bool  buf_ready    = false;
int   sample_count = 0;
double battery_soc = 0.0;
bool   battery_low = false;

namespace {
  tflite::ErrorReporter*    error_reporter = nullptr;
  const tflite::Model*      tflite_model   = nullptr;
  tflite::MicroInterpreter* interpreter    = nullptr;
  TfLiteTensor* input  = nullptr;
  TfLiteTensor* output = nullptr;
  constexpr int kTensorArenaSize = 75 * 1024;
  uint8_t* tensor_arena = nullptr;
}

unsigned long last_sample_us       = 0;
unsigned long last_trigger_ms      = 0;
unsigned long last_ui_ms           = 0;
unsigned long last_msg_ms          = 0;
unsigned long last_battery_ms      = 0;
unsigned long fall_start_ms        = 0;
unsigned long svm_trigger_ms       = 0;
unsigned long power_btn_held_since = 0;
bool          power_btn_was_held   = false;
bool          lastPowerBtnState    = HIGH;
bool          lastBtnState         = HIGH;

Acceleration acceleration;
Gyroscope    gyroscope;
float        temperature;

// ── BLE globals (Core 0 task) ─────────────────────────────────────────────
BLEServer*         pServer        = nullptr;
BLECharacteristic* pFallAlert     = nullptr;
BLECharacteristic* pBatteryLevel  = nullptr;
bool               needsAdvRestart = false;
int                fallCount       = 0;
unsigned long      last_ble_bat_ms = 0;

// ── BLE helpers ───────────────────────────────────────────────────────────
String getReadableTime() {
  unsigned long s = millis() / 1000;
  char buffer[10];
  sprintf(buffer, "%02lu:%02lu:%02lu", (s / 3600), (s % 3600) / 60, s % 60);
  return String(buffer);
}

void sendFallAlert() {
  if (device_connected) {
    fallCount++;
    String payload = "{\"type\":\"FALL\",\"device_id\":\"" DEVICE_ID "\","
                     "\"fall_count\":" + String(fallCount) +
                     ",\"timestamp\":\"" + getReadableTime() + "\"}";
    pFallAlert->setValue(payload.c_str());
    pFallAlert->notify();
    Serial.println("[BLE] Fall alert sent: " + payload);
  }
}

void sendEmergencyAlert() {
  if (device_connected) {
    String payload = "{\"type\":\"EMERGENCY\",\"device_id\":\"" DEVICE_ID "\","
                     "\"fall_count\":" + String(fallCount) +
                     ",\"timestamp\":\"" + getReadableTime() + "\"}";
    pFallAlert->setValue(payload.c_str());
    pFallAlert->notify();
    Serial.println("[BLE] Emergency alert sent: " + payload);
  }
}

void sendBatteryLevel() {
  if (device_connected) {
    String payload = "{\"type\":\"BATTERY\",\"device_id\":\"" DEVICE_ID "\","
                     "\"battery_pct\":" + String((int)battery_soc_shared) +
                     ",\"timestamp\":\"" + getReadableTime() + "\"}";
    pBatteryLevel->setValue(payload.c_str());
    pBatteryLevel->notify();
  }
}

// ── BLE server callbacks ──────────────────────────────────────────────────
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) {
    device_connected = true;
    digitalWrite(LED_STATUS, HIGH);
    Serial.println("[BLE] Device connected.");
    sendBatteryLevel();
  }
  void onDisconnect(BLEServer* pServer) {
    device_connected  = false;
    needsAdvRestart   = true;
    digitalWrite(LED_STATUS, LOW);
    Serial.println("[BLE] Device disconnected.");
  }
};

// ── Fall alert WRITE callback — app cancels alert by writing any value ────
class FallAlertCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pChar) {
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    ble_cancel_request = true;
    xSemaphoreGive(state_mutex);
    Serial.println("[BLE] Cancel request received from app.");
  }
};

// ── BLE task — runs on Core 0 ─────────────────────────────────────────────
void ble_task(void* pvParams) {
  bool last_fall_signal      = false;
  bool last_emergency_signal = false;

  for (;;) {
    unsigned long now_ms = millis();

    if (needsAdvRestart && (now_ms - last_ble_bat_ms >= 500)) {
      BLEDevice::startAdvertising();
      needsAdvRestart  = false;
      last_ble_bat_ms  = now_ms;
      Serial.println("[BLE] Advertising restarted.");
    }

    bool current_fall, current_emergency;
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    current_fall      = fall_signal;
    current_emergency = emergency_signal;
    xSemaphoreGive(state_mutex);

    if (current_fall && !last_fall_signal) {
      sendFallAlert();
    }
    last_fall_signal = current_fall;

    if (current_emergency && !last_emergency_signal) {
      sendEmergencyAlert();
    }
    last_emergency_signal = current_emergency;

    if (device_connected && (now_ms - last_ble_bat_ms >= BLE_BATTERY_MS)) {
      last_ble_bat_ms = now_ms;
      sendBatteryLevel();
    }

    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

// ── Hardware functions (Core 1) ───────────────────────────────────────────
void calibrateVerticalAxis() {
  Serial.println("[Calib] Measuring vertical axis...");
  float sum = 0.0f;
  for (int i = 0; i < CALIB_SAMPLES; i++) {
    imu.readAll(acceleration, gyroscope, temperature);
    sum += acceleration.x;
    delay(5);
  }
  float avg_x = sum / CALIB_SAMPLES;
  if (avg_x > 0.0f) {
    vertical_sign = -1.0f;
    Serial.print("[Calib] Right-side up (acc.x="); Serial.print(avg_x, 3); Serial.println("g).");
  } else {
    vertical_sign = 1.0f;
    Serial.print("[Calib] Upside down (acc.x="); Serial.print(avg_x, 3); Serial.println("g).");
  }
}

void updateBatLED(unsigned long now_ms) {
  digitalWrite(LED_BAT, battery_low ? (now_ms / 500) % 2 : LOW);
}

void enterDeepSleep() {
  Serial.println("[Power] Entering deep sleep.");
  Serial.flush();
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_POWER, HIGH); delay(200);
    digitalWrite(LED_POWER, LOW);  delay(200);
  }
  digitalWrite(LED_STATUS, LOW);
  digitalWrite(LED_BAT,    LOW);
  digitalWrite(LED_POWER,  LOW);
  esp_sleep_enable_ext0_wakeup((gpio_num_t)BTN_DEFAULT, 0);
  rtc_gpio_pullup_en((gpio_num_t)BTN_DEFAULT);
  rtc_gpio_pulldown_dis((gpio_num_t)BTN_DEFAULT);
  esp_deep_sleep_start();
}

void checkPowerButton(unsigned long now_ms) {
  if (millis() < 2000) return;
  bool currentPowerBtn = digitalRead(BTN_POWER);   // fixed: was BTN_DEFAULT
  if (currentPowerBtn == LOW) {
    if (lastPowerBtnState == HIGH) {
      power_btn_held_since = now_ms;
      power_btn_was_held   = false;
    } else if (!power_btn_was_held) {
      if ((now_ms - power_btn_held_since) >= SLEEP_HOLD_MS) {
        power_btn_was_held = true;
        enterDeepSleep();
      }
    }
  } else {
    if (!power_btn_was_held) digitalWrite(LED_POWER, HIGH);
    power_btn_was_held = false;
  }
  lastPowerBtnState = currentPowerBtn;
}

float readBattery() {
  battery_soc = lipo.getSOC();
  battery_low = (battery_soc < 20.0);
  battery_soc_shared = (float)battery_soc;

  Serial.print("[Battery] "); Serial.print(battery_soc, 1); Serial.print(" %");
  if (battery_low) Serial.print("  *** LOW ***");
  Serial.println();
  return (float)battery_soc;
}

float run_inference() {
  int oldest = write_head;
  for (int i = 0; i < WINDOW_SIZE; i++) {
    int idx = (oldest + i) % WINDOW_SIZE;
    for (int c = 0; c < CHANNELS; c++) {
      input->data.f[i * CHANNELS + c] = circ_buf[idx][c];
    }
  }
  if (interpreter->Invoke() != kTfLiteOk) {
    Serial.println("Invoke failed!"); return 0.0f;
  }
  if (output->type == kTfLiteFloat32) {
    return output->data.f[0];
  } else if (output->type == kTfLiteInt8) {
    int8_t quantized_val = output->data.int8[0];
    return (quantized_val - output->params.zero_point) * output->params.scale;
  }
  Serial.println("Unknown output type!"); return 0.0f;
}

float check_stillness() {
  float ax_arr[STILLNESS_SAMPLES], ay_arr[STILLNESS_SAMPLES], az_arr[STILLNESS_SAMPLES];
  float sum_x = 0.0f, sum_y = 0.0f, sum_z = 0.0f;
  for (int i = 0; i < STILLNESS_SAMPLES; i++) {
    int idx = (write_head - 1 - i + WINDOW_SIZE) % WINDOW_SIZE;
    ax_arr[i] = circ_buf[idx][0] * SCALER_SCALE[0] + SCALER_MEAN[0];
    ay_arr[i] = circ_buf[idx][1] * SCALER_SCALE[1] + SCALER_MEAN[1];
    az_arr[i] = circ_buf[idx][2] * SCALER_SCALE[2] + SCALER_MEAN[2];
    sum_x += ax_arr[i]; sum_y += ay_arr[i]; sum_z += az_arr[i];
  }
  float mean_x = sum_x / STILLNESS_SAMPLES;
  float mean_y = sum_y / STILLNESS_SAMPLES;
  float mean_z = sum_z / STILLNESS_SAMPLES;
  float variance = 0.0f;
  for (int i = 0; i < STILLNESS_SAMPLES; i++) {
    variance += (ax_arr[i]-mean_x)*(ax_arr[i]-mean_x) +
                (ay_arr[i]-mean_y)*(ay_arr[i]-mean_y) +
                (az_arr[i]-mean_z)*(az_arr[i]-mean_z);
  }
  return sqrtf(variance / STILLNESS_SAMPLES);
}

// ── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pinMode(LED_STATUS,  OUTPUT);
  pinMode(LED_POWER,   OUTPUT);
  pinMode(LED_BAT,     OUTPUT);
  pinMode(BTN_DEFAULT, INPUT_PULLUP);
  pinMode(BTN_POWER,   INPUT_PULLUP);
  pinMode(BTN_ALERT,   INPUT_PULLUP);

  digitalWrite(LED_POWER,  HIGH);
  digitalWrite(LED_STATUS, LOW);
  digitalWrite(LED_BAT,    LOW);

  esp_sleep_wakeup_cause_t wakeup_reason = esp_sleep_get_wakeup_cause();
  Serial.println(wakeup_reason == ESP_SLEEP_WAKEUP_EXT0
    ? "[Power] Woke from deep sleep." : "[Power] Fresh boot.");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  imu.begin();
  calibrateVerticalAxis();

  if (lipo.begin() == false) {
    Serial.println("MAX17043 not detected. Check wiring.");
  } else {
    lipo.quickStart();
    lipo.setThreshold(20);
    Serial.println("Fuel gauge ready.");
    readBattery();
  }

  // ── TFLite init ───────────────────────────────────────────────────────
  tensor_arena = (uint8_t*)malloc(kTensorArenaSize);
  if (!tensor_arena) { Serial.println("MALLOC FAILED"); while (1); }

  static tflite::MicroErrorReporter micro_error_reporter;
  error_reporter = &micro_error_reporter;

  tflite_model = tflite::GetModel(esp32_fall_detector_waist_tflite);
  if (tflite_model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("Model schema mismatch!"); while (1);
  }

  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      tflite_model, resolver, tensor_arena, kTensorArenaSize, error_reporter);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("AllocateTensors FAILED"); while (1);
  }
  Serial.print("Arena used: "); Serial.print(interpreter->arena_used_bytes()); Serial.println(" bytes");
  input  = interpreter->input(0);
  output = interpreter->output(0);

  // ── BLE init ──────────────────────────────────────────────────────────
  BLEDevice::init("RESCU_DEVICE");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());

  BLEService* pFallService = pServer->createService(FALL_SERVICE_UUID);
  pFallAlert = pFallService->createCharacteristic(
      FALL_ALERT_UUID,
      BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_WRITE);
  pFallAlert->addDescriptor(new BLE2902());
  pFallAlert->setCallbacks(new FallAlertCallbacks());
  pFallService->start();

  BLEService* pBattService = pServer->createService(BATTERY_SERVICE_UUID);
  pBatteryLevel = pBattService->createCharacteristic(
      BATTERY_LEVEL_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  pBatteryLevel->addDescriptor(new BLE2902());
  pBattService->start();

  BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(FALL_SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
  Serial.println("[BLE] Advertising started.");

  state_mutex = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(
      ble_task,    // function
      "ble_task",  // name
      4096,        // stack size
      NULL,        // params
      1,           // priority
      NULL,        // handle
      0            // Core 0
  );

  Serial.println("Ready. Monitoring for falls...");
}

// ── Main loop — Core 1 (fall detection) ───────────────────────────────────
void loop() {
  unsigned long now_us = micros();
  unsigned long now_ms = millis();

  checkPowerButton(now_ms);

  // ── 1. Sample IMU at 238Hz (only when BLE connected) ─────────────────
  if (device_connected && (now_us - last_sample_us >= SAMPLE_US) && state != EMERGENCY) {
    last_sample_us = now_us;

    imu.readAll(acceleration, gyroscope, temperature);
    float raw[6] = {
      acceleration.y,
      vertical_sign * acceleration.x,
      acceleration.z,
      gyroscope.y,
      vertical_sign * gyroscope.x,
      gyroscope.z
    };

    for (int c = 0; c < CHANNELS; c++) {
      circ_buf[write_head][c] = (raw[c] - SCALER_MEAN[c]) / SCALER_SCALE[c];
    }
    write_head = (write_head + 1) % WINDOW_SIZE;
    sample_count++;
    if (sample_count >= WINDOW_SIZE) buf_ready = true;

    // ── 2. Pre-screener ───────────────────────────────────────────────────
    if (buf_ready && state == IDLE) {
      float svm     = sqrtf(raw[0]*raw[0] + raw[1]*raw[1] + raw[2]*raw[2]);
      float gyr_mag = sqrtf(raw[3]*raw[3] + raw[4]*raw[4] + raw[5]*raw[5]);
      bool  cooldown_ok = (now_ms - last_trigger_ms) > COOLDOWN_MS;

      if (svm >= SVM_TRIGGER_G && gyr_mag >= GYR_TRIGGER_DPS && cooldown_ok) {
        last_trigger_ms = now_ms;
        svm_trigger_ms  = now_ms;
        state = WAITING_FOR_CNN;
        Serial.print("[Pre-screen] SVM="); Serial.print(svm);
        Serial.print("g  GYR="); Serial.print(gyr_mag);
        Serial.println("dps — waiting for post-fall data...");
      }
    }

    // ── 3. Fire CNN after delay ───────────────────────────────────────────
    if (state == WAITING_FOR_CNN && (now_ms - svm_trigger_ms >= CNN_DELAY_MS)) {
      state = RUNNING_CNN;
      float prob    = run_inference();
      float std_dev = check_stillness();

      Serial.print("[CNN] prob="); Serial.print(prob);
      Serial.print("  [Stillness] StdDev="); Serial.println(std_dev);

      if (prob >= FALL_THRESH && std_dev < STILLNESS_STD_DEV_G) {
        Serial.println(">>> FALL CONFIRMED");
        xSemaphoreTake(state_mutex, portMAX_DELAY);
        state       = FALL_DETECTED;
        fall_signal = true;
        xSemaphoreGive(state_mutex);
        fall_start_ms = millis();
      } else {
        Serial.println(prob < FALL_THRESH ? "[CNN] Not a fall." : "[Rejected] Post-event motion.");
        state = IDLE;
      }
    }
  }

  // ── 4. Battery read (only when BLE connected) ─────────────────────────
  if (device_connected && (now_ms - last_battery_ms >= BATTERY_READ_MS)) {
    last_battery_ms = now_ms;
    readBattery();
  }

  // ── 5. UI & state machine at 100ms ────────────────────────────────────
  if (now_ms - last_ui_ms >= 100) {
    last_ui_ms = now_ms;
    updateBatLED(now_ms);

    bool currentBtnState   = digitalRead(BTN_ALERT);
    bool buttonJustPressed = (millis() > 5000) &&
                             (currentBtnState == LOW && lastBtnState == HIGH);

    bool app_cancel = false;
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    if (ble_cancel_request) {
      app_cancel         = true;
      ble_cancel_request = false;
    }
    xSemaphoreGive(state_mutex);

    switch (state) {
      case IDLE:
        if (buttonJustPressed) {
          Serial.println("Manual SOS triggered.");
          xSemaphoreTake(state_mutex, portMAX_DELAY);
          state            = EMERGENCY;
          emergency_signal = true;
          fall_signal      = true;
          xSemaphoreGive(state_mutex);
        }
        break;

      case WAITING_FOR_CNN:
        break;

      case RUNNING_CNN:
        break;

      case FALL_DETECTED: {
        unsigned long elapsed   = now_ms - fall_start_ms;
        unsigned long remaining = (elapsed < ALERT_TIMEOUT_MS)
                                  ? (ALERT_TIMEOUT_MS - elapsed) / 1000 : 0;
        if (now_ms - last_msg_ms >= 1000) {
          last_msg_ms = now_ms;
          Serial.print("Fall alert — "); Serial.print(remaining); Serial.println("s to cancel");
        }

        if (buttonJustPressed || app_cancel) {
          Serial.println(app_cancel ? "App cancelled alert." : "User cancelled alert.");
          xSemaphoreTake(state_mutex, portMAX_DELAY);
          fall_signal = false;
          state       = IDLE;
          xSemaphoreGive(state_mutex);
        }
        if (elapsed > ble_alert_timeout_ms) {
          Serial.println("!!! EMERGENCY — no user response !!!");
          xSemaphoreTake(state_mutex, portMAX_DELAY);
          state            = EMERGENCY;
          emergency_signal = true;
          xSemaphoreGive(state_mutex);
        }
        break;
      }

      case EMERGENCY:
        if (buttonJustPressed || app_cancel) {
          Serial.println(app_cancel ? "App reset emergency." : "Emergency cancelled by user.");
          xSemaphoreTake(state_mutex, portMAX_DELAY);
          state            = IDLE;
          emergency_signal = false;
          fall_signal      = false;
          xSemaphoreGive(state_mutex);
        }
        break;
    }
    lastBtnState = currentBtnState;
  }
}
