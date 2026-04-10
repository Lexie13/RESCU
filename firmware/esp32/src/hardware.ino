#include <Wire.h>
#include "JoyIT_LSM6DS3TR-C.h"
#include <Adafruit_MPL3115A2.h>
#include <SparkFun_MAX1704x_Fuel_Gauge_Arduino_Library.h>

Adafruit_MPL3115A2 baro;
LSM6DS3TR_C imu;
SFE_MAX1704X lipo; // Defaults to the MAX17043

// I2C pins
#define I2C_SCL 20
#define I2C_SDA 22

// LEDs
#define LED_STATUS 25
#define LED_POWER 26

// Buttons
#define BTN_DEFAULT 38
#define BTN_POWER 14
#define BTN_ALERT 15

#define VBATPIN A13

enum SystemState {
  IDLE,
  FALL_DETECTED,
  EMERGENCY
};

SystemState state = IDLE;
float measuredvbat;

Acceleration acceleration;
Gyroscope gyroscope;
float temperature;

float pressure;
float altitude;
float initialAlt;

double voltage = 0; // Variable to keep track of LiPo voltage
double soc = 0; // Variable to keep track of LiPo state-of-charge (SOC)
bool alert; // Variable to keep track of whether alert has been triggered

unsigned long startTime;

bool fall_detected;
bool emergency;

bool lastBtnState = HIGH; // Assumes INPUT_PULLUP (HIGH = unpressed)

void setup() {
  // put your setup code here, to run once:
  Serial.begin(500000);
  // delay(3000);
  // Wire.begin(I2C_SDA, I2C_SCL);
  // Wire.begin();

  // LED setup
  pinMode(LED_STATUS, OUTPUT);
  pinMode(LED_POWER, OUTPUT);

  // Button setup (internal pull-up)
  pinMode(BTN_DEFAULT, INPUT_PULLUP);
  pinMode(BTN_POWER, INPUT_PULLUP);
  pinMode(BTN_ALERT, INPUT_PULLUP);

  Serial.println("Fall Detector Starting...");
  delay(3000);
  // imu
  imu.begin();
  
  // barometer
  baro.begin();
  float initialPressure = baro.getPressure(); // Get current room pressure
  baro.setSeaPressure(initialPressure);
  initialAlt = baro.getAltitude();
  // fuel gauge
  // lipo.enableDebugging();
  
  // // Set up the MAX17043 LiPo fuel gauge:
  // if (lipo.begin() == false) // Connect to the MAX17043 using the default wire port
  // {
  //   Serial.println(F("MAX17043 not detected. Please check wiring. Freezing."));
  //   while (1)
  //     ;
  // }

  // lipo.quickStart();
  // lipo.setThreshold(20); // Set alert threshold to 20%.

}

void loop() {
  // put your main code here, to run repeatedly:
  // handleButtons();
  // voltage = lipo.getVoltage();
  // Serial.print("Voltage: ");
  // Serial.print(voltage);  // Print the battery voltage
  // Serial.println(" V");

  // soc = lipo.getSOC();
  // Serial.print("Percentage: ");
  // Serial.print(soc); // Print the battery state of charge
  // Serial.println(" %");

  bool currentBtnState = digitalRead(BTN_DEFAULT);

  bool buttonJustPressed = (currentBtnState == LOW && lastBtnState == HIGH);
  
  measuredvbat = analogReadMilliVolts(VBATPIN);
  measuredvbat *= 2;    // we divided by 2, so multiply back
  measuredvbat /= 1000; // convert to volts!
  Serial.print("VBat: " ); Serial.println(measuredvbat);

  switch (state) {
    case IDLE:
      // readSensors();
      digitalWrite(LED_STATUS, LOW); 

      fall_detected = false;
      emergency = false;

      if(acceleration.z < 0.2) {
        Serial.println("\nFall detected!");
        state = FALL_DETECTED;
        startTime = millis();
      }
      // if (digitalRead(BTN_DEFAULT) == LOW) {
      //   Serial.println("Manual SOS!");
      //   state = EMERGENCY;
      // }
      if (buttonJustPressed) {
        Serial.println("\nManual SOS!");
        state = EMERGENCY;
      }
      break;

    case FALL_DETECTED:
      digitalWrite(LED_STATUS, HIGH);

      fall_detected = true;
      emergency = false;

      // if (digitalRead(BTN_DEFAULT) == LOW) {
      //   Serial.println("Button Pressed! Breaking out.");
      //   state = IDLE;
      // }
      if (buttonJustPressed) {
        Serial.println("Button Pressed! Breaking out.");
        state = IDLE;
      }
      if(millis() - startTime > 10000) {
        Serial.println("!!! EMERGENCY !!!");
        state = EMERGENCY;
      }
      break;

    case EMERGENCY:
      digitalWrite(LED_STATUS, HIGH);

      fall_detected = false;
      emergency = true;

      // if (digitalRead(BTN_DEFAULT) == LOW) {
      //   Serial.println("Button Pressed! Resetting.");
      //   state = IDLE;
      // }
      if (buttonJustPressed) {
        Serial.println("Button Pressed! Resetting.");
        state = IDLE;
      }
      break;
  }
  lastBtnState = currentBtnState;
  delay(100);  // 20Hz loop (adjust later)
}

// =======================
// Button Handling
// =======================

// void handleButtons() {
//   if (digitalRead(BTN_ALERT) == LOW) {
//     state = IDLE;
//     digitalWrite(LED_STATUS, LOW);
//   }
// }
int loopCounter = 0;

void readSensors() {
  readIMU(); // High priority: Read every 50ms
  
  loopCounter++;
  if (loopCounter >= 20) { // Lower priority: Read every 500ms (0.5 sec)
    readBarometer();
    loopCounter = 0;
  }
}

void readIMU() {
  // Replace with actual register reads
  // read all sensor data
  imu.readAll(acceleration, gyroscope, temperature);
  // print acceleration data
  Serial.print(F("\nA[g]  x: ")); Serial.print(acceleration.x, 4);
  Serial.print(F("  y: "));     Serial.print(acceleration.y, 4);
  Serial.print(F("  z: "));     Serial.print(acceleration.z, 4);

  // // print gyroscope data
  // Serial.print(F(" | G[dps] x: ")); Serial.print(gyroscope.x, 2);
  // Serial.print(F("  y: "));         Serial.print(gyroscope.y, 2);
  // Serial.print(F("  z: "));         Serial.print(gyroscope.z, 2);
}

void readBarometer() {
  pressure = baro.getPressure();
  altitude = baro.getAltitude();

  // Serial.print("\npressure:"); Serial.print(pressure, 4); Serial.print(" hPa");
  Serial.print("\nAltitude:"); Serial.print(altitude + initialAlt, 4); Serial.print(" m");
}

// void waitForButton() {
//   Serial.println("Waiting 5 seconds for button press...");
  
//   // Record the start time
//   bool buttonPressed = false;

//   // Loop until 5 seconds pass OR button is pressed
//   // Since you used INPUT_PULLUP, the button is LOW when pressed
//   while (millis() - startTime < 5000) {
    
//     if (digitalRead(BTN_DEFAULT) == LOW) {
//       Serial.println("Button Pressed! Breaking out.");
//       buttonPressed = true;
//       break; // Exit the while loop immediately
//     }
//   }

//   if (!buttonPressed) {
//     Serial.println("Timed out after 5 seconds.");
//   }

//   digitalWrite(LED_STATUS, LOW); // Ensure LED is off before returning
// }

