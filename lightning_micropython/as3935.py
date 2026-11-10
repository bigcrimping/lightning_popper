"""Minimal MicroPython driver for the AS3935 Franklin lightning sensor (SPI).

Ported from the SparkFun driver wrapped by the Soldered Arduino library that
the original sketch in ../lightning_code uses. Only the features this project
needs are included.
"""

import time
import machine
from machine import Pin
from micropython import const

# Registers
_AFE_GAIN = const(0x00)
_THRESHOLD = const(0x01)
_LIGHTNING_REG = const(0x02)
_INT_MASK_ANT = const(0x03)
_ENERGY_LSB = const(0x04)
_ENERGY_MSB = const(0x05)
_ENERGY_MMSB = const(0x06)
_DISTANCE = const(0x07)
_FREQ_DISP_IRQ = const(0x08)
_CALIB_TRCO = const(0x3A)
_CALIB_SRCO = const(0x3B)
_PRESET_DEFAULT = const(0x3C)
_CALIB_RCO = const(0x3D)

_DIRECT_COMMAND = const(0x96)
_SPI_READ = const(0x40)

# Analog front end settings for set_indoor_outdoor(). INDOOR is the higher
# gain, so it is the more sensitive of the two.
INDOOR = const(0x12)
OUTDOOR = const(0x0E)

# Values returned by read_interrupt()
INT_NOISE = const(0x01)
INT_DISTURBER = const(0x04)
INT_LIGHTNING = const(0x08)

# Special values returned by distance_to_storm()
DISTANCE_OUT_OF_RANGE = const(0x3F)
DISTANCE_OVERHEAD = const(0x01)

_STRIKES = (1, 5, 9, 16)
_DIVISIONS = (16, 32, 64, 128)

# Antenna tuning. The antenna should resonate at 500 kHz and the chip can put
# that on the IRQ pin divided by 16/32/64/128. Dividing by 128 gives about
# 3.9 kHz, slow enough to count edges from a MicroPython interrupt handler.
_TUNE_DIV = const(128)
_TUNE_TARGET_HZ = 500000 / _TUNE_DIV
_TUNE_WINDOW_MS = const(100)

_edge_count = 0


def _count_edge(_pin):
    global _edge_count
    _edge_count += 1


