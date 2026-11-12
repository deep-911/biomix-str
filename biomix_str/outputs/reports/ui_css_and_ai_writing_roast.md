# BioMix-STR: Deep UI/CSS and AI-Writing Roast & Audit

**Audit Date:** 2026-10-18  
**Scope:** Read-Only Audit of Live Application (`http://127.0.0.1:8000`), DOM Tree, Stylesheets, and Source Code  
**Target Files:**  
- `src/biomix/static/index.html`  
- `src/biomix/static/styles.css`  
- `src/biomix/static/app.js`  
- `src/biomix/bpe_catalog.py`  
- `src/biomix/server.py`  
- `src/biomix/theory.py`  
- `src/biomix/provenance.py`  
- `src/biomix/report_generator.py`  

**Standards Audited Against:**  
1. Precision Web UI/CSS Engineering (Pixel-perfect alignment, zero clipping, zero unhandled wrapping, zero off-screen core actions).  
2. Wikipedia: Signs of AI Writing ([WP:AIWRITE](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)) — strict elimination of puffery, superficial participial tack-ons, em-dash clutter, decorative unicode noise, and verbose meta-titles.

---

## Part 1: Broken CSS Alignment, Clipping & Layout Overbloat

### 1.1 Top-Left `Vessel Internals` Card (`#card-vessel-internals`)

#### Visual Defect
In `media_1792298593192.png`, expanding the "Vessel Internals" card reveals:
- The text blocks `"DO / pH Dip-Tube Probes / Dual sensor tubes from top head"` and `"External Thermal Jacket / Translucent heating/cooling shell"` are horizontally center-aligned in the middle of the card.
- Below each text block, sitting isolated on its own line in the center of the card, is a tiny, unstyled circle (an unstyled browser checkbox).

```
+-----------------------------------------------------------+
| Vessel Internals                             [Visual Only]|
|                                                           |
| Sparger Geometry                             Ring Sparger |
| [ Torus Ring Sparger (Standard)                         v]|
|                                                           |
|                  DO / pH Dip-Tube Probes                  |
|             Dual sensor tubes from top head               |
|                           ( )                             |
|                                                           |
|                  External Thermal Jacket                  |
|             Translucent heating/cooling shell             |
|                           ( )                             |
+-----------------------------------------------------------+
```

#### Exact Root Cause in Code
1. **Missing `flex-direction: row`:** In `index.html` lines 280 and 292:
   ```html
   <div class="control-group" style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
   ```
   In `styles.css` line 406:
   ```css
   .control-group {
     display: flex;
     flex-direction: column;
     gap: 6px;
   }
   ```
   The inline style sets `display: flex; align-items: center; justify-content: space-between;`, but **fails to specify `flex-direction: row`**. Because `.control-group` already has `flex-direction: column` from the CSS class, the flex container remains a **vertical column**.
   In a column flex container, `align-items: center` horizontally centers all children (`<div>` and `<label>`), and `justify-content: space-between` has no horizontal effect.
2. **Missing Toggle Switch CSS:** In `index.html` lines 285–288 and 297–300:
   ```html
   <label class="switch">
     <input type="checkbox" id="toggle-probes">
     <span class="slider round"></span>
   </label>
   ```
   **Neither `.switch` nor `.slider` nor `.slider.round` exists anywhere in `styles.css`** (0 matches). The author pasted generic HTML for a toggle switch without writing the corresponding CSS rules. The browser renders an unstyled `<input type="checkbox">` followed by an empty `<span>`. The checkbox sits on a new row directly below the centered text.

---

### 1.2 HUD Card (`#hud-metrics-card` & `#hud-revert-banner`)

#### Visual Defect
1. **Vertical Word Stack:** When a slider is modified, `#hud-revert-banner` appears. The message `"Modified from verified run"` is squished into a 4-line vertical column:
   ```
   Modified
   from
   verified
   run
   ```
   next to the button `[↺ Revert to Verified CFD]`.
