import math

import pytest

from vexsim import units


def test_inch_meter_round_trip():
    assert units.in_to_m(1.0) == pytest.approx(0.0254)
    assert units.m_to_in(units.in_to_m(3.25)) == pytest.approx(3.25)


def test_rpm_conversion():
    assert units.rpm_to_rad_s(60.0) == pytest.approx(2 * math.pi)
    assert units.rad_s_to_rpm(units.rpm_to_rad_s(600.0)) == pytest.approx(600.0)


def test_mass_angle_voltage():
    assert units.lb_to_kg(1.0) == pytest.approx(0.45359237)
    assert units.kg_to_lb(units.lb_to_kg(15.0)) == pytest.approx(15.0)
    assert units.deg_to_rad(180.0) == pytest.approx(math.pi)
    assert units.rad_to_deg(math.pi / 2) == pytest.approx(90.0)
    assert units.mv_to_v(12000) == pytest.approx(12.0)
    assert units.v_to_mv(12.0) == pytest.approx(12000)
