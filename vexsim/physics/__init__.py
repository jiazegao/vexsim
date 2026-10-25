"""Physics models and the simulation loop."""

from vexsim.physics.battery import Battery, BatterySpec
from vexsim.physics.motor import BrakeMode, ControlMode, MotorSpec, V5Motor
from vexsim.physics.params import PhysicsParams, resolve_params
from vexsim.physics.power import IdealSupply, PowerSystem
from vexsim.physics.thermal import ThermalSpec
from vexsim.physics.world import PRIORITY_CONTROL, PRIORITY_RECORD, PRIORITY_SENSOR, System, World

__all__ = [
    "PRIORITY_CONTROL",
    "PRIORITY_RECORD",
    "PRIORITY_SENSOR",
    "Battery",
    "BatterySpec",
    "BrakeMode",
    "ControlMode",
    "IdealSupply",
    "MotorSpec",
    "PhysicsParams",
    "PowerSystem",
    "System",
    "ThermalSpec",
    "V5Motor",
    "World",
    "resolve_params",
]