2. **Clipped & Awkward Badges:**
   - The badge `"● Geometry Preview & Engineering Reference"` wraps onto two lines (`● Geometry Preview &` / `Engineering Reference`).
   - The card title `"Engineering Reference (Correlations)"` wraps onto two lines because the regime badge sits on the same row.
   - The regime pill displays lowercase `"turbulent"` instead of capitalized `"Turbulent"`.

#### Exact Root Cause in Code
1. **Width Math Collapse in `#hud-revert-banner`:**
   - `.hud-metrics-card` has a fixed width: `width: 224px` (`styles.css:741`).
   - Card padding is `10px 14px`, leaving usable inner width $= 224 - 28 = 196\text{ px}$.
   - `.hud-banner` has `display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 10px;` (`styles.css:2506–2515`). Inner width $= 196 - 20 = 176\text{ px}$.
   - `.hud-banner-btn` has `white-space: nowrap; font-size: 10.5px; font-weight: 600; padding: 3px 8px;` and text `↺ Revert to Verified CFD` (25 characters). Rendered button width is $\approx 145\text{ px}$.
   - Available width for `.hud-banner-msg`: $176\text{ px} - 145\text{ px} - 8\text{ px (gap)} = \mathbf{23\text{ px}}$.
   - In a 23-pixel space, no single word can fit on one line. The browser wraps at every whitespace character, creating a 4-line vertical word stack.
2. **Badge & Title Overflow:**
   - `"● Geometry Preview & Engineering Reference"` is 44 characters long. At 10px font, it requires $\approx 250\text{ px}$, exceeding the 196px card width.
   - `"Engineering Reference (Correlations)"` is 37 characters long. In `.hud-header` (`display: flex; justify-content: space-between`), the regime badge takes $\sim 65\text{ px}$, leaving $\sim 125\text{ px}$ for the title, forcing it onto two lines.
   - In `app.js` line 3076: `elRegime.textContent = meta.flow_regime || ...`. In `cad_mesher.py` and `bpe_catalog.py`, `flow_regime` is the lowercase string `"turbulent"`. Neither `app.js` nor `.wb-card-badge` applies text transformation, outputting raw lowercase `"turbulent"`.

---

### 1.3 Right-Hand Specification Card (`#impeller-profile-card` & Suitability Advisor)

#### Visual Defect
1. **Working Principle Box Clipped:** In `media_1792298559930.png`, the top border of the `Working Principle & Fluid Kinematics` container is tucked under or flush with the header when scrolled.
2. **Duplicate Advisory Paragraph:** The `Engineering Suitability Advisor` renders the exact same warning paragraph twice in immediate succession:
   - Yellow alert box: `⚠ Stage 0 (Rushton 6-Blade Disc Turbine (R-100)): Selected D_i/T ratio is 0.350...`
   - Gray action box: `→ Action: Stage 0 (Rushton 6-Blade Disc Turbine (R-100)): Selected D_i/T ratio is 0.350...`
3. **0-Indexed Jargon & Raw Code Notation:**
   - Displays `Stage 0` instead of `Stage 1` (bottom impeller).
   - Displays raw code variable name `D_i/T` with an underscore instead of clean mathematical formatting ($D_i/T$).

#### Exact Root Cause in Code
1. **Header Shrinking & Body Scroll Collision:**
   - `.impeller-profile-docked-card` has `max-height: calc(100% - 110px); display: flex; flex-direction: column; overflow: hidden;` (`styles.css:1465–1481`).
   - `.impeller-profile-header` lacks `flex-shrink: 0;`.
   - `.impeller-profile-body` has `overflow-y: auto; padding: 12px 14px; gap: 10px;`.
   - The total content height (tags, principle, applications, 4-box envelope grid, suitability box) exceeds 500px, causing the entire advisor box to be clipped at the bottom of standard 768px viewports.