class AS3935:
    def __init__(self, spi, cs, irq):
        """spi: machine.SPI set up for mode 1 (polarity=0, phase=1), MSB
        first, 2 MHz or slower. cs and irq: machine.Pin objects."""
        self._spi = spi
        self._cs = cs
        self._irq = irq
        self._cs.init(Pin.OUT, value=1)
        self._irq.init(Pin.IN)
        self._rbuf = bytearray(2)
        # The LCO needs 2 ms to start up and the RC oscillators 2 ms more.
        time.sleep_ms(4)

    # -- raw register access ------------------------------------------------

    def _read(self, reg):
        self._cs(0)
        self._spi.write_readinto(bytes((reg | _SPI_READ, 0)), self._rbuf)
        # Datasheet: CS must go high, low, high to end a read command.
        self._cs(1)
        self._cs(0)
        self._cs(1)
        return self._rbuf[1]

    def _write_raw(self, reg, value):
        self._cs(0)
        self._spi.write(bytes((reg, value & 0xFF)))
        self._cs(1)

    def _write(self, reg, keep_mask, bits, pos):
        """Read-modify-write: keep the bits in keep_mask, OR in bits << pos."""
        self._write_raw(reg, (self._read(reg) & keep_mask) | (bits << pos))

    # -- configuration ------------------------------------------------------

    def reset_settings(self):
        """Restore every register to its power-on default."""
        self._write_raw(_PRESET_DEFAULT, _DIRECT_COMMAND)
        time.sleep_ms(2)

    def set_indoor_outdoor(self, setting):
        if setting not in (INDOOR, OUTDOOR):
            raise ValueError("setting must be INDOOR or OUTDOOR")
        self._write(_AFE_GAIN, 0xC1, setting, 1)

    def mask_disturber(self, state):
        self._write(_INT_MASK_ANT, 0xDF, 1 if state else 0, 5)

    def set_noise_level(self, floor):
        """Noise floor threshold, 0 (lowest) to 7 (highest)."""
        if not 0 <= floor <= 7:
            raise ValueError("noise level must be 0-7")
        self._write(_THRESHOLD, 0x8F, floor, 4)

    def read_noise_level(self):
        return (self._read(_THRESHOLD) & 0x70) >> 4

    def watchdog_threshold(self, sensitivity):
        """Signal level needed to start validation, 0 (most sensitive) to 10."""
        if not 0 <= sensitivity <= 10:
            raise ValueError("watchdog threshold must be 0-10")
        self._write(_THRESHOLD, 0xF0, sensitivity, 0)

    def read_watchdog_threshold(self):
        return self._read(_THRESHOLD) & 0x0F

    def spike_rejection(self, sensitivity):
        """How hard short spikes are rejected, 0 (least) to 11 (most)."""
        if not 0 <= sensitivity <= 11:
            raise ValueError("spike rejection must be 0-11")
        self._write(_LIGHTNING_REG, 0xF0, sensitivity, 0)

    def read_spike_rejection(self):
        return self._read(_LIGHTNING_REG) & 0x0F

    def lightning_threshold(self, strikes):
        """Number of strikes (1, 5, 9 or 16) needed before an interrupt."""
        if strikes not in _STRIKES:
            raise ValueError("lightning threshold must be 1, 5, 9 or 16")
        self._write(_LIGHTNING_REG, 0xCF, _STRIKES.index(strikes), 4)

    def read_lightning_threshold(self):
        return _STRIKES[(self._read(_LIGHTNING_REG) & 0x30) >> 4]

    def _set_division(self, ratio):
        self._write(_INT_MASK_ANT, 0x3F, _DIVISIONS.index(ratio), 6)

    # -- events -------------------------------------------------------------

    def read_interrupt(self):
        """Read, and thereby clear, the interrupt source. Returns one of the
        INT_* values, or 0 if nothing is pending."""
        # Datasheet: wait 2 ms after IRQ goes high before reading.
        time.sleep_ms(2)
        return self._read(_INT_MASK_ANT) & 0x0F

    def distance_to_storm(self):
        """Estimated distance to the storm front in km. Also see
        DISTANCE_OUT_OF_RANGE and DISTANCE_OVERHEAD."""
        return self._read(_DISTANCE) & 0x3F

    def strike_energy(self):
        """Relative energy of the last lightning event. It has no physical
        unit, it is only useful for comparing events with each other."""
        return (((self._read(_ENERGY_MMSB) & 0x1F) << 16)
                | (self._read(_ENERGY_MSB) << 8)
                | self._read(_ENERGY_LSB))

    # -- calibration --------------------------------------------------------

    def read_tune_cap(self):
        """Internal antenna tuning capacitance in pF (0-120, steps of 8)."""
        return (self._read(_FREQ_DISP_IRQ) & 0x0F) * 8

    def _measure_irq_hz(self):
        global _edge_count
        state = machine.disable_irq()
        _edge_count = 0
        start = time.ticks_us()
        machine.enable_irq(state)
        time.sleep_ms(_TUNE_WINDOW_MS)
        state = machine.disable_irq()
        count = _edge_count
        elapsed = time.ticks_diff(time.ticks_us(), start)
        machine.enable_irq(state)
        return count * 1000000 / elapsed

    def tune_antenna(self):
        """Pick the internal tuning capacitor that puts the antenna closest
        to 500 kHz. Do not attach your own handler to the IRQ pin while this
        runs: the pin outputs the antenna frequency during tuning.

        Returns (capacitance_pF, antenna_frequency_Hz), or None if no signal
        was seen on the IRQ pin, which means it is not connected."""
        self._set_division(_TUNE_DIV)
        self._write(_FREQ_DISP_IRQ, 0x1F, 1, 7)  # antenna (LCO) out on IRQ
        self._irq.irq(_count_edge, Pin.IRQ_RISING, hard=True)
        best = None
        try:
            for step in range(16):
                self._write(_FREQ_DISP_IRQ, 0xF0, step, 0)
                time.sleep_ms(5)  # let the frequency settle
                hz = self._measure_irq_hz()
                if hz == 0:
                    best = None
                    break
                err = abs(hz - _TUNE_TARGET_HZ)
                if best is None or err < best[0]:
                    best = (err, step, hz)
        finally:
            self._irq.irq(handler=None)
            self._write(_FREQ_DISP_IRQ, 0x1F, 0, 7)  # IRQ pin back to normal
            self._set_division(16)                   # division back to default
        if best is None:
            return None
        self._write(_FREQ_DISP_IRQ, 0xF0, best[1], 0)
        return best[1] * 8, best[2] * _TUNE_DIV

    def calibrate_oscillators(self):
        """Calibrate the internal RC oscillators. Run after tune_antenna(),
        because they are calibrated against the antenna. True on success."""
        self._write_raw(_CALIB_RCO, _DIRECT_COMMAND)
        self._write(_FREQ_DISP_IRQ, 0x1F, 1, 6)
        time.sleep_ms(2)
        self._write(_FREQ_DISP_IRQ, 0x1F, 0, 6)
        # In each result register bit 7 means done and bit 6 means failed.
        trco = self._read(_CALIB_TRCO) & 0xC0
        srco = self._read(_CALIB_SRCO) & 0xC0
        return trco == 0x80 and srco == 0x80
