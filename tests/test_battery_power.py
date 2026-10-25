import pytest

from vexsim.physics import Battery, BatterySpec, PowerSystem, V5Motor, World
from vexsim.physics.rig import ShaftRig
from vexsim.units import rad_s_to_rpm


def test_open_circuit_voltage_curve():
    assert Battery(soc=1.0).open_circuit_voltage() == pytest.approx(13.5)
    assert Battery(soc=0.5).open_circuit_voltage() == pytest.approx(13.1)
    assert Battery(soc=0.4).open_circuit_voltage() == pytest.approx(13.05)
    volts = [Battery(soc=s / 20).open_circuit_voltage() for s in range(21)]
    assert volts == sorted(volts)


def test_terminal_voltage_sags_with_current():
    battery = Battery()
    r = battery.spec.internal_resistance_ohm
    assert battery.terminal_voltage(20.0) == pytest.approx(13.5 - 20.0 * r)
    assert battery.terminal_voltage(1e6) == 0.0


def test_charge_counting():
    battery = Battery()
    battery.step(1.1, 1800.0)  # 1.1 A for half an hour = 550 mAh
    assert battery.soc == pytest.approx(0.5)
    assert battery.charge_used_mah == pytest.approx(550.0)
    battery.step(10.0, 3600.0)
    assert battery.soc == 0.0
    battery.step(-5.0, 100.0)  # the sim never charges the battery
    assert battery.soc == 0.0


def test_battery_validation():
    with pytest.raises(ValueError):
        Battery(soc=1.5)
    with pytest.raises(ValueError):
        BatterySpec(capacity_mah=0)
    with pytest.raises(ValueError):
        BatterySpec(ocv_soc=(0.0, 0.5), ocv_v=(12.0, 11.0, 13.0))
    with pytest.raises(ValueError):
        BatterySpec(ocv_soc=(0.0, 1.0), ocv_v=(13.0, 12.0))


def stalled_motors(n, power):
    motors = []
    for _ in range(n):
        motor = V5Motor("green")
        power.attach(motor)
        motor.set_velocity(motor.rated_speed)
        motors.append(motor)
    return motors


def run_stalled(motors, power, steps=50, dt=0.001):
    for _ in range(steps):
        for motor in motors:
            motor.update(0.0, dt)
        power.end_step(dt)


def test_bus_sags_under_load():
    power = PowerSystem()
    idle = power.bus_voltage
    motors = stalled_motors(8, power)
    run_stalled(motors, power)
    total_in = sum(m.power_in for m in motors)
    assert power.battery_current_a == pytest.approx(
        total_in / power.bus_voltage + power.quiescent_current_a, rel=0.02
    )
    assert power.bus_voltage < idle - 0.5


def test_brain_shares_current_beyond_eight_motors():
    power = PowerSystem()
    eight = stalled_motors(8, power)
    assert all(m.effective_current_limit_a == pytest.approx(2.5) for m in eight)
    stalled_motors(2, power)
    assert all(m.effective_current_limit_a == pytest.approx(2.0) for m in power.motors)


def test_regeneration_does_not_charge_battery():
    power = PowerSystem()
    power.add_load(-200.0)
    power.end_step(0.001)
    assert power.battery_current_a == pytest.approx(power.quiescent_current_a)


def free_spin_rpm(soc, command):
    power = PowerSystem(Battery(soc=soc))
    motor = V5Motor("blue")
    power.attach(motor)
    rig = ShaftRig(motor, load_inertia_kgm2=4 * motor.reflected_inertia_kgm2)
    if command == "velocity":
        motor.set_velocity(motor.rated_speed)
    else:
        motor.set_voltage(12.0)
    rig.run(1.0)
    return rad_s_to_rpm(rig.omega)


def test_velocity_mode_is_consistent_across_battery_charge():
    # VEX: speed is regulated so robots behave the same on a full or a low battery...
    assert free_spin_rpm(1.0, "velocity") == pytest.approx(600, rel=0.005)
    assert free_spin_rpm(0.01, "velocity") == pytest.approx(600, rel=0.005)
    # ...while a 12 V command loses speed once the battery can't supply 12 V (11.4 V here).
    assert free_spin_rpm(0.01, "voltage") < 0.98 * free_spin_rpm(1.0, "voltage")


def test_power_system_runs_inside_world():
    def run(seed):
        world = World(seed=seed)
        power = PowerSystem()
        motor = V5Motor("green")
        power.attach(motor)
        rig = world.add_system(ShaftRig(motor, load_inertia_kgm2=0.002))
        world.every(10, lambda w: motor.set_velocity(motor.rated_speed * min(1.0, w.time)))
        world.run_for(1.5)
        return rig.omega, power.battery.soc, motor.temperature_c

    omega, soc, temp = run(1)
    assert omega == pytest.approx(V5Motor("green").rated_speed, rel=0.01)
    assert soc < 1.0 and temp > 25.0
    assert run(1) == run(1)