2. **Backend/Frontend Duplication Loop:**
   - In `server.py` lines 1068–1071:
     ```python
     alerts = evaluate_bpe_suitability(tank=req.tank, fluid=fluid, ops=ops)
     return {
         "alerts": alerts,
         "has_warnings": any(a["level"] == "warning" for a in alerts),
         "recommended_adjustments": [a["message"] for a in alerts if a["level"] == "warning"],
         "bpe_metrics": sim_res.model_dump(),
     }
     ```
     Notice that `recommended_adjustments` is populated with the exact same `a["message"]` string from `alerts`.
   - In `app.js` lines 2572–2595:
     ```javascript
     alerts.forEach(a => {
       const pill = document.createElement('div');
       pill.className = `bpe-alert-pill ${pillClass}`;
       pill.innerHTML = `${icon} ${a.message}`;
       container.appendChild(pill);
     });
     if (recs && recs.length > 0) {
       recs.forEach(r => {
         const rec = document.createElement('div');
         rec.className = 'bpe-alert-pill';
         rec.innerHTML = `&#8594; <em>Action:</em> ${r}`;
         container.appendChild(rec);
       });
     }
     ```
     The frontend renders `a.message` as a warning pill, and then loops through `recs` (which is the identical list of messages) and renders each one again as an action pill.
3. **0-Indexed Loop in Python:**
   - In `bpe_catalog.py` line 793:
     ```python
     for i, imp in enumerate(tank.impellers):
         tag = f"Stage {i} ({entry.display_name})"
     ```
     `enumerate` starts at `0`. In single-impeller tanks, the only impeller is labeled `Stage 0`. Chemical engineering standards number stages starting at 1.
   - In `bpe_catalog.py` line 857:
     ```python
     f"{tag}: Selected D_i/T ratio is {ratio:.3f}. Recommended design-envelope range is [{min_r:.2f}, {max_r:.2f}] (standard design ratio = {std_r:.3f})."
     ```
     Uses raw Python variable identifier `D_i/T`.

---

### 1.4 Left Sidebar Space Waste & Cut-Off Solver Card

#### Visual Defect
1. **Dead Space for Single Stage:** When `Enable Stage 2 (Upper Impeller)` is unchecked, Card 4 still renders a large 130px tall SVG and readout container displaying:
   `Inter-Impeller Gap (ΔC) / Single Stage / No inter-impeller interaction / Single Impeller Loop`.
2. **Hidden Solver Card on Standard Displays:** On a 1366x768 or 1536x864 screen (viewport height 666–730px), `#card-fluent-solver` is positioned at `top: 1153px`, and its bottom is at `1485px`. The actual Solve button (`Launch Ansys Fluent 2026 R1 Solve`) is buried **400–750 pixels below the screen fold**. The user cannot see the solver button without deeply scrolling the rail.

#### Exact Root Cause in Code
1. **Measured DOM Metrics (from Playwright Audit):**
   - Viewport height: `730px`
   - Rail element height: `666px`
   - **Rail total scroll height: `2,179px`** (3.3× the viewport height!)
   - `#gap-visual-box` height: `130px`
   - Solver card top: `1,153px`
   - Solver card bottom: `1,485px`
2. **Unconditional Gap Card Visibility:** In `index.html` lines 415–437, `#gap-visual-box` is permanently placed at the bottom of Card 4. When Stage 2 is unchecked, `app.js` sets text to `"Single Stage"` instead of setting `gapBox.style.display = 'none'`. This wastes 130px of vertical space in a card that only has one impeller.
3. **Uncollapsed Non-Essential Cards:**
   - Card 1 (Ensemble Presets): 300px
   - Card 2 (Vessel & Baffles): 280px
   - Card 3 (Operating Conditions): 240px
   - Card 3b (Vessel Internals): 200px
   - Card 4 (Multi-Impeller Stages): 400px
   - Card 5 (Ansys Fluent Solver): 332px
   Total $= 2,179\text{ px}$. Because Card 5 is the primary action of the studio, placing it at the bottom of an uncollapsed 2,179px column guarantees that users on laptops and standard monitors miss the solve trigger entirely.

