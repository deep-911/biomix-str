"""Regression test for AUD-05: Allow baffle_width_ratio = 0.0 when baffle_count = 0."""

import pytest
from biomix.models import TankGeometry, ImpellerSpec, ImpellerType


def test_unbaffled_tank_accepts_zero_baffle_width_ratio():
    """Unbaffled tank (baffle_count=0) must allow baffle_width_ratio=0.0 without ValidationError."""
    tank = TankGeometry(
        diameter_m=0.45,
        liquid_height_m=0.50,
        baffle_count=0,
        baffle_width_ratio=0.0,
        impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.15)],
    )
    assert tank.baffle_count == 0
    assert tank.baffle_width_ratio == 0.0
    assert tank.baffle_width_m == 0.0
    assert tank.is_baffled is False


def test_baffled_tank_rejects_zero_baffle_width_ratio():
    """Baffled tank (baffle_count > 0) must reject baffle_width_ratio=0.0."""
    with pytest.raises(ValueError):
        TankGeometry(
            diameter_m=0.45,
            liquid_height_m=0.50,
            baffle_count=4,
            baffle_width_ratio=0.0,
            impellers=[ImpellerSpec(impeller_type=ImpellerType.RUSHTON_6_BLADE, diameter_m=0.15, clearance_m=0.15)],
        )
