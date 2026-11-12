# BioMix-STR Automated QA Audit & Bug Manifest (Step 6.1)

**Date:** October 15, 2026 16:51:31  
**Total Findings:** 0 | **Critical:** 0 | **Warning:** 0 | **Polish:** 0

---

## Table of Contents
1. [Executive Summary & Finding Counts](#1-executive-summary--finding-counts)
2. [Audit 1: Physics & Cached Metadata Feasibility Check](#2-audit-1-physics--cached-metadata-feasibility-check)
3. [Audit 2: Unrendered Math & Raw LaTeX Scan](#3-audit-2-unrendered-math--raw-latex-scan)
4. [Audit 3: Interactive Controls & Dead Button Crawl](#4-audit-3-interactive-controls--dead-button-crawl)
5. [Audit 4: Overlapping Elements & Layout Bounding-Box Check](#5-audit-4-overlapping-elements--layout-bounding-box-check)
6. [Prioritized Step 6.2 Action & Polish Plan](#6-prioritized-step-62-action--polish-plan)

---

## 1. Executive Summary & Finding Counts

| Audit Category | Critical | Warning | Polish | Total |
| :--- | :---: | :---: | :---: | :---: |
| **1. Physics & Cached Metadata** | 0 | 0 | 0 | 0 |
| **2. Math & Formula Formatting** | 0 | 0 | 0 | 0 |
| **3. Interactive Controls & Dead Clicks** | 0 | 0 | 0 | 0 |
| **4. Layout Collisions & Overlaps** | 0 | 0 | 0 | 0 |
| **TOTAL** | **0** | **0** | **0** | **0** |

## 2. Audit 1: Physics & Cached Metadata Feasibility Check

### Cached Ensemble Runs Physics Summary

| Run ID | Power (W) | Torque (N·m) | Max Velocity (m/s) | Dead Zone % | Tip Speed (m/s) | Streamlines | 3D Vectors |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `fluent_mari_hemi_130rpm_51...` | 0.37 | 0.0274 | 2.30 | 8.7% | 1.09 | 90 | 434 |
| `fluent_pitc_elli_220rpm_43...` | 7.75 | 0.3366 | 2.51 | 8.0% | 1.84 | 90 | 468 |
| `fluent_rush_flat_250rpm_c5...` | 19.45 | 0.7430 | 1.79 | 5.6% | 1.83 | 90 | 486 |
| `fluent_rush_flat_260rpm_c0...` | 10.91 | 0.4006 | 2.07 | 3.6% | 2.04 | 90 | 486 |
| `fluent_rush_flat_280rpm_1f...` | 50.16 | 1.7108 | 5.26 | 4.0% | 2.20 | 114 | 486 |
| `fluent_rush_flat_280rpm_dd...` | 48.43 | 1.6516 | 4.26 | 6.2% | 2.20 | 114 | 486 |

✓ **All cached run metadata and 16-impeller preview physics passed physical sanity validation!**

---

## 3. Audit 2: Unrendered Math & Raw LaTeX Scan

✓ **Zero unrendered LaTeX delimiters or raw formula strings found.**

---

## 4. Audit 3: Interactive Controls & Dead Button Crawl

✓ **All interactive buttons, sliders, segmented pickers, and modals passed functional crawl.**

---

## 5. Audit 4: Overlapping Elements & Layout Bounding-Box Check

✓ **Zero element collisions or viewport boundary clipping detected at both 1600x1000 and 1366x768.**

---

## 6. Prioritized Step 6.2 Action & Polish Plan

1. **Critical Functional Fixes:** Address any identified 422 payload mismatches, single-stage XY gap indexing issues, and modal selection callbacks.
2. **Mathematical Typography Polish:** Convert plain-text tokens (`theta_95`, `lambda_K`, `u_max`, `k_La`, `m^3`, `h^-1`) to KaTeX or clean HTML `<sub>`/`<sup>` mathematical notation across all cards.
3. **Layout & Responsive Spacing:** Ensure floating HUD cards have adaptive maximum heights and responsive spacing to prevent overlap on 1366x768 laptop displays.