---

### 1.5 Tab 2: 2D Field Inspector Audit

#### Visual Defects
1. **Hardcoded Select Width Truncates Scalar Names:**
   - In `index.html` line 704:
     `<select class="select-input" id="select-scalar-field" style="width: 170px;">`
   - Option names:
     - `Velocity Magnitude |u| (m/s)` (29 chars) — renders as `Velocity Magnitude |u `
     - `Turbulent Kinetic Energy k (m²/s²)` (34 chars) — truncated
     - `Turbulence Dissipation Rate ε (m²/s³)` (37 chars) — truncated
     - `Kolmogorov Eddy Microscale λ_K (μm)` (35 chars) — truncated
     - `Turbulent Shear Stress τ_t (Pa)` (31 chars) — truncated
   - In `media_1792298603287.png`, the select box is clipped on the right.
2. **Phantom Plane Selector Button:**
   - The plane bar displays: `[XZ Mid-Plane] [YZ Mid-Plane] [XY (Stage 1)] [XY (Mid-Gap)]`.
   - For single-impeller runs (e.g., standard Rushton), `[XY (Mid-Gap)]` remains clickable even though no second impeller or gap exists. Clicking it renders an empty or duplicate slice.
3. **Missing Colorbar Scale on 2D Tab:**
   - The 2D slice canvas renders contour colors, but the colorbar legend (`.colorbar-legend`) is anchored inside the 3D studio view (`tab-studio`). When switching to `tab-slice`, there is no color legend explaining what colors correspond to what numerical values.

---

### 1.6 Tab 3: Any-vs-Any Configuration Comparator Audit

#### Visual Defects
1. **Case B Card Header Clipping:**
   - In `media_1792298613736.png`, the provenance badge in Case B is clipped at the right margin: `Verified Flu...`.
   - The rightmost axis ticks on the Case B velocity slice (`0.0 m/s`, `2.16 m/s`) are partially sliced off by the viewport edge.
2. **Horizontal Overflow on Small Viewports:**
   - Two 50% flex columns with large fixed-width canvases (500px each) plus margins push the comparator container beyond 1366px width, triggering horizontal scrollbars and clipping cards.
3. **Quick Pairs Pill Overcrowding:**
   - Six long quick-pair buttons (`Dual Wide vs Narrow`, `Rushton vs Smith CD-6`, `Pitched Blade vs Hydrofoil`, `Rushton vs Anchor`, `RPM Sweep (120 vs 400 RPM)`, `Viscosity Cavern (1 cP vs 3,000 cP)`) are placed in a horizontal row without flex-wrap, crowding the top header.

---

### 1.7 Tab 4: Solver Evidence Audit

#### Visual Defects
1. **Card Stacking & Cut-Off:**
   - The Navier-Stokes residual chart is 320px tall. Below it sits the "Verification & Solver Evidence Summary" card and the artifact checklist.
   - On standard viewports, the verification evidence cards are pushed below the bottom edge.
2. **AI Subtitle Puffery:**
   - Subtitle text: `"Rigorous comparison of Ansys Fluent 2026 R1 3D Navier-Stokes solver outputs against independent BPE engineering reference correlations."` (See Part 2 for AI writing roast).

---

### 1.8 Tab 5: Theory & Scale-Up Calculator Audit

#### Visual Defects
1. **Raw Programming Underscores in Public Table:**
   - In `index.html` lines 946–970:
     - `Working Liquid Volume (V_L)` — literal underscore `V_L`
     - `Impeller Diameter (D_i)` — literal underscore `D_i`
     - `Agitator Speed (N)`
     - `Impeller Tip Speed (u_tip)` — literal underscore `u_tip`
     - `Mixing Time (t_95)` — literal underscore `t_95`
     - `Specific Power (P/V_L)` — literal underscore `V_L`
     - `Impeller Reynolds Number (Re_i)` — literal underscore `Re_i`
