"""Desktop test of the MicroPython port against a simulated AS3935.

Needs no hardware and no MicroPython: the machine, micropython and time
modules are replaced with fakes. Run with ordinary Python:

    python tests/test_micropython_port.py
"""
import contextlib
import io
import os
import sys
import types

sys.dont_write_bytecode = True
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "lightning_micropython")

# ---------------------------------------------------------------- fake clock
clock = {"ms": 0}
sleep_hooks = []


def sleep_ms(ms):
    for hook in list(sleep_hooks):
        hook(ms)
    clock["ms"] += ms


fake_time = types.ModuleType("time")
fake_time.sleep_ms = sleep_ms
fake_time.ticks_ms = lambda: clock["ms"]
fake_time.ticks_us = lambda: clock["ms"] * 1000
fake_time.ticks_diff = lambda a, b: a - b
fake_time.ticks_add = lambda a, b: a + b

# -------------------------------------------------------------- fake sensor
DEFAULTS = {0x00: 0x24, 0x01: 0x22, 0x02: 0xC2, 0x03: 0x00, 0x07: 0x3F,
            0x08: 0x00}


class FakeSensor:
    def __init__(self, dead=None):
        self.dead = dead        # None, or the byte every read returns
        self.dead_reads = None  # if set, reads are dead until this hits 0
        self.calib_result = 0x80  # done, not failed
        self.cs_low = False
        self.reset()
        # Antenna frequency for each capacitor step: best match is step 6.
        self.hz_per_step = [520000 - 3300 * s for s in range(16)]

    def reset(self):
        self.regs = [0] * 64
        for reg, value in DEFAULTS.items():
            self.regs[reg] = value

    def irq_hz(self):
        """Frequency on the IRQ pin while the antenna is displayed."""
        if not self.regs[0x08] & 0x80:
            return 0
        div = (16, 32, 64, 128)[self.regs[0x03] >> 6]
        return self.hz_per_step[self.regs[0x08] & 0x0F] / div

    def transfer(self, out):
        assert self.cs_low, "SPI transfer with CS high"
        cmd = out[0]
        if cmd & 0x40:  # read
            if self.dead is not None:
                return bytes((0, self.dead))
            return bytes((0, self.regs[cmd & 0x3F]))
        reg, value = cmd & 0x3F, out[1]
        if reg == 0x3C and value == 0x96:
            self.reset()
        elif reg == 0x3D and value == 0x96:
            self.regs[0x3A] = self.regs[0x3B] = self.calib_result
        else:
            self.regs[reg] = value
        return bytes(2)


hw = FakeSensor()
irq_level = [0]


class FakeSPI:
    MSB = 0

    def __init__(self, *args, **kw):
        assert kw.get("polarity") == 0 and kw.get("phase") == 1, kw
        assert kw.get("baudrate") <= 2000000

    def write_readinto(self, out, buf):
        buf[:] = hw.transfer(out)

    def write(self, out):
        hw.transfer(out)


class FakePin:
    IN, OUT, IRQ_RISING = 0, 1, 1
    all = []

    def __init__(self, ident, mode=None, value=None):
        self.ident = ident
        self.val = value or 0
        self.handler = None
        FakePin.all.append(self)

    def init(self, mode=None, value=None):
        if value is not None:
            self(value)

    def __call__(self, v=None):
        if v is None:
            return irq_level[0] if self.ident == 20 else self.val
        self.val = v
        if self.ident == 17:
            hw.cs_low = (v == 0)

    def toggle(self):
        self.val ^= 1

    def irq(self, handler=None, trigger=None, hard=False):
        self.handler = handler


def edge_hook(ms):
    """Deliver antenna edges to whichever IRQ pin object has a handler."""
    for pin in FakePin.all:
        if pin.ident == 20 and pin.handler is not None:
            for _ in range(int(hw.irq_hz() * ms / 1000)):
                pin.handler(pin)


sleep_hooks.append(edge_hook)


class Rebooted(Exception):
    pass


def fake_reset():
    raise Rebooted()


fake_machine = types.ModuleType("machine")
fake_machine.Pin = FakePin
fake_machine.SPI = FakeSPI
fake_machine.disable_irq = lambda: 0
fake_machine.enable_irq = lambda state: None
fake_machine.reset = fake_reset

fake_mp = types.ModuleType("micropython")
fake_mp.const = lambda x: x

sys.modules["time"] = fake_time
sys.modules["machine"] = fake_machine
sys.modules["micropython"] = fake_mp
sys.print_exception = lambda exc: print("exception:", repr(exc))
sys.path.insert(0, SRC)

