#include <Wire.h>
#include "JoyIT_LSM6DS3TR-C.h"
#include <SparkFun_MAX1704x_Fuel_Gauge_Arduino_Library.h>
#include "TensorFlowLite_ESP32.h"
// #include "esp32_fall_detector_waist_big.h"
#include "esp32_fall_detector_waist_small.h"
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

LSM6DS3TR_C  imu;
SFE_MAX1704X lipo;

#define I2C_SCL     20
#define I2C_SDA     22
#define LED_STATUS  25
#define LED_POWER   26
#define BTN_DEFAULT 38
#define BTN_POWER   14
#define BTN_ALERT   15

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

// Read battery every 30 seconds — fuel gauge is slow, no need to poll faster
#define BATTERY_READ_MS     30000UL

// // -------BIG---------------------------------------------------
// const float SCALER_MEAN[6]  = { 0.0678f, -0.7340f, -0.0180f,
//                                   0.8214f, -0.1086f,  0.3141f };
// const float SCALER_SCALE[6] = { 0.4739f,  0.5771f,  0.4738f,
//                                  39.1045f, 66.3920f, 49.8927f };

// -------SMALL-------------------------------------------------
const float SCALER_MEAN[6]  = { 0.067819f, -0.734005f, -0.018085f,
                                  0.821446f, -0.108692f,  0.314144f };
const float SCALER_SCALE[6] = { 0.434421f,  0.577117f,  0.473865f,
                                 39.104501f, 66.392083f, 49.89272f };

enum SystemState { IDLE, WAITING_FOR_CNN, RUNNING_CNN, FALL_DETECTED, EMERGENCY };
SystemState state = IDLE;

float circ_buf[WINDOW_SIZE][CHANNELS];
int   write_head   = 0;
bool  buf_ready    = false;
int   sample_count = 0;

bool fall_signal      = false;
bool emergency_signal = false;

// ── Battery state ─────────────────────────────────────────────────────────
double battery_voltage = 0.0;
double battery_soc     = 0.0;   // state of charge (%)

namespace {
  tflite::ErrorReporter*    error_reporter = nullptr;
  const tflite::Model*      model          = nullptr;
  tflite::MicroInterpreter* interpreter    = nullptr;
  TfLiteTensor* input  = nullptr;
  TfLiteTensor* output = nullptr;
  constexpr int kTensorArenaSize = 75 * 1024;
  uint8_t* tensor_arena = nullptr;
}

unsigned long last_sample_us  = 0;
unsigned long last_trigger_ms = 0;
unsigned long last_ui_ms      = 0;
unsigned long last_msg_ms     = 0;
unsigned long last_battery_ms = 0;
unsigned long fall_start_ms   = 0;
unsigned long svm_trigger_ms  = 0;

bool lastBtnState = HIGH;

Acceleration acceleration;
Gyroscope    gyroscope;
float        temperature;

// ── Battery read function ─────────────────────────────────────────────────
// Returns state of charge (0.0 - 100.0 %).
// Also updates battery_voltage and battery_soc globals and prints both.
float readBattery() {
  battery_voltage = lipo.getVoltage();
  battery_soc     = lipo.getSOC();

  Serial.print("[Battery] ");
  Serial.print(battery_voltage, 2);
  Serial.print(" V  |  ");
  Serial.print(battery_soc, 1);
  Serial.println(" %");

  if (battery_soc < 20.0) {
    Serial.println("[Battery] WARNING: Low battery!");
  }

  return (float)battery_soc;
}

// ── Run CNN inference ─────────────────────────────────────────────────────
float run_inference() {
  int oldest = write_head;
  for (int i = 0; i < WINDOW_SIZE; i++) {
    int idx = (oldest + i) % WINDOW_SIZE;
    for (int c = 0; c < CHANNELS; c++) {
      input->data.f[i * CHANNELS + c] = circ_buf[idx][c];
    }
  }

  if (interpreter->Invoke() != kTfLiteOk) {
    Serial.println("Invoke failed!");
    return 0.0f;
  }

  if (output->type == kTfLiteFloat32) {
    return output->data.f[0];
  } else if (output->type == kTfLiteInt8) {
    int8_t quantized_val = output->data.int8[0];
    float  scale         = output->params.scale;
    int    zero_point    = output->params.zero_point;
    return (quantized_val - zero_point) * scale;
  } else {
    Serial.println("Unknown output tensor type!");
    return 0.0f;
  }
}