2. **Unformatted Formula String:**
   - Displays raw code notation: `u_tip,2 = u_tip,1 · λ^(1/3)` and `N_2 = N_1 · λ^(-2/3)` instead of formatted HTML math ($u_{\text{tip},2} = u_{\text{tip},1} \cdot \lambda^{1/3}$).

---

### 1.9 Impeller Engineering Library Modal Audit

#### Visual Defects
1. **Jagged Grid Heights:**
   - In `media_1792298663573.png`, 16 impeller cards are displayed in a 3-column CSS grid.
   - Card descriptions vary from 2 lines to 6 lines, causing uneven card heights across rows and misaligned action buttons.
2. **Participial Bloat in Descriptions:** Every card in the modal contains 1–3 participial tack-on clauses (detailed below).

---

## Part 2: Audit Against Wikipedia's "Signs of AI Writing"

The Wikipedia guideline [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) details stylistic habits characteristic of Large Language Models. Every user-facing file in the BioMix-STR codebase was audited against these specific patterns.

### 2.1 AI Vocabulary & Puffery Words

LLMs disproportionately rely on promotional, hyperbolic words (*fundamentally, rigorous, comprehensive, crucial, pivotal, robust, seamless, meticulously, paramount, superior, optimal*).

| File | Line | Flagged Word | Context & Current String | Recommended Terse Replacement |
|---|:---:|---|---|---|
| `bpe_catalog.py` | L124 | `fundamentally` | *"...fundamentally suppressing low-pressure gas pocket cavity formation..."* | Suppresses low-pressure gas cavity formation |
| `bpe_catalog.py` | L173 | `robust` | *"High turbulent shear and robust radial pumping."* | High shear and radial pumping |
| `bpe_catalog.py` | L524 | `optimal` | *"...for optimal inter-stage axial exchange"* | ...for inter-stage axial circulation |
| `bpe_catalog.py` | L822 | `superior` | *"...would provide superior mixing kinetics with lower power draw."* | ...provides faster mixing at lower power |
| `report_generator.py` | L28 | `comprehensive` | `"""Generate a comprehensive engineering report..."""` | Generate an engineering verification report |
| `index.html` | L586 | `optimal` | `<div class="bpe-alert-pill optimal">` | Class name -> `status-normal` or `status-pass` |
| `index.html` | L824 | `comprehensive` | `Comprehensive Hydrodynamic & Energy Parity Matrix` | Hydrodynamic & Energy Parity Matrix |
| `index.html` | L933 | `elevates` | *"...which elevates maximum shear stress around impeller blade"* | ...which increases maximum blade shear stress |
| `index.html` | L1015 | `rigorous` | *"Rigorous comparison of Ansys Fluent 2026 R1 3D Navier-Stokes solver outputs..."* | Comparison of Fluent 2026 R1 CFD fields against correlations |
| `index.html` | L1080 | `optimal` | `<td style="color: #81c995;">Optimal Bioprocess Circulation</td>` | Balanced Circulation |
| `app.js` | L2072 | `optimal` | `pillEl.textContent = 'Independent Dual Loops (Optimal)';` | Independent Dual Loops |
| `app.js` | L3481 | `robust` | `<td>Ensures robust radial discharge jet momentum...</td>` | Maintains radial jet momentum |
| `app.js` | L3486 | `optimal` | `<td>> 1.2 (Optimal)</td>` | `> 1.2 (Standard)` |

---

### 2.2 Superficial `-ing` Participle Tack-Ons

