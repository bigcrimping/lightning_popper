"""Event monitor for the Lightning Popper sensor.

Prints every sensor event with a timestamp and never runs the motor. Use it
to look for false strikes, for example with a piezo igniter near the antenna.

as3935.py and main.py must already be on the Pico. Run this file from the PC
without copying it, and stop it with Ctrl-C:

    mpremote run lightning_micropython/monitor.py

Afterwards reset the Pico to return to normal operation:

    mpremote reset
"""

import time

import as3935
import main  # for the sensor setup; importing it does not start the popper

# Sensor settings used while monitoring. The defaults are deliberately more
# sensitive than the shipped ones in main.py, to check that test sparks reach
# the sensor at all. Set USE_SHIPPED_SETTINGS to True to see what the popper
# itself would react to.
USE_SHIPPED_SETTINGS = False

AFE_GAIN = as3935.INDOOR   # INDOOR is the more sensitive setting
NOISE_FLOOR = 2            # 0-7, chip default 2
WATCHDOG = 1               # 0-10, lower is more sensitive, chip default 2
SPIKE = 1                  # 0-11, lower rejects fewer spikes, chip default 2

# Seconds to run for, or 0 to run until Ctrl-C.
DURATION_S = 0

_NAMES = {as3935.INT_NOISE: "NOISE", as3935.INT_DISTURBER: "DISTURBER",
          as3935.INT_LIGHTNING: "LIGHTNING"}


def _describe_distance(distance):
    if distance == as3935.DISTANCE_OUT_OF_RANGE:
        return "out of range"
    if distance == as3935.DISTANCE_OVERHEAD:
        return "overhead"
    return "{} km".format(distance)


def monitor():
    if not main.setup():
        print("Sensor not answering, cannot monitor.")
        return
    sensor = main.sensor
    if not USE_SHIPPED_SETTINGS:
        sensor.set_indoor_outdoor(AFE_GAIN)
        sensor.set_noise_level(NOISE_FLOOR)
        sensor.watchdog_threshold(WATCHDOG)
        sensor.spike_rejection(SPIKE)
    print("Monitoring with noise floor {}, watchdog {}, spike rejection {}. "
          "Motor disabled.".format(sensor.read_noise_level(),
                                   sensor.read_watchdog_threshold(),
                                   sensor.read_spike_rejection()))

    counts = {}
    start = time.ticks_ms()
    elapsed_ms = 0
    last = start
    try:
        while not DURATION_S or elapsed_ms < DURATION_S * 1000:
            # Accumulate elapsed time in small steps so long runs survive
            # the tick counter wrapping.
            now = time.ticks_ms()
            elapsed_ms += time.ticks_diff(now, last)
            last = now
            if main.int_pin():
                event = sensor.read_interrupt()
                name = _NAMES.get(event, "UNKNOWN 0x{:02X}".format(event))
                counts[name] = counts.get(name, 0) + 1
                line = "{:9.2f}s {}".format(elapsed_ms / 1000, name)
                if event == as3935.INT_LIGHTNING:
                    line += " distance={} energy={}".format(
                        _describe_distance(sensor.distance_to_storm()),
                        sensor.strike_energy())
                print(line)
            time.sleep_ms(5)
    except KeyboardInterrupt:
        pass
    print("Totals after {:.0f}s: {}".format(elapsed_ms / 1000,
                                           counts or "no events"))


monitor()