import as3935  # noqa: E402
import main  # noqa: E402

# ------------------------------------------------------------------- checks
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def quiet(func, *args):
    """Call func with stdout captured. Returns (result, output)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = func(*args)
    return result, buf.getvalue()


def fresh_driver():
    global hw
    hw = FakeSensor()
    return as3935.AS3935(FakeSPI(polarity=0, phase=1, baudrate=2000000),
                         FakePin(17), FakePin(20))


# Setter register values, starting from the datasheet defaults.
d = fresh_driver()
d.set_indoor_outdoor(as3935.INDOOR)
check("indoor -> reg0 0x24", hw.regs[0] == 0x24)
d.set_indoor_outdoor(as3935.OUTDOOR)
check("outdoor -> reg0 0x1C", hw.regs[0] == 0x1C)
d.set_noise_level(7)
check("noise 7 -> reg1 0x72", hw.regs[1] == 0x72)
d.watchdog_threshold(10)
check("watchdog 10 keeps noise bits -> reg1 0x7A", hw.regs[1] == 0x7A)
d.spike_rejection(7)
check("spike 7 -> reg2 0xC7", hw.regs[2] == 0xC7)
d.lightning_threshold(16)
check("threshold 16 -> reg2 0xF7", hw.regs[2] == 0xF7)
d.lightning_threshold(1)
check("threshold 1 -> reg2 0xC7", hw.regs[2] == 0xC7)
hw.regs[3] = 0x01
d.mask_disturber(True)
check("mask disturber -> reg3 0x21", hw.regs[3] == 0x21)
d.mask_disturber(False)
check("unmask disturber -> reg3 0x01", hw.regs[3] == 0x01)

# Readbacks round-trip over the whole valid range, including zero.
ok = True
for n in range(0, 8):
    d.set_noise_level(n)
    ok &= d.read_noise_level() == n
for n in range(0, 11):
    d.watchdog_threshold(n)
    ok &= d.read_watchdog_threshold() == n
for n in range(0, 12):
    d.spike_rejection(n)
    ok &= d.read_spike_rejection() == n
for n in (1, 5, 9, 16):
    d.lightning_threshold(n)
    ok &= d.read_lightning_threshold() == n
check("all readbacks round-trip, zero included", ok)

for name, call in (("noise 8", lambda: d.set_noise_level(8)),
                   ("watchdog 11", lambda: d.watchdog_threshold(11)),
                   ("spike 12", lambda: d.spike_rejection(12)),
                   ("threshold 2", lambda: d.lightning_threshold(2)),
                   ("afe 0", lambda: d.set_indoor_outdoor(0))):
    try:
        call()
        check("invalid %s raises" % name, False)
    except ValueError:
        check("invalid %s raises" % name, True)

# Events.
hw.regs[3] = 0x08
check("read_interrupt returns lightning", d.read_interrupt() == 0x08)
hw.regs[7] = 0x0C
check("distance 12 km", d.distance_to_storm() == 12)
hw.regs[4], hw.regs[5], hw.regs[6] = 0x34, 0x12, 0xE5
check("strike energy uses 21 bits", d.strike_energy() == 0x051234)

# Antenna tuning.
d = fresh_driver()
result = d.tune_antenna()
check("tuning picks step 6 (48 pF)", result is not None and result[0] == 48)
check("tuned frequency near 500 kHz",
      result is not None and abs(result[1] - 500200) < 2000)
check("cap register left at step 6", hw.regs[8] & 0x0F == 6)
check("antenna display off after tuning", hw.regs[8] & 0x80 == 0)
check("division back to 16", hw.regs[3] & 0xC0 == 0)
check("IRQ handlers removed",
      all(p.handler is None for p in FakePin.all))

d = fresh_driver()
hw.hz_per_step = [0] * 16
check("tuning with dead IRQ returns None", d.tune_antenna() is None)
check("antenna display off after failed tuning", hw.regs[8] & 0x80 == 0)

# Oscillator calibration: needs done set and failed clear.
for result_byte, expect in ((0x80, True), (0xC0, False), (0x40, False),
                            (0x00, False)):
    d = fresh_driver()
    hw.calib_result = result_byte
    check("calibration result 0x%02X -> %s" % (result_byte, expect),
          d.calibrate_oscillators() == expect)

# Full setup.
hw = FakeSensor()
ok, out = quiet(main.setup)
check("setup succeeds with healthy sensor", ok is True)
check("setup tunes antenna to 48 pF", "Tuning capacitor: 48 pF" in out)
check("setup has no warnings", "Warning" not in out)
check("setup leaves indoor gain", hw.regs[0] == 0x24)
check("setup leaves reg1 0x72", hw.regs[1] == 0x72)
check("setup leaves reg2 0xC7", hw.regs[2] == 0xC7)
check("setup leaves disturbers unmasked", hw.regs[3] & 0x20 == 0)

for dead in (0x00, 0xFF):
    hw = FakeSensor(dead=dead)
    ok, out = quiet(main.setup)
    check("setup fails when every read is 0x%02X" % dead, ok is False)

# run() retries setup until the sensor answers, then enters the loop.
class StopLoop(Exception):
    pass


hw = FakeSensor(dead=0xFF)
state = {"sleeps": 0}


def revive_then_stop(ms):
    state["sleeps"] += 1
    if clock["ms"] - state["t0"] > 7000:
        hw.dead = None  # sensor finally powers up
    if clock["ms"] - state["t0"] > 20000:
        raise StopLoop()


state["t0"] = clock["ms"]
sleep_hooks.append(revive_then_stop)
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        main.run()
except StopLoop:
    pass
sleep_hooks.remove(revive_then_stop)
out = buf.getvalue()
check("run retries failed setup", out.count("Retrying sensor setup.") >= 2)
check("run reaches ready after sensor recovers",
      "Ready, waiting for lightning." in out)

# Strike handling and cooldown.
hw = FakeSensor()
quiet(main.setup)
pops = []
real_pop = main.pop_popper
main.pop_popper = lambda: pops.append(clock["ms"])
main.last_pop_ticks = None
main.noise_count = main.disturber_count = 0


def strike(distance=10):
    hw.regs[3] = (hw.regs[3] & 0xF0) | 0x08
    hw.regs[7] = distance
    return quiet(main.handle_event)[1]


out = strike()
check("first strike fires motor", len(pops) == 1)
check("distance is printed in km", "Approximately: 10km away!" in out)
clock["ms"] += 30000
out = strike()
check("strike 30 s later does not fire", len(pops) == 1)
check("cooldown is reported", "Within cooldown" in out)
clock["ms"] += 31000
out = strike(1)
check("strike 61 s after the first fires", len(pops) == 2)
check("overhead is decoded", "Storm is overhead!" in out)
out = strike(0x3F)
check("immediate strike does not fire", len(pops) == 2)
check("out of range is decoded", "out of range" in out)

# Cooldown survives the tick counter: the loop clears it once it expires.
clock["ms"] += 61000
check("cooldown clears after 60 s", main.cooldown_active() is False)
check("cooldown state is cleared", main.last_pop_ticks is None)

hw.regs[3] = 0x01
quiet(main.handle_event)
hw.regs[3] = 0x04
quiet(main.handle_event)
check("noise and disturber do not fire", len(pops) == 2)
check("noise counted", main.noise_count == 1)
check("disturber counted", main.disturber_count == 1)

# The real pop_popper drives the pins and always releases the motor.
main.pop_popper = real_pop
on_ms = []
hook = lambda ms: on_ms.append(ms) if main.motor_2() else None  # noqa: E731
sleep_hooks.append(hook)
quiet(main.pop_popper)
sleep_hooks.remove(hook)
check("motor released after pulse", main.motor_2() == 0)
check("motor pulse lasts 3 s", sum(on_ms) == 3000)


def interrupt_during_pulse(ms):
    if main.motor_2() == 1:
        raise KeyboardInterrupt


sleep_hooks.append(interrupt_during_pulse)
try:
    quiet(main.pop_popper)
except KeyboardInterrupt:
    pass
sleep_hooks.remove(interrupt_during_pulse)
check("motor released when interrupted", main.motor_2() == 0)

# main() makes the motor safe and reboots on an unexpected error.
def failing_run():
    main.motor_2(1)
    raise OSError("simulated SPI failure")


real_run = main.run
main.run = failing_run
rebooted = False
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        main.main()
except Rebooted:
    rebooted = True
check("unexpected error reboots the Pico", rebooted)
check("motor off before reboot", main.motor_2() == 0)
check("error is printed", "simulated SPI failure" in buf.getvalue())


def ctrl_c():
    raise KeyboardInterrupt


main.run = ctrl_c
try:
    main.main()
    check("Ctrl-C is not swallowed", False)
except KeyboardInterrupt:
    check("Ctrl-C is not swallowed", True)
except Rebooted:
    check("Ctrl-C is not swallowed", False)
main.run = real_run

print()
print("FAILED: %d" % len(failures) if failures else "ALL PASSED")
sys.exit(1 if failures else 0)