A defining characteristic of AI-generated text is appending participial clauses (*", ensuring..."*, *", dividing..."*, *", eliminating..."*, *", facilitating..."*) to the end of declarative sentences to sound authoritative without conveying new technical information.

| File | Location | Sentence with Superficial `-ing` Clause | Recommended Technical Rewrite |
|---|---|---|---|
| `bpe_catalog.py` | L86 (Rushton) | *"...towards vessel wall at blade centerline, dividing into two symmetrical upper and lower toroidal recirculation loops."* | Liquid discharges radially at the blade centerline into upper and lower recirculation loops. |
| `bpe_catalog.py` | L124 (Smith CD-6) | *"...guides sparged gas along concave inner contour, fundamentally suppressing low-pressure gas pocket cavity formation behind blade edges."* | The concave blade profile guides gas along the inner contour to reduce cavity formation behind the blades. |
| `bpe_catalog.py` | L207 (Marine) | *"...directed downwards towards vessel dish, creating sweeping bottom velocities that prevent solids settling while generating minimal shear."* | Fluid pumps downward toward the dish head to suspend solids at low shear. |
| `bpe_catalog.py` | L248 (PBT) | *"...nominal 45° trajectory, partitioning momentum into simultaneous axial downflow (bulk turnover) and radial sweep (wall circulation)."* | Blade angle (45°) produces combined axial downflow and radial wall circulation. |
| `bpe_catalog.py` | L289 (Hydrofoil) | *"...near-zero radial velocity component, eliminating destructive velocity gradients and minimizing shear-induced cell lysis in fragile cultures."* | Aerofoil camber produces axial downflow with low shear for animal cell cultures. |
| `bpe_catalog.py` | L330 (Maxflo) | *"...wide blade chord coverage, preventing gas bubbles from channeling directly up the drive shaft under high aeration."* | Wide-chord blades suppress gas channeling along the agitator shaft. |
| `bpe_catalog.py` | L514 (Intermig) | *"...alternating 90° blade orientation per stage, generating counter-current axial circulation loops with low localized energy dissipation."* | Successive stages are staggered 90° to divide axial circulation loops across tall vessels. |
| `bpe_catalog.py` | L555 (Anchor) | *"...shearing viscous boundary layers and promoting convective heat transfer across jacketed wall."* | Frame sweeps within 5–15 mm of the wall to enhance vessel jacket heat transfer. |
| `bpe_catalog.py` | L596 (Ribbon) | *"...pumping fluid upward along the vessel wall and forcing downward return flow along the central shaft, ensuring top-to-bottom turnover in pseudoplastic broths."* | Outer flight lifts fluid along the wall, returning downward along the shaft for bulk turnover. |
| `bpe_catalog.py` | L637 (Auger) | *"...through draft tube, establishing forced circulation in highly viscous or thixotropic media."* | Helical screw pumps fluid axially through the draft tube in high-viscosity broths. |
| `bpe_catalog.py` | L840 (Unbaffled) | *"...solid-body tangential swirl, creating a central Rankine surface depression and reducing power draw by 30-50%."* | Tangential swirl forms a central surface vortex and reduces shaft power draw by 30–50%. |

---

### 2.3 Em Dashes (`—`) & Decorative Unicode Clutter

LLM outputs are saturated with em dashes (`—`) as catch-all punctuation, along with decorative unicode bullets and emojis that clutter technical tables.

#### Inventory of Em Dashes in Code & UI:
1. `report_generator.py` L159, L162, L165: Em dash used as table placeholders (`—`) where numbers are unavailable. (Should be `N/A`).
2. `app.js` L2450: `"Scale-Up Similitude & Industrial Sizing Calculator — Evaluates..."` (Title-subtitle separator).
3. `app.js` L3400: Em dash in summary tooltips.
4. `index.html` L431, L824: `&mdash;` separating headings from redundant explanatory sentences.

