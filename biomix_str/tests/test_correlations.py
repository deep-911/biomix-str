"""Unit tests for BioMix-STR core BPE hydrodynamic and mass transfer correlations."""

import math
import pytest

from biomix.correlations import (
    FlowRegime,
    METZNER_OTTO_KS,
    PUMPING_NUMBER_NQ,
    calc_aeration_number,
    calc_average_shear,
    calc_flooding_aeration_number,
    calc_froude_number,
    calc_gas_flow_rate_m3_s,
    calc_gassed_power,
    calc_kla_vant_riet,
    calc_kolmogorov_scales,
    calc_mixing_time_95,
    calc_power_number,
    calc_pumping_and_circulation,
    calc_reynolds_number,
    calc_superficial_gas_velocity,
    calc_tip_speed,
    calc_ungassed_power,
    classify_flow_regime,
)
from biomix.models import ImpellerType


class TestDoranWorkedExample:
    """Test 1: Verification against classic Doran Bioprocess Engineering Principles textbook."""

    def test_doran_rushton_turbulent_power(self):
        # Doran Chapter 8 Example:
        # T = 1.5 m, D_i = 0.5 m, Rushton turbine, 4 baffles
        # Liquid: Water (rho = 1000 kg/m^3, mu = 1e-3 Pa.s)
        # N = 180 rpm -> 3.0 rev/s
        rho = 1000.0
        mu = 0.001
        D = 0.5
        N = 180.0 / 60.0  # 3.0 rps

        re_i = calc_reynolds_number(density_kg_m3=rho, rps=N, diameter_m=D, viscosity_pa_s=mu)
        assert math.isclose(re_i, 750000.0, rel_tol=1e-9)

        regime = classify_flow_regime(re_i)
        assert regime == FlowRegime.TURBULENT

        np_val = calc_power_number(re_i=re_i, impeller_type=ImpellerType.RUSHTON_6_BLADE, is_baffled=True)
        assert math.isclose(np_val, 5.0, rel_tol=1e-9)

        p0 = calc_ungassed_power(np_val=np_val, density_kg_m3=rho, rps=N, diameter_m=D)
        # P0 = 5.0 * 1000 * 3^3 * 0.5^5 = 5000 * 27 * 0.03125 = 4218.75 W
        assert math.isclose(p0, 4218.75, rel_tol=1e-9)


class TestPowerNumberCurves:
    """Test 2: Laminar, transitional, and unbaffled Power Number interpolation."""

    def test_laminar_asymptote(self):
        # Re = 0.5: N_p = K_L / Re
        re_laminar = 0.5
        np_rushton = calc_power_number(re_laminar, ImpellerType.RUSHTON_6_BLADE)
        assert math.isclose(np_rushton, 70.0 / 0.5, rel_tol=1e-9)  # 140.0

        np_pbt = calc_power_number(re_laminar, ImpellerType.PITCHED_BLADE_45)
        assert math.isclose(np_pbt, 44.0 / 0.5, rel_tol=1e-9)  # 88.0

        np_prop = calc_power_number(re_laminar, ImpellerType.MARINE_PROPELLER)
        assert math.isclose(np_prop, 40.0 / 0.5, rel_tol=1e-9)  # 80.0

    def test_transitional_knot_exactness(self):
        # Anchor point (100.0, 3.6) for Rushton
        np_100 = calc_power_number(100.0, ImpellerType.RUSHTON_6_BLADE)
        assert math.isclose(np_100, 3.6, rel_tol=1e-6)

        # Anchor point (10.0, 7.2) for Rushton
        np_10 = calc_power_number(10.0, ImpellerType.RUSHTON_6_BLADE)
        assert math.isclose(np_10, 7.2, rel_tol=1e-6)

    def test_turbulent_plateau(self):
        np_rush = calc_power_number(50000.0, ImpellerType.RUSHTON_6_BLADE)
        assert math.isclose(np_rush, 5.0, rel_tol=1e-9)

        np_pbt = calc_power_number(50000.0, ImpellerType.PITCHED_BLADE_45)
        assert math.isclose(np_pbt, 1.5, rel_tol=1e-9)

        np_prop = calc_power_number(50000.0, ImpellerType.MARINE_PROPELLER)
        assert math.isclose(np_prop, 0.35, rel_tol=1e-9)

    def test_unbaffled_vortex_reduction(self):
        re_turb = 10000.0
        np_baffled = calc_power_number(re_turb, ImpellerType.RUSHTON_6_BLADE, is_baffled=True)
        np_unbaffled = calc_power_number(re_turb, ImpellerType.RUSHTON_6_BLADE, is_baffled=False)

        assert np_baffled == 5.0
        assert np_unbaffled < np_baffled
        expected_unbaffled = 5.0 * ((300.0 / re_turb) ** 0.18)
        assert math.isclose(np_unbaffled, expected_unbaffled, rel_tol=1e-9)


