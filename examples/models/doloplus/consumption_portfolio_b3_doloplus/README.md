## consumption_portfolio_b3_doloplus (two-stage sketch; B3)

This folder sketches a **two-stage** Dolo+ decomposition of a consumption–savings model with portfolio choice, implementing the timing idea in `AI/context/correspondences/email/CDC-port-21012026.md`.

### B3 idea (“realize all shocks after portfolio choice”)

Goal: allow **unrestricted correlation** between return shocks and income shocks *without* requiring conditional-expectation machinery.

- The **consumption stage** is *shock-free*: it takes fully realized cash-on-hand (Pablo’s \(w\), here `m`) as input and chooses `c`, producing end-of-stage assets `a`.
  - In `cons_stage.yaml`, this is encoded by the identity arrival→decision transition:
    - \(w_{\text{dcsn}} = m_{\text{arvl}}\)

- The **portfolio stage** chooses the risky share `shr`, and then **both** the income shock `y` and risky return shock `Risky` are realized *after* the decision (between dcsn and cntn). The continuation state is cash-on-hand `m`, which becomes the next consumption stage’s input.
  - In `portfolio_stage.yaml`, the Bellman recursion uses a **joint** expectation operator:
    - \(V_{\text{dcsn}} = \max_{\text{shr}} \; E_{y,R}(V_{\text{cntn}})\)

### Files

- `cons_stage.yaml`: shock-free EGM-style consumption stage (input `m`, state `w`, output `a`)
- `portfolio_stage.yaml`: portfolio choice stage; shocks realized post-decision; output `m`
- `period.yaml`: stage ordering within the period (`cons_stage` then `portfolio_stage`)
- `calibration.yaml`, `settings.yaml`: numeric bindings for parameters/settings referenced in the stage files

Notes:
- This is a **representation example** (syntax + timing). It is not yet wired into a full multi-stage execution/solve pipeline in Dolo.

