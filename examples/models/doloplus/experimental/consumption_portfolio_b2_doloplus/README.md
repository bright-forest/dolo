## consumption_portfolio_b2_doloplus (two-stage sketch; B2)

This folder sketches a **two-stage** Dolo+ decomposition of a consumption–savings model with portfolio choice.

**B2 idea (\"apply returns inside the portfolio stage\")**:

- The **portfolio stage** chooses the risky share `sigma` and applies the risky return shock `R` in the decision→continuation transition:

\[
b = a\cdot (\sigma R + (1-\sigma)R^f).
\]

So its continuation value is a function of **bank balances only**: \(V_{\text{cntn}} = V_{\text{cntn}}(b)\).

- The **consumption stage** then takes `b` and an income shock `y`, and chooses consumption `c` (EGM-style).

Files:
- `portfolio_stage.yaml`: portfolio-choice stage with post-decision RoR shock `R`, outputs `b`.
- `cons_stage.yaml`: EGM-style consumption stage with income shock `y` only (no RoR shock here).
- `calibration.yaml`, `settings.yaml`: numeric bindings for parameters/settings referenced in the stage files.

Notes:
- This is a **representation example** (syntax + timing). It is not yet wired into a full multi-stage execution/solve pipeline in Dolo.
