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


//Specific SPI setup for Raspberry Pi Pico
bool setRX(pin_size_t GP16); 
bool setCS(pin_size_t GP17); 
bool setSCK(pin_size_t GP18);
bool setTX(pin_size_t GP19);


// Values for modifying the IC's AS3935 settings
byte noiseFloor = 7;
byte watchDogVal = 2;
byte spike = 7;
byte lightningThresh = 1;
byte intVal = 0;

//set test mode to 1 to make the motor turn, useful for debug
int test_mode = 1;

void setup()
{
  // When lightning is detected the interrupt pin goes HIGH.
  pinMode(intPin, INPUT);
  pinMode(motor_int_1,OUTPUT);
  pinMode(motor_int_2,OUTPUT);

  Serial.begin(9600);

  SPI.begin(); // For SPI

  lightning.maskDisturber(false);
  lightning.setIndoorOutdoor(INDOOR);
  lightning.setNoiseLevel(noiseFloor);
  lightning.watchdogThreshold(watchDogVal);
  lightning.spikeRejection(spike);
  lightning.lightningThreshold(lightningThresh);

}

void loop()
{

  //check to see if the device has detected a lightning strike

  if (digitalRead(intPin) == HIGH) {
    // Hardware has alerted us to an event, now we read the interrupt register
    // to see exactly what it is.
    intVal = lightning.readInterruptReg();
    if (intVal == NOISE_INT) {
      Serial.println("Noise.");
    }
    else if (intVal == DISTURBER_INT) {
      Serial.println("Disturber.");
    }
    else if (intVal == LIGHTNING_INT) {
      Serial.println("Lightning Strike Detected!");
      byte distance = lightning.distanceToStorm();
      Serial.print("Approximately: ");
      Serial.print(distance);
      Serial.println("km away!");
      
      //Turn on the motor for 3 seconds to pop the popper
      Serial.println("Motor ON");
      digitalWrite(motor_int_2, HIGH);
      delay(3000);
      digitalWrite(motor_int_2, LOW);
      Serial.println("Motor OFF");

    }
  }
  
  //test mode to run the motor

  if (test_mode == 1) {

    Serial.println("Turning on motor to test popper function");
    delay(3000);
    Serial.println("Motor ON");
    digitalWrite(motor_int_2, HIGH);
    delay(3000);
    digitalWrite(motor_int_2, LOW);
    Serial.println("Motor OFF");
  }
  
  // Only check every three seconds
  delay(3000);

}
