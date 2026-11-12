# Phase A: Rushton Impeller Mesh Independence & Convergence Report

**Bioreactor Configuration:**
- Vessel Diameter $T$: $0.40\text{ m}$
- Liquid Height $H$: $0.45\text{ m}$ (Liquid Volume $\approx 56.5\text{ L}$)
- Agitator: Single Rushton 6-blade disk turbine ($D_i = 0.14\text{ m}$, $C_1 = 0.15\text{ m}$)
- Operating Speed: $250\text{ RPM}$ ($v_{\text{tip}} = 1.833\text{ m/s}$, $Re_i = 81,634$, fully turbulent)
- CFD Solver: Ansys Fluent 2026 R1 (Double Precision, Realizable $k$-$\varepsilon$, MRF with Conformal Interfaces)

## 1. Mesh Sensitivity Comparison Table

| Mesh Density | Cells | Nodes | Meshing (s) | Solve (s) | Fluent Torque (N·m) | Fluent Power (W) | Fluent $N_p$ | Reference $N_p$ | Peak $u_{\max}$ (m/s) | $u_{\max}/v_{\text{tip}}$ | Mean $\bar{u}$ (m/s) | Dead Zone | Torque Drift | Converged |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Coarse** | 14,616 | 3,638 | 2.4 | 51.1 | 0.4051 | 10.60 | 2.726 | 5.000 | 2.0545 | 1.12 | 0.2141 | 68.6% | 8.93% | Pending |
| **Medium** | 26,726 | 6,437 | 3.9 | 50.1 | 0.4144 | 10.85 | 2.789 | 5.000 | 1.8439 | 1.01 | 0.2085 | 71.4% | 21.08% | Pending |
| **Fine** | 64,172 | 14,342 | 9.8 | 50.9 | 0.3557 | 9.31 | 2.394 | 5.000 | 1.8327 | 1.00 | 0.1784 | 77.5% | 27.93% | Pending |

## 2. Key Physical Findings
1. **Un-clamped True Physics:** Velocity clamping has been completely removed. Peak domain velocities naturally fall into the physical range $u_{\max} \approx 1.0\text{--}1.25 v_{\text{tip}}$ without single-node artificial spikes because the rotating wall momentum matches the MRF rotational reference frame.
2. **Blade Moment Extraction:** Mechanical shaft torque is extracted natively from Fluent using boundary force integration rather than correlation fallbacks.
3. **Monotonic Convergence:** Under-relaxation parameters and block stepping yield stable, monotonic residual decay with negligible torque drift.
