"""V5 Smart Motor (11W) model.

Electrical model at the motor core (before the gear cartridge). Winding
inductance is neglected; its time constant is far below the 1 ms step.

    I = (V - ke * w_core) / R          clamped to +/- the effective current limit
    torque_core = kt * I - friction(w_core)
    torque_out  = G * torque_core,     w_core = G * w_out

G is the cartridge ratio: red 36, green 18, blue 6. kt and ke are fitted
separately, so kt also absorbs gearbox efficiency.

The constants are fitted to the motor's natural (uncapped) torque-speed line
at 12.8 V. The firmware then caps velocity commands at the rated speed
(100/200/600 rpm) and limits current to 2.5 A. Together these reproduce VEX's
published curve: rated speed is held up to about a third of stall torque,
2.1 N*m at the current limit (red cartridge), and roughly 12.7 W peak power.
Parameter sources and which values are estimates: docs/models.md.

All quantities are SI and refer to the output shaft unless named *_core.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from vexsim.physics.power import IdealSupply, Supply
from vexsim.physics.thermal import MotorThermal, ThermalSpec
from vexsim.units import rpm_to_rad_s
from vexsim.v5 import CARTRIDGE_FREE_RPM

CARTRIDGE_RATIO = {"red": 36, "green": 18, "blue": 6}
_REFERENCE_RATIO = CARTRIDGE_RATIO["red"]  # the spec's output-side numbers are for red


@dataclass(frozen=True)
class MotorSpec:
    """Characteristics of the V5 11W motor. Output-side values are for the red cartridge."""

    reference_voltage_v: float = 12.8  # V5 battery nominal; the curve fit assumes it
    natural_free_rpm: float = 121.0  # uncapped free speed at reference voltage (fit)
    natural_stall_torque_nm: float = 3.99  # uncapped stall torque (fit)
    natural_stall_current_a: float = 4.69  # uncapped stall current (fit)
    free_current_a: float = 0.15  # no-load current (assumption)
    coulomb_fraction: float = 0.3  # share of no-load friction that is Coulomb (assumption)
    current_limit_a: float = 2.5  # firmware default and maximum
    max_command_v: float = 12.0  # move_voltage range is +/-12000 mV
    rotor_inertia_kgm2: float = 2.0e-6  # motor core, before the cartridge (estimate)
    friction_smoothing_rad_s: float = 2.0  # motor core; width of the Coulomb tanh
    velocity_kp: float = 2.0  # internal velocity loop, in units of ke
    velocity_ki: float = 20.0  # 1/s, in units of ke
    velocity_filter_s: float = 0.002  # velocity estimate low-pass time constant
    integral_gate: float = 0.25  # integrate only below this accel, in rated speeds per second
    position_kp: float = 15.0  # 1/s: position error (rad) -> velocity target (rad/s)

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if name == "coulomb_fraction":
                continue
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"motor.{name} must be positive, got {value}")
        if not 0.0 <= self.coulomb_fraction <= 1.0:
            raise ValueError("motor.coulomb_fraction must be in [0, 1]")
        if self.free_current_a >= self.natural_stall_current_a:
            raise ValueError("motor.free_current_a must be below natural_stall_current_a")
        if self.current_limit_a > self.natural_stall_current_a:
            raise ValueError("motor.current_limit_a cannot exceed natural_stall_current_a")


@dataclass(frozen=True)
class CoreConstants:
    """Electrical and friction constants of the motor core, derived from a MotorSpec."""

    resistance_ohm: float
    kt: float  # N*m/A
    ke: float  # V/(rad/s)
    coulomb_nm: float
    viscous_nm_s: float
    smoothing_rad_s: float
    rotor_inertia_kgm2: float

    @classmethod
    def from_spec(cls, spec: MotorSpec) -> CoreConstants:
        # Natural line at the reference voltage, referred to the core:
        #   stall: kt*I_s - coulomb = T_s,  I_s = V/R
        #   free:  kt*I_f = coulomb + viscous*w_f,  I_f = (V - ke*w_f)/R
        stall_torque = spec.natural_stall_torque_nm / _REFERENCE_RATIO
        free_speed = rpm_to_rad_s(spec.natural_free_rpm) * _REFERENCE_RATIO
        stall_current = spec.natural_stall_current_a
        free_current = spec.free_current_a
        c = spec.coulomb_fraction

        kt = stall_torque / (stall_current - c * free_current)
        no_load_torque = kt * free_current
        resistance = spec.reference_voltage_v / stall_current
        return cls(
            resistance_ohm=resistance,
            kt=kt,
            ke=(spec.reference_voltage_v - resistance * free_current) / free_speed,
            coulomb_nm=c * no_load_torque,
            viscous_nm_s=(1.0 - c) * no_load_torque / free_speed,
            smoothing_rad_s=spec.friction_smoothing_rad_s,
            rotor_inertia_kgm2=spec.rotor_inertia_kgm2,
        )

    def friction(self, w_core: float) -> float:
        return (
            self.coulomb_nm * math.tanh(w_core / self.smoothing_rad_s) + self.viscous_nm_s * w_core
        )


class BrakeMode(Enum):
    COAST = "coast"  # windings open: spins down on friction alone
    BRAKE = "brake"  # windings shorted: back-EMF brakes the motor
    HOLD = "hold"  # closed-loop hold of the position where it stopped


class ControlMode(Enum):
    STOPPED = "stopped"
    VOLTAGE = "voltage"
    VELOCITY = "velocity"
    POSITION = "position"


class V5Motor:
    """One V5 11W motor: firmware control loops, current limiting, thermal derating.

    The owner integrates the shaft dynamics. Each tick it calls
    ``update(omega, dt)`` with the output shaft speed and applies the returned
    torque. ``reflected_inertia_kgm2`` gives the rotor inertia seen at the
    output, which must be added to the driven load.
    """

    def __init__(
        self,
        cartridge: str = "green",
        *,
        spec: MotorSpec | None = None,
        thermal: ThermalSpec | None = None,
        supply: Supply | None = None,
    ):
        if cartridge not in CARTRIDGE_RATIO:
            raise ValueError(
                f"cartridge must be one of {sorted(CARTRIDGE_RATIO)}, got {cartridge!r}"
            )
        self.spec = spec or MotorSpec()
        self.core = CoreConstants.from_spec(self.spec)
        self.cartridge = cartridge
        self.ratio = CARTRIDGE_RATIO[cartridge]
        self.rated_speed = rpm_to_rad_s(CARTRIDGE_FREE_RPM[cartridge])
        self.thermal = MotorThermal(thermal)
        self.supply: Supply = supply or IdealSupply(self.spec.reference_voltage_v)
        self.supply_current_cap = math.inf  # set by PowerSystem when the brain shares current

        self._brake_mode = BrakeMode.COAST  # PROS default
        self._current_limit = self.spec.current_limit_a
        self._mode = ControlMode.STOPPED
        self._voltage_cmd = 0.0
        self._velocity_cmd = 0.0
        self._position_cmd = 0.0
        self._max_speed = self.rated_speed
        self._hold_target = 0.0
        self._integral_v = 0.0
        self._velocity_est = 0.0
        self._accel_est = 0.0

        # State after the latest update()
        self.position = 0.0  # rad, integrated from the shaft speed (internal encoder)
        self.velocity = 0.0  # rad/s, true shaft speed
        self.current = 0.0  # A
        self.voltage = 0.0  # V applied to the windings
        self.torque = 0.0  # N*m at the output shaft
        self.power_in = 0.0  # W drawn from the supply (negative when regenerating)
        self.current_limited = False

    # --- configuration -----------------------------------------------------------

    @property
    def brake_mode(self) -> BrakeMode:
        return self._brake_mode

    @brake_mode.setter
    def brake_mode(self, mode: BrakeMode) -> None:
        if mode is BrakeMode.HOLD and self._brake_mode is not BrakeMode.HOLD:
            self._hold_target = self.position
            self._integral_v = 0.0
        self._brake_mode = BrakeMode(mode)

    @property
    def current_limit_a(self) -> float:
        return self._current_limit

    @current_limit_a.setter
    def current_limit_a(self, amps: float) -> None:
        self._current_limit = min(max(amps, 0.0), self.spec.current_limit_a)

    @property
    def effective_current_limit_a(self) -> float:
        """User limit, brain sharing, and thermal derating combined."""
        return min(self._current_limit, self.supply_current_cap) * self.thermal.derate_factor

    # --- commands (PROS move_* semantics; a zero command stops with the brake mode) ---

    def set_voltage(self, volts: float) -> None:
        if volts == 0:
            self.stop()
            return
        limit = self.spec.max_command_v
        self._enter(ControlMode.VOLTAGE)
        self._voltage_cmd = min(max(volts, -limit), limit)

    def set_velocity(self, rad_s: float) -> None:
        if rad_s == 0:
            self.stop()
            return
        self._enter(ControlMode.VELOCITY)
        self._velocity_cmd = min(max(rad_s, -self.rated_speed), self.rated_speed)

    def set_position(self, target_rad: float, max_speed: float | None = None) -> None:
        self._enter(ControlMode.POSITION)
        self._position_cmd = target_rad
        cap = self.rated_speed if max_speed is None else abs(max_speed)
        self._max_speed = min(cap, self.rated_speed)

    def stop(self) -> None:
        if self._mode is not ControlMode.STOPPED:
            self._hold_target = self.position
        self._enter(ControlMode.STOPPED)

    def _enter(self, mode: ControlMode) -> None:
        if mode is not self._mode:
            self._integral_v = 0.0
            self._mode = mode

    # --- readouts ------------------------------------------------------------------

    @property
    def mode(self) -> ControlMode:
        return self._mode

    @property
    def velocity_estimate(self) -> float:
        """Filtered shaft speed, as the motor's own controller (and get_actual_velocity) sees it."""
        return self._velocity_est

    @property
    def temperature_c(self) -> float:
        """Sensor temperature (housing/PCB node)."""
        return self.thermal.housing_c

    @property
    def over_temp(self) -> bool:
        return self.thermal.derate_level > 0

    @property
    def reflected_inertia_kgm2(self) -> float:
        return self.core.rotor_inertia_kgm2 * self.ratio**2

    @property
    def power_out(self) -> float:
        return self.torque * self.velocity

    # --- simulation ----------------------------------------------------------------

    def update(self, omega: float, dt: float) -> float:
        """Advance one step with the output shaft at ``omega`` rad/s. Returns output torque."""
        core = self.core
        self.velocity = omega
        self.position += omega * dt
        previous_est = self._velocity_est
        self._velocity_est += (omega - self._velocity_est) * (
            1.0 - math.exp(-dt / self.spec.velocity_filter_s)
        )
        self._accel_est = (self._velocity_est - previous_est) / dt

        w_core = omega * self.ratio
        v_bus = max(self.supply.bus_voltage, 0.0)
        limited = False
        if self._mode is ControlMode.STOPPED and self._brake_mode is BrakeMode.COAST:
            volts, current = 0.0, 0.0
        else:
            volts = min(max(self._drive_voltage(v_bus, dt), -v_bus), v_bus)
            current = (volts - core.ke * w_core) / core.resistance_ohm
            i_limit = self.effective_current_limit_a
            if abs(current) > i_limit:
                current = math.copysign(i_limit, current)
                volts = current * core.resistance_ohm + core.ke * w_core
                limited = True

        self.torque = self.ratio * (core.kt * current - core.friction(w_core))
        self.current, self.voltage, self.current_limited = current, volts, limited
        self.power_in = volts * current
        self.supply.add_load(self.power_in)
        self.thermal.step(current * current * core.resistance_ohm, dt)
        return self.torque

    def _drive_voltage(self, v_bus: float, dt: float) -> float:
        mode = self._mode
        if mode is ControlMode.VOLTAGE:
            return self._voltage_cmd
        if mode is ControlMode.VELOCITY:
            return self._velocity_loop(self._velocity_cmd, v_bus, dt)
        if mode is ControlMode.POSITION:
            return self._velocity_loop(
                self._position_loop(self._position_cmd, self._max_speed), v_bus, dt
            )
        if self._brake_mode is BrakeMode.HOLD:
            return self._velocity_loop(
                self._position_loop(self._hold_target, self.rated_speed), v_bus, dt
            )
        return 0.0  # BRAKE: windings shorted

    def _position_loop(self, target: float, max_speed: float) -> float:
        speed = self.spec.position_kp * (target - self.position)
        return min(max(speed, -max_speed), max_speed)

    def _velocity_loop(self, target: float, v_bus: float, dt: float) -> float:
        core, spec = self.core, self.spec
        ke_out = core.ke * self.ratio
        error = target - self._velocity_est
        w_target_core = target * self.ratio
        feedforward = (
            core.ke * w_target_core + core.resistance_ohm * core.friction(w_target_core) / core.kt
        )
        command = feedforward + spec.velocity_kp * ke_out * error + self._integral_v

        # The integral only has to reject load torque; feedforward covers the rest. So it
        # integrates near steady state (low acceleration) and never while the output is
        # pinned in the error's direction. Integrating during the approach to a new target
        # would wind up and overshoot, badly so with heavy loads.
        settling = abs(self._accel_est) > spec.integral_gate * self.rated_speed
        voltage_pinned = abs(command) >= v_bus and command * error > 0
        current_pinned = self.current_limited and self.current * error > 0
        if not (settling or voltage_pinned or current_pinned):
            self._integral_v += spec.velocity_ki * ke_out * error * dt
            self._integral_v = min(max(self._integral_v, -v_bus), v_bus)
        return command
