"""Lightning Popper, MicroPython port for the Raspberry Pi Pico.

Copy this file and as3935.py to the Pico. Wiring is unchanged from the
Arduino version in ../lightning_code.
"""

import sys
import time
import machine
from machine import Pin, SPI

import as3935
from as3935 import AS3935

# Pins
PIN_INT = 20      # interrupt pin from AS3935
PIN_CS = 17       # CS for AS3935
PIN_MISO = 16     # SPI0 RX
PIN_SCK = 18      # SPI0 SCK
PIN_MOSI = 19     # SPI0 TX
PIN_MOTOR_1 = 8   # motor direction 1 of motor driver
PIN_MOTOR_2 = 9   # motor direction 2 of motor driver

# AS3935 settings
NOISE_FLOOR = 7
WATCHDOG = 2
SPIKE = 7
LIGHTNING_THRESHOLD = 1

# Set to True to make the motor turn repeatedly, useful for debug.
# Ship with this False so the motor only fires on a real strike.
TEST_MODE = False

MOTOR_RUN_MS = 3000

# Minimum time between motor firings. A busy storm can raise several
# lightning interrupts a minute.
STRIKE_COOLDOWN_MS = 60000

# Noise and disturber events can fire continuously in an electrically noisy
# environment, so only log every Nth one.
EVENT_LOG_EVERY = 10

# If the sensor does not answer at start-up, blink the LED for this long and
# then try again. The sensor has its own regulator and can be slow to power up.
SETUP_RETRY_MS = 3000

# After an unexpected error, wait this long and then reboot the Pico.
ERROR_RESTART_MS = 5000

int_pin = Pin(PIN_INT, Pin.IN)
motor_1 = Pin(PIN_MOTOR_1, Pin.OUT, value=0)  # H-bridge off at boot
motor_2 = Pin(PIN_MOTOR_2, Pin.OUT, value=0)

sensor = None
last_pop_ticks = None  # ticks_ms() of the last firing while cooldown runs
noise_count = 0
disturber_count = 0


def pop_popper():
    """Drive the motor to fire the popper, then let it coast.

    This is a hard, open-loop drive with no stall protection, so make sure
    the gearmotor cannot stall against an end-stop for the full pulse."""
    print("Motor ON")
    motor_1(0)
    motor_2(1)
    try:
        time.sleep_ms(MOTOR_RUN_MS)
    finally:
        motor_2(0)  # also stops the motor if the program is interrupted
    print("Motor OFF")


def blink_fault(duration_ms):
    """Blink the on-board LED rapidly so a fault is visible without a serial
    connection. On a Pico W this needs the Pico W build of MicroPython."""
    led = Pin("LED", Pin.OUT)
    end = time.ticks_add(time.ticks_ms(), duration_ms)
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        led.toggle()
        time.sleep_ms(150)
    led(0)


def cooldown_active():
    """True while the motor must not fire again. The main loop calls this
    every pass, so the tick counter can never wrap during a cooldown."""
    global last_pop_ticks
    if (last_pop_ticks is not None and
            time.ticks_diff(time.ticks_ms(), last_pop_ticks) >= STRIKE_COOLDOWN_MS):
        last_pop_ticks = None
    return last_pop_ticks is not None


def setup():
    """Configure the sensor. Returns False if it does not answer on SPI."""
    global sensor
    # The AS3935 uses SPI mode 1 at up to 2 MHz.
    spi = SPI(0, baudrate=2000000, polarity=0, phase=1, bits=8,
              firstbit=SPI.MSB, sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI),
              miso=Pin(PIN_MISO))
    sensor = AS3935(spi, Pin(PIN_CS), int_pin)

    # A soft reset of the Pico does not power-cycle the sensor, so start
    # from known defaults every time.
    sensor.reset_settings()

    print("Tuning AS3935 antenna...")
    tuned = sensor.tune_antenna()
    if tuned is None:
        print("Warning: no signal on interrupt pin, antenna not tuned.")
    else:
        print("Tuning capacitor: {} pF, antenna at {:.1f} kHz".format(
            tuned[0], tuned[1] / 1000))
    if not sensor.calibrate_oscillators():
        print("Warning: oscillator calibration did not report success.")

    sensor.mask_disturber(False)
    # INDOOR is the higher gain setting, so the more sensitive one.
    sensor.set_indoor_outdoor(as3935.INDOOR)
    sensor.set_noise_level(NOISE_FLOOR)
    sensor.watchdog_threshold(WATCHDOG)
    sensor.spike_rejection(SPIKE)
    sensor.lightning_threshold(LIGHTNING_THRESHOLD)

    # Read the settings back. This is the real "is the sensor there" check:
    # with MISO floating or CS miswired these do not match what was written.
    readback = (sensor.read_noise_level(), sensor.read_watchdog_threshold(),
                sensor.read_spike_rejection(), sensor.read_lightning_threshold())
    print("AS3935 noise level:", readback[0])
    print("AS3935 watchdog threshold:", readback[1])
    print("AS3935 spike rejection:", readback[2])
    print("AS3935 lightning threshold:", readback[3])
    if readback != (NOISE_FLOOR, WATCHDOG, SPIKE, LIGHTNING_THRESHOLD):
        print("AS3935 readback mismatch. Check SPI wiring and CS pin.")
        return False
    return True


def handle_event():
    """Service a pending AS3935 interrupt."""
    global last_pop_ticks, noise_count, disturber_count
    event = sensor.read_interrupt()  # also clears the interrupt
    if event == as3935.INT_NOISE:
        noise_count += 1
        if noise_count % EVENT_LOG_EVERY == 1:
            print("Noise ({} total).".format(noise_count))
    elif event == as3935.INT_DISTURBER:
        disturber_count += 1
        if disturber_count % EVENT_LOG_EVERY == 1:
            print("Disturber ({} total).".format(disturber_count))
    elif event == as3935.INT_LIGHTNING:
        print("Lightning Strike Detected!")
        distance = sensor.distance_to_storm()
        if distance == as3935.DISTANCE_OUT_OF_RANGE:
            print("Distance: out of range")
        elif distance == as3935.DISTANCE_OVERHEAD:
            print("Storm is overhead!")
        else:
            print("Approximately: {}km away!".format(distance))

        if cooldown_active():
            print("Within cooldown, not firing motor.")
        else:
            pop_popper()
            last_pop_ticks = time.ticks_ms()


def run():
    while not setup():
        print("Retrying sensor setup.")
        blink_fault(SETUP_RETRY_MS)
    print("Ready, waiting for lightning.")

    while True:
        cooldown_active()

        # The AS3935 holds its interrupt pin high until the interrupt
        # register is read, so polling the level never misses an event,
        # including one that arrives while the motor is running.
        if int_pin():
            handle_event()

        if TEST_MODE:
            print("Turning on motor to test popper function")
            time.sleep_ms(3000)
            pop_popper()
            time.sleep_ms(3000)

        time.sleep_ms(10)


def main():
    """Run forever. This device is left unattended, so on an unexpected
    error make the motor safe and reboot rather than stop at the prompt.
    Ctrl-C still stops the program normally."""
    try:
        run()
    except Exception as exc:
        motor_1(0)
        motor_2(0)
        sys.print_exception(exc)
        print("Restarting.")
        blink_fault(ERROR_RESTART_MS)
        machine.reset()


if __name__ == "__main__":
    main()
