## consumption_portfolio_b1_doloplus (two-stage sketch; B1)

This folder sketches a **two-stage** Dolo+ decomposition of a consumption–savings model with portfolio choice.

**B1 idea (\"carry the share\")**:

- The **portfolio stage** chooses the risky share `sigma` but does **not** apply the risky return shock.
  - Its continuation value is therefore a function of **(bank balance, share)**: \(V_{\text{cntn}} = V_{\text{cntn}}(b, \sigma)\).
- The **consumption stage** then receives `(b, sigma)` and a realized rate-of-return shock `R`, and chooses consumption `c`.

Files:
- `cons_stage.yaml`: EGM-style consumption stage with **income shock** `y` and **RoR shock** `R` (both observed at decision time).
- `portfolio_stage.yaml`: portfolio-choice stage (choose `sigma`), outputs `(b, sigma)` to be used by the next consumption stage.
- `calibration.yaml`, `settings.yaml`: numeric bindings for parameters/settings referenced in the stage files.

Notes:
- This is a **representation example** (syntax + timing). It is not yet wired into a full multi-stage execution/solve pipeline in Dolo.