// ── Post-event stillness check (Standard Deviation) ──────────────────────
float check_stillness() {
  float ax_arr[STILLNESS_SAMPLES];
  float ay_arr[STILLNESS_SAMPLES];
  float az_arr[STILLNESS_SAMPLES];
  float sum_x = 0.0f, sum_y = 0.0f, sum_z = 0.0f;

  for (int i = 0; i < STILLNESS_SAMPLES; i++) {
    int idx = (write_head - 1 - i + WINDOW_SIZE) % WINDOW_SIZE;
    ax_arr[i] = circ_buf[idx][0] * SCALER_SCALE[0] + SCALER_MEAN[0];
    ay_arr[i] = circ_buf[idx][1] * SCALER_SCALE[1] + SCALER_MEAN[1];
    az_arr[i] = circ_buf[idx][2] * SCALER_SCALE[2] + SCALER_MEAN[2];
    sum_x += ax_arr[i];
    sum_y += ay_arr[i];
    sum_z += az_arr[i];
  }

  float mean_x = sum_x / STILLNESS_SAMPLES;
  float mean_y = sum_y / STILLNESS_SAMPLES;
  float mean_z = sum_z / STILLNESS_SAMPLES;

  float variance = 0.0f;
  for (int i = 0; i < STILLNESS_SAMPLES; i++) {
    variance += (ax_arr[i] - mean_x) * (ax_arr[i] - mean_x) +
                (ay_arr[i] - mean_y) * (ay_arr[i] - mean_y) +
                (az_arr[i] - mean_z) * (az_arr[i] - mean_z);
  }
  return sqrtf(variance / STILLNESS_SAMPLES);
}

// ── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(LED_STATUS,  OUTPUT);
  pinMode(LED_POWER,   OUTPUT);
  pinMode(BTN_DEFAULT, INPUT_PULLUP);
  pinMode(BTN_POWER,   INPUT_PULLUP);
  pinMode(BTN_ALERT,   INPUT_PULLUP);

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  imu.begin();

  // ── Fuel gauge init ───────────────────────────────────────────────────
  if (lipo.begin() == false) {
    Serial.println("MAX17043 not detected. Check wiring.");
    // Not fatal — fall detection still works without battery monitoring
  } else {
    lipo.quickStart();
    lipo.setThreshold(20);   // trigger alert flag below 20%
    Serial.println("Fuel gauge ready.");
    readBattery();            // print initial battery level on boot
  }

  // ── TFLite init ───────────────────────────────────────────────────────
  Serial.println("Allocating tensor arena...");
  tensor_arena = (uint8_t*)malloc(kTensorArenaSize);
  if (!tensor_arena) {
    Serial.println("MALLOC FAILED");
    while (1);
  }

  static tflite::MicroErrorReporter micro_error_reporter;
  error_reporter = &micro_error_reporter;

  // model = tflite::GetModel(esp32_fall_detector_waist_big_tflite);
  model = tflite::GetModel(esp32_fall_detector_waist_small_tflite);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("Model schema mismatch!"); while (1);
  }

  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, kTensorArenaSize, error_reporter);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("AllocateTensors FAILED"); while (1);
  }

  Serial.print("Arena used: ");
  Serial.print(interpreter->arena_used_bytes());
  Serial.println(" bytes");

  input  = interpreter->input(0);
  output = interpreter->output(0);
  Serial.println("Ready. Monitoring for falls...");
}

