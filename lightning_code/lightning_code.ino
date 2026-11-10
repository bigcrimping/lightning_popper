/**

 Heavy re-use of the following code examples from SparkFun and soldered.com

 **************************************************

 	product: www.solde.red/333097

   @authors     Elias Santistevan, SparkFun Electronics

    Modified by Soldered.com
 ***************************************************/

#include <SPI.h>
#include "AS3935-Lightning-sensor-SOLDERED.h"

#define INDOOR 0x12
#define OUTDOOR 0xE
#define LIGHTNING_INT 0x08
#define DISTURBER_INT 0x04
#define NOISE_INT 0x01
AS3935 lightning;

// Pindef
const int intPin = 20; //Interupt pin from AS3935
const int spiCS = 17; //CS for AS3935
const int motor_int_1 = 8; // Motor Direction 1 of motor driver
const int motor_int_2 = 9; // Motor Direction 2 of motor driver


// Values for modifying the IC's AS3935 settings
byte noiseFloor = 7;
byte watchDogVal = 2;
byte spike = 7;
byte lightningThresh = 1;
byte intVal = 0;

//set test mode to 1 to make the motor turn, useful for debug
//ship with this set to 0 so the motor only fires on a real strike
int test_mode = 0;

// Set by the AS3935 interrupt (rising edge on intPin) and serviced in loop().
// volatile because it is written from an ISR and read from the main loop.
volatile bool strikeDetected = false;

// Minimum time between motor firings. A busy storm can raise several
// lightning interrupts a minute; without this the popper would run
// back-to-back 3 s pulses.
const unsigned long STRIKE_COOLDOWN_MS = 60000UL;
unsigned long lastPopMillis = 0;
bool hasPopped = false;

// Noise/disturber events can fire continuously in an electrically noisy
// environment, so rate-limit their logging to avoid spamming the serial line.
unsigned long noiseCount = 0;
unsigned long disturberCount = 0;
const unsigned long EVENT_LOG_EVERY = 10; // only log every Nth noise/disturber event

// ISR: just flag that the AS3935 raised an interrupt. Keep it minimal -- the
// SPI register read (which also clears the interrupt) is done in loop().
void lightningISR()
{
  strikeDetected = true;
}

// Drive the motor for 3 seconds to fire the popper, then let it coast.
// NOTE: this is a hard, open-loop 3s drive. The motor driver has no software
// current limit or stall protection, so make sure the gearmotor cannot stall
// against an end-stop for the full pulse (mechanical limit / shorter pulse if needed).
void popPopper()
{
  Serial.println("Motor ON");
  digitalWrite(motor_int_1, LOW);   // define the unused half of the H-bridge
  digitalWrite(motor_int_2, HIGH);  // drive one direction
  delay(3000);
  digitalWrite(motor_int_2, LOW);   // coast / let back-EMF settle
  Serial.println("Motor OFF");
}

// Sensor never answered on SPI: sit here blinking the on-board LED so the
// fault is visible without a serial monitor.
void haltWithBlink()
{
  pinMode(LED_BUILTIN, OUTPUT);
  while (1) {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(150);
    digitalWrite(LED_BUILTIN, LOW);
    delay(150);
  }
}

