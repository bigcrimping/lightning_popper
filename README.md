# Lightning Popper


A Raspberry Pi pico project connecting to a SparkFun AS3935 Lightning Detector via SPI and a L298N motor driver to drive a micro metal 298:1 6V gearmotor

![complete](https://github.com/bigcrimping/lightning_popper/assets/74270551/87d22aa9-51c7-4eeb-b0e1-dea4f7492809)


The electronics fit in a 3D printed housing in the base of a Ikea BEGÅVNING glass dome with a upper section holding the motor drive and wheel


https://github.com/bigcrimping/lightning_popper/assets/74270551/b90ec8f4-45b4-442c-8fff-1e1bec368a54


## Project Code

The code is here: https://github.com/bigcrimping/lightning_popper/tree/main/lightning_code

You will need to add the "Soldered AS3935 Lightning sensor library" and the "Raspberry Pi Pico/RP2040" board package to compile

## Wiring

The base contains:
1) Raspberry Pi Pico
2) SparkFun AS3935 Lightning Detector
3) Generic LDO board (to feed AS3935 supply)
4) "L298N DC Motor Driver MX1508 Mini Dual Channel 1.5A"
5) "HW-432" Step up converter(6V)

Wiring is as below:

![electronics](https://github.com/bigcrimping/lightning_popper/assets/74270551/3d50762d-5487-49d7-a665-f8a9300f6293)


## Mechanical Files

Mechanical files here: https://github.com/bigcrimping/lightning_popper/tree/main/mech (3mf format)

The design comprises of:

"base" which will require brass inserts

![threaded](https://github.com/bigcrimping/lightning_popper/assets/74270551/9966c038-9ce9-4814-9642-3f7d19f9cc12)


"bell motor" printed with supports

![bell_motor](https://github.com/bigcrimping/lightning_popper/assets/74270551/a06eada8-f2d8-4675-942a-0c05afe74800)

"wheel" with M2.5 insert and M2.5x10mm cap head bolt

![wheel](https://github.com/bigcrimping/lightning_popper/assets/74270551/6e27ab3c-7540-4526-8318-cf2dc6437b58)