class TestGassedPowerAndFlooding:
    """Test 3: Aeration, gassed power reduction, and Nienow flooding limits."""

    def test_zero_aeration_returns_ungassed_power(self):
        p0 = 3000.0
        pg = calc_gassed_power(p0_w=p0, rps=4.0, diameter_m=0.35, q_g_m3_s=0.0, method="michel")
        assert pg == p0

        pg_bakker = calc_gassed_power(p0_w=p0, rps=4.0, diameter_m=0.35, q_g_m3_s=0.0, method="bakker")
        assert pg_bakker == p0

    def test_sparged_power_reduction(self):
        p0 = 3000.0
        rps = 4.0
        D = 0.35
        v_l = 1.0  # 1 m^3 working volume
        q_g = calc_gas_flow_rate_m3_s(aeration_vvm=0.5, working_volume_m3=v_l)

        pg_michel = calc_gassed_power(p0_w=p0, rps=rps, diameter_m=D, q_g_m3_s=q_g, method="michel")
        pg_bakker = calc_gassed_power(p0_w=p0, rps=rps, diameter_m=D, q_g_m3_s=q_g, method="bakker")

        assert 0.30 * p0 <= pg_michel < p0
        assert 0.35 * p0 <= pg_bakker < p0

    def test_flooding_thresholds(self):
        T = 1.0
        D = 0.35
        rps = 3.0
        fr = calc_froude_number(rps=rps, diameter_m=D)

        fl_flood_rushton = calc_flooding_aeration_number(ImpellerType.RUSHTON_6_BLADE, D, T, fr)
        fl_flood_pbt = calc_flooding_aeration_number(ImpellerType.PITCHED_BLADE_45, D, T, fr)
        fl_flood_prop = calc_flooding_aeration_number(ImpellerType.MARINE_PROPELLER, D, T, fr)

        # Axial impellers have factor 15 vs 30 for Rushton (exactly half)
        assert math.isclose(fl_flood_pbt, 0.5 * fl_flood_rushton, rel_tol=1e-9)
        assert math.isclose(fl_flood_prop, 0.5 * fl_flood_rushton, rel_tol=1e-9)

        # At high aeration, Fl_g exceeds Fl_g,flood
        high_qg = 0.05
        fl_g = calc_aeration_number(high_qg, rps, D)
        assert fl_g > fl_flood_rushton


class TestShearKolmogorovAndMassTransfer:
    """Test 4: Shear rates, Kolmogorov microscales, mixing time, and k_L a."""

    def test_tip_speed_and_shear(self):
        rps = 5.0
        D = 0.30
        v_tip = calc_tip_speed(rps, D)
        assert math.isclose(v_tip, math.pi * 5.0 * 0.30, rel_tol=1e-9)

        mu = 0.002
        gamma_dot, tau = calc_average_shear(rps, mu, ImpellerType.RUSHTON_6_BLADE)
        expected_gamma = METZNER_OTTO_KS[ImpellerType.RUSHTON_6_BLADE] * rps
        assert math.isclose(gamma_dot, expected_gamma, rel_tol=1e-9)
        assert math.isclose(tau, mu * expected_gamma, rel_tol=1e-9)

    def test_kolmogorov_microscale_ratio(self):
        p_w = 2500.0
        rho = 1000.0
        v_l = 1.2
        nu = 1e-6  # m^2/s for water

        scales = calc_kolmogorov_scales(p_w, rho, v_l, nu)
        eps_avg = scales["epsilon_avg_w_kg"]
        eps_max = scales["epsilon_max_w_kg"]
        lambda_avg = scales["lambda_k_avg_m"]
        lambda_min = scales["lambda_k_min_m"]

        assert math.isclose(eps_max, 10.0 * eps_avg, rel_tol=1e-9)
        # Since epsilon_max = 10 * epsilon_avg, lambda_avg / lambda_min = 10^0.25 ~ 1.7782794
        ratio = lambda_avg / lambda_min
        assert math.isclose(ratio, 10.0 ** 0.25, rel_tol=1e-9)
        assert lambda_min < lambda_avg

    def test_pumping_and_circulation(self):
        rps = 4.0
        D = 0.35
        v_l = 1.0
        qp, tc = calc_pumping_and_circulation(rps, D, v_l, ImpellerType.RUSHTON_6_BLADE)
        nq = PUMPING_NUMBER_NQ[ImpellerType.RUSHTON_6_BLADE]
        expected_qp = nq * rps * (D ** 3)
        assert math.isclose(qp, expected_qp, rel_tol=1e-9)
        assert math.isclose(tc, v_l / expected_qp, rel_tol=1e-9)

    def test_mixing_time_95(self):
        T = 1.0
        H = 1.2
        D = 0.35
        P = 1500.0
        rho = 1000.0
        v_l = 0.942
        re_turb = 200000.0
        re_trans = 500.0

        theta_turb = calc_mixing_time_95(T, H, D, P, rho, v_l, re_turb)
        theta_trans = calc_mixing_time_95(T, H, D, P, rho, v_l, re_trans)

        assert theta_turb > 0.0
        assert theta_trans > theta_turb  # viscous transitional penalty increases mixing time

    def test_kla_vant_riet_coalescing_vs_non_coalescing(self):
        pg = 2000.0
        v_l = 1.5
        area = 0.785
        q_g = calc_gas_flow_rate_m3_s(aeration_vvm=1.0, working_volume_m3=v_l)
        u_g = calc_superficial_gas_velocity(q_g, area)

        kla_coalescing = calc_kla_vant_riet(pg, v_l, u_g, coalescing_media=True)
        kla_non_coalescing = calc_kla_vant_riet(pg, v_l, u_g, coalescing_media=False)

        assert kla_coalescing > 0.0
        assert kla_non_coalescing > 0.0

        # Exact formula checks
        expected_coal = 0.026 * ((pg / v_l) ** 0.4) * (u_g ** 0.5)
        expected_non_coal = 0.002 * ((pg / v_l) ** 0.7) * (u_g ** 0.2)
        assert math.isclose(kla_coalescing, expected_coal, rel_tol=1e-9)
        assert math.isclose(kla_non_coalescing, expected_non_coal, rel_tol=1e-9)

        # Zero input boundaries
        assert calc_kla_vant_riet(0.0, v_l, u_g) == 0.0
        assert calc_kla_vant_riet(pg, v_l, 0.0) == 0.0