void setup()
{
  // When lightning is detected the interrupt pin goes HIGH.
  pinMode(intPin, INPUT);
  pinMode(motor_int_1,OUTPUT);
  pinMode(motor_int_2,OUTPUT);

  // Leave the H-bridge in a defined (off) state at boot.
  digitalWrite(motor_int_1, LOW);
  digitalWrite(motor_int_2, LOW);

  Serial.begin(9600);
  // USB serial on the Pico only enumerates after boot, so give a monitor a
  // few seconds to connect. Bounded so a headless boot still proceeds.
  while (!Serial && millis() < 3000) { }

  // Raspberry Pi Pico (Arduino-Pico core): set the SPI0 pins before begin().
  // These are the core defaults for SPI0 but are stated here so the wiring
  // is documented in one place.
  SPI.setRX(16);   // MISO (GP16)
  SPI.setSCK(18);  // SCK  (GP18)
  SPI.setTX(19);   // MOSI (GP19)
  SPI.begin(); // For SPI

  // Bind the driver to the CS pin and SPI port. Without this call every
  // register write below goes nowhere and readInterruptReg() returns garbage.
  // Note: beginSPI() only configures the bus, it never talks to the chip, so
  // its return value cannot tell us whether the sensor is present. The
  // readback check further down does that.
  lightning.beginSPI(spiCS, 2000000);

  // Tune the antenna to 500 kHz and calibrate the internal oscillators. The
  // library recommends this before use. It must run BEFORE attachInterrupt()
  // below: during tuning the IRQ pin outputs the oscillator and would flood
  // the ISR.
  Serial.println("Tuning AS3935 antenna...");
  if (!lightning.tuneAntenna()) {
    Serial.println("Warning: oscillator calibration did not report success.");
  }

  lightning.maskDisturber(false);
  lightning.setIndoorOutdoor(INDOOR);
  lightning.setNoiseLevel(noiseFloor);
  lightning.watchdogThreshold(watchDogVal);
  lightning.spikeRejection(spike);
  lightning.lightningThreshold(lightningThresh);

  // Read the settings back. This is the real "is the sensor there" check:
  // with MISO floating or CS miswired these come back as 0x00/0xFF rather
  // than the values written above.
  byte rbNoise = lightning.readNoiseLevel();
  byte rbWatchdog = lightning.readWatchdogThreshold();
  byte rbSpike = lightning.readSpikeRejection();
  byte rbThresh = lightning.readLightningThreshold();
  Serial.print("AS3935 noise level: ");
  Serial.println(rbNoise);
  Serial.print("AS3935 watchdog threshold: ");
  Serial.println(rbWatchdog);
  Serial.print("AS3935 spike rejection: ");
  Serial.println(rbSpike);
  Serial.print("AS3935 lightning threshold: ");
  Serial.println(rbThresh);
  if (rbNoise != noiseFloor || rbWatchdog != watchDogVal ||
      rbSpike != spike || rbThresh != lightningThresh) {
    Serial.println("AS3935 readback mismatch. Check SPI wiring and CS pin.");
    haltWithBlink();
  }

  // Service the AS3935 on the interrupt edge rather than polling the level.
  attachInterrupt(digitalPinToInterrupt(intPin), lightningISR, RISING);

}

void loop()
{

  //check to see if the device has detected a lightning strike

  // The AS3935 holds INT high until the interrupt register is read, so an
  // event that was already asserted when attachInterrupt() ran (or that
  // arrived while the motor was running) never produces a new rising edge.
  // Treat a HIGH level as pending too, so nothing gets stuck.
  if (strikeDetected || digitalRead(intPin) == HIGH) {
    strikeDetected = false;

    // Per the AS3935 datasheet, wait ~2ms after the interrupt before reading
    // the interrupt register, then read it (which also clears the interrupt).
    delay(2);
    intVal = lightning.readInterruptReg();
    if (intVal == NOISE_INT) {
      noiseCount++;
      if (noiseCount % EVENT_LOG_EVERY == 1) {
        Serial.print("Noise (");
        Serial.print(noiseCount);
        Serial.println(" total).");
      }
    }
    else if (intVal == DISTURBER_INT) {
      disturberCount++;
      if (disturberCount % EVENT_LOG_EVERY == 1) {
        Serial.print("Disturber (");
        Serial.print(disturberCount);
        Serial.println(" total).");
      }
    }
    else if (intVal == LIGHTNING_INT) {
      Serial.println("Lightning Strike Detected!");
      byte distance = lightning.distanceToStorm();
      Serial.print("Approximately: ");
      Serial.print(distance);
      Serial.println("km away!");

      //Turn on the motor for 3 seconds to pop the popper, unless we popped
      //less than STRIKE_COOLDOWN_MS ago.
      if (!hasPopped || (millis() - lastPopMillis) >= STRIKE_COOLDOWN_MS) {
        popPopper();
        lastPopMillis = millis();
        hasPopped = true;
      }
      else {
        Serial.println("Within cooldown, not firing motor.");
      }

    }
  }

  //test mode to run the motor

  if (test_mode == 1) {

    Serial.println("Turning on motor to test popper function");
    delay(3000);
    popPopper();
    delay(3000);
  }

}
