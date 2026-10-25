"""Conversions between VEX-facing units and SI.

The simulator computes in SI (m, kg, s, rad, N, V, A). Configs, the robot-code
API and logs use VEX conventions (inches, degrees, rpm, millivolts). Convert at
those boundaries only.
"""

import math

M_PER_IN = 0.0254
KG_PER_LB = 0.45359237
RAD_S_PER_RPM = 2.0 * math.pi / 60.0


def in_to_m(inches: float) -> float:
    return inches * M_PER_IN


def m_to_in(meters: float) -> float:
    return meters / M_PER_IN


def lb_to_kg(pounds: float) -> float:
    return pounds * KG_PER_LB


def kg_to_lb(kilograms: float) -> float:
    return kilograms / KG_PER_LB


def deg_to_rad(degrees: float) -> float:
    return math.radians(degrees)


def rad_to_deg(radians: float) -> float:
    return math.degrees(radians)


def rpm_to_rad_s(rpm: float) -> float:
    return rpm * RAD_S_PER_RPM


def rad_s_to_rpm(rad_s: float) -> float:
    return rad_s / RAD_S_PER_RPM


def mv_to_v(millivolts: float) -> float:
    return millivolts / 1000.0


def v_to_mv(volts: float) -> float:
    return volts * 1000.0
