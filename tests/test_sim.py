"""Tests for the free-ride power simulation (:mod:`daum_bridge.sim`)."""

import pytest

from daum_bridge import sim


def test_zero_speed_is_zero_power():
    assert sim.simulated_power(0.0, 5.0) == 0.0


def test_flat_road_power_is_rolling_plus_drag():
    # 30 km/h on the flat with the default rider/bike/tyres: the classic
    # ~216 W, which is a sane number for a road bike at that speed.
    assert sim.simulated_power(30.0, 0.0) == pytest.approx(216.4, rel=1e-3)


def test_power_rises_with_speed():
    slow = sim.simulated_power(20.0, 0.0)
    fast = sim.simulated_power(40.0, 0.0)
    assert fast > slow


def test_power_rises_with_grade():
    flat = sim.simulated_power(20.0, 0.0)
    climb = sim.simulated_power(20.0, 6.0)
    assert climb > flat


def test_descent_reduces_power():
    flat = sim.simulated_power(20.0, 0.0)
    descent = sim.simulated_power(20.0, -6.0)
    assert descent < flat
    assert descent >= 0.0


def test_grade_is_clamped_to_the_configured_maximum():
    steep = sim.simulated_power(20.0, 40.0, max_grade_percent=16.0)
    at_limit = sim.simulated_power(20.0, 16.0)
    assert steep == pytest.approx(at_limit)


def test_heavier_rider_needs_more_power_on_a_climb():
    light = sim.simulated_power(15.0, 5.0, rider_mass_kg=60.0)
    heavy = sim.simulated_power(15.0, 5.0, rider_mass_kg=100.0)
    assert heavy > light


def test_clamp_power_uses_the_brake_range():
    assert sim.clamp_power(0.0) == 25
    assert sim.clamp_power(216.4) == 216
    assert sim.clamp_power(2000.0) == 800


def test_speed_for_gear_rises_with_gear_and_cadence():
    assert sim.speed_for_gear(90.0, 14) > sim.speed_for_gear(90.0, 1)
    assert sim.speed_for_gear(90.0, 7) > sim.speed_for_gear(60.0, 7)
    assert sim.speed_for_gear(90.0, 0) == sim.speed_for_gear(90.0, 1)