// ── Main loop ─────────────────────────────────────────────────────────────
void loop() {
  unsigned long now_us = micros();
  unsigned long now_ms = millis();

  // ── 1. Sample IMU at 238Hz ─────────────────────────────────────────────
  if (now_us - last_sample_us >= SAMPLE_US) {
    last_sample_us = now_us;

    imu.readAll(acceleration, gyroscope, temperature);
    float raw[6] = {
      acceleration.x,
      -acceleration.y,   // flipped — training had gravity as negative Y
      acceleration.z,
      gyroscope.x,
      gyroscope.y,
      gyroscope.z
    };

    for (int c = 0; c < CHANNELS; c++) {
      circ_buf[write_head][c] = (raw[c] - SCALER_MEAN[c]) / SCALER_SCALE[c];
    }
    write_head = (write_head + 1) % WINDOW_SIZE;
    sample_count++;
    if (sample_count >= WINDOW_SIZE) buf_ready = true;

    // ── 2. Pre-screener ────────────────────────────────────────────────────
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

    // ── 3. Fire CNN after delay ────────────────────────────────────────────
    if (state == WAITING_FOR_CNN && (now_ms - svm_trigger_ms >= CNN_DELAY_MS)) {
      state = RUNNING_CNN;
      float prob    = run_inference();
      float std_dev = check_stillness();

      Serial.print("[CNN] prob="); Serial.print(prob);
      Serial.print("  [Stillness] StdDev="); Serial.println(std_dev);

      if (prob >= FALL_THRESH) {
        if (std_dev < STILLNESS_STD_DEV_G) {
          Serial.println(">>> FALL CONFIRMED");
          state         = FALL_DETECTED;
          fall_start_ms = millis();
        } else {
          Serial.println("[Rejected] Post-event motion detected (ADL)");
          state = IDLE;
        }
      } else {
        Serial.println("[CNN] Not a fall.");
        state = IDLE;
      }
    }
  }

  // ── 4. Battery read every 30 seconds ──────────────────────────────────
  if (now_ms - last_battery_ms >= BATTERY_READ_MS) {
    last_battery_ms = now_ms;
    readBattery();
  }

  // ── 5. UI & state machine at 100ms ────────────────────────────────────
  if (now_ms - last_ui_ms >= 100) {
    last_ui_ms = now_ms;

    bool currentBtnState   = digitalRead(BTN_DEFAULT);
    bool buttonJustPressed = (currentBtnState == LOW && lastBtnState == HIGH);

    switch (state) {
      case IDLE:
        digitalWrite(LED_STATUS, LOW);
        if (buttonJustPressed) {
          Serial.println("Manual SOS triggered.");
          state = EMERGENCY;
        }
        break;

      case WAITING_FOR_CNN:
        digitalWrite(LED_STATUS, (now_ms / 500) % 2);
        break;

      case RUNNING_CNN:
        digitalWrite(LED_STATUS, (now_ms / 150) % 2);
        break;

      case FALL_DETECTED: {
        fall_signal = true;
        digitalWrite(LED_STATUS, HIGH);
        unsigned long elapsed   = now_ms - fall_start_ms;
        unsigned long remaining = (elapsed < ALERT_TIMEOUT_MS)
                                  ? (ALERT_TIMEOUT_MS - elapsed) / 1000 : 0;
        if (now_ms - last_msg_ms >= 1000) {
          last_msg_ms = now_ms;
          Serial.print("Fall alert — "); Serial.print(remaining); Serial.println("s to cancel");
        }
        if (buttonJustPressed) {
          fall_signal = false;
          Serial.println("User cancelled — returning to IDLE");
          state = IDLE;
        }
        if (elapsed > ALERT_TIMEOUT_MS) {
          Serial.println("!!! EMERGENCY — no user response !!!");
          state = EMERGENCY;
        }
        break;
      }

      case EMERGENCY:
        emergency_signal = true;
        digitalWrite(LED_STATUS, (now_ms / 100) % 2);
        if (buttonJustPressed) {
          emergency_signal = false;
          Serial.println("Emergency cancelled by user.");
          state = IDLE;
        }
        break;
    }
    lastBtnState = currentBtnState;
  }
}