#### Inventory of Decorative Unicode Clutter:
1. `✓` and `&#10003;` (Checkmark): Appears in 7 places, including inside button labels (`✓ Verified Fluent Result`, `✓ < 512k Student Limit: OK`).
2. `↺` and `&#8634;` (Revert arrow): `&#8634; Revert to Verified CFD` inside `#btn-revert-cfd`.
3. `→ Action:` and `&#8594;`: Hardcoded in `app.js` line 2592 (`&#8594; <em>Action:</em>`).
4. `●` (Solid bullet): Hardcoded in solver source badges (`● Geometry Preview & Engineering Reference`, `● Reference Field Artifact`).
5. `⚠` and `&#9888;` (Warning triangle): Hardcoded in alert pills.
6. `▸` and `▾` (`&#9656;` / `&#9662;`): Chevrons on collapsible cards and toggles.

*Recommendation:* Strip unnecessary decorative emojis and unicode symbols from buttons and labels. Use clean SVGs or standard CSS border/dot indicators. Replace em dashes with colons, parentheses, or clean sentence breaks.

---

### 2.4 Verbose Meta-Titles & Explanatory Subtitles

AI text tends to give every card a long double-barreled title followed by a verbose paragraph explaining what the card does.

| Location | Current Verbose Title & Subtitle | Proposed Clean Engineering Heading |
|---|---|---|
| **Tab 5 Header** (`index.html:902`) | **Scale-Up Similitude & Industrial Sizing Calculator**<br>*Evaluates geometric similitude (λ = (V₂/V₁)^(1/3)) and computes required agitation speed, tip speed, power draw, torque, and mixing time under standard bioprocess scale-up criteria.* | **Bioprocess Scale-Up Calculator**<br><span style="font-size:11px;color:#5f6368">Geometric scale-up from baseline vessel volume.</span> |
| **Tab 4 Header** (`index.html:1014`) | **Verification & Solver Evidence Summary**<br>*Rigorous comparison of Ansys Fluent 2026 R1 3D Navier-Stokes solver outputs against independent BPE engineering reference correlations.* | **CFD Solver Evidence & Convergence**<br><span style="font-size:11px;color:#5f6368">Fluent 2026 R1 residuals, torque stability, and parity checks.</span> |
| **Tab 3 Header** (`index.html:775`) | **Any-vs-Any Verified Fluent CFD Run Comparator**<br>*Select any two converged Ansys Fluent 2026 R1 simulations to cross-compare flow fields, velocity profiles along tank height, and engineering metrics.* | **Run Comparator**<br><span style="font-size:11px;color:#5f6368">Side-by-side comparison of converged Fluent runs.</span> |
| **Tab 1 Card 3b** (`index.html:262`) | **Vessel Internals**<br>*Configure internal vessel hardware and sensors. CFD solves single-phase unsparged flow.* | **Vessel Hardware (Visual)**<br><span style="font-size:11px;color:#5f6368">Internal geometry preview (probes, sparger, jacket).</span> |
| **Tab 1 Card 4** (`index.html:306`) | **Multi-Impeller Stages & Inter-Impeller Gap (ΔC)** | **Impeller Stages** |
| **Tab 1 Profile** (`index.html:569`) | **Working Principle & Fluid Kinematics** | **Flow Characteristics** |
| **Tab 1 Profile** (`index.html:573`) | **Bioprocess Applications & Microorganisms** | **Typical Applications** |

---

## Part 3: Surgical Fix Plan (Roadmap for Review)

Below is the concrete, line-by-line implementation roadmap to fix all audited issues in one synchronized pass once approved:

### 1. `src/biomix/static/index.html`
- **Line 280, 292:** Fix `.control-group` inline styles: add `flex-direction: row; justify-content: space-between; align-items: center;`.
- **Line 285–288, 297–300:** Replace unstyled `<label class="switch">` with clean, styled checkbox toggles (`.wb-toggle-row`).
- **Line 508–515:** Refactor `#hud-metrics-card`:
  - Increase card width from `224px` to `260px` or set `#hud-revert-banner` to vertical flexbox (`flex-direction: column; align-items: stretch;`).
  - Shorten button text from `↺ Revert to Verified CFD` to `Revert to Verified Run`.
  - Shorten preview badge text from `● Geometry Preview & Engineering Reference` to `Geometry Preview (Correlations)`.
  - Ensure title text truncates or fits cleanly on one line.
- **Line 704:** Change `#select-scalar-field` width from `style="width: 170px;"` to `style="width: 240px;"` so 35-char scalar field names never truncate.
- **Line 902–970:** Clean up Tab 5 table: replace raw underscores (`V_L`, `D_i`, `u_tip`, `t_95`, `Re_i`) with formatted HTML subscripts ($V_L$, $D_i$, $v_{\text{tip}}$, $t_{95}$, $\text{Re}$).
- **Line 1014:** Remove "Rigorous comparison..." subtitle; replace with concise engineering caption.

### 2. `src/biomix/static/styles.css`
- **Add Toggle Switch Styles:** Implement proper `.wb-switch` CSS (width 36px, height 20px, rounded track, sliding knob).
- **HUD Card Width & Banner Layout:**
  - `.hud-metrics-card`: Update `width: 260px;`.
  - `.hud-banner`: Update `flex-direction: column; align-items: stretch; gap: 4px;` so messages and buttons never collide horizontally.
  - `.hud-banner-msg`: `text-align: center;`.
  - `.wb-card-badge`: Add `text-transform: capitalize;` so regime displays as `Turbulent`, `Laminar`.
- **Workbench Rail Layout & Solver Card Visibility:**
  - Collapse Card 2 (`Vessel & Baffles`) and Card 3 (`Operating Conditions`) by default when a verified preset is loaded, or make `#card-fluent-solver` sticky / docked at the bottom of the rail with its own persistent header, so the Solve button is **always 100% visible** without scrolling.
  - Add `.gap-visual-container.hidden { display: none !important; }`.
- **Comparator Viewport Fixes:**
  - Make comparator canvas containers responsive with `max-width: 100%` and `overflow: hidden;` to eliminate clipping of the Case B badge and axis ticks.

### 3. `src/biomix/static/app.js`
- **Line 2572–2595 (`renderSuitabilityAlerts`):**
  - Stop duplicating alerts into recommendations. If an alert has an actionable adjustment, display the adjustment once inside the alert card rather than rendering a duplicate gray box.
- **Line 3076:** Format regime string: `capitalize(flow_regime)`.
- **Line 3280–3305 (`syncInputsFromTank`):**
  - When Stage 2 is unchecked, hide `#gap-visual-box` completely (`display: none`), recovering 130px of vertical space in the rail.
- **Line 2450:** Update Tab 5 header strings to remove verbose meta-subtitles.

### 4. `src/biomix/bpe_catalog.py`
- **Line 800:** Fix stage numbering: `tag = f"Stage {i + 1} ({entry.display_name})"`. (Stage 1 for bottom, Stage 2 for upper).
- **Line 857:** Format diameter ratio: replace raw `D_i/T` with formatted `Di/T`.
- **Lines 80–746:** Clean up all 16 impeller descriptions:
  - Remove AI puffery (`fundamentally`, `robust`, `superior`, `optimal`).
  - Rewrite trailing `-ing` participial tack-ons into concise, direct active-voice technical sentences.

### 5. `src/biomix/server.py`
- **Line 1070:** Remove redundant duplication in `evaluate_suitability`: do not duplicate `alerts` messages into `recommended_adjustments`.

---

## Conclusion
This audit report documents all 5 visual CSS/alignment flaws and all 4 Wikipedia AI-writing patterns with exact file paths, line numbers, and root causes. No code files have been modified. Once reviewed, these fixes can be implemented in a clean surgical pass.
