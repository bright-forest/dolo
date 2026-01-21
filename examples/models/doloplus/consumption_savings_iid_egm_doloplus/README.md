## consumption_savings_iid_egm_doloplus (split-file / spec_0.1c-style)

This folder is a **design-forward** variant of `../consumption_savings_iid_egm_doloplus.yaml`.

Goal: illustrate the **Foundations-aligned** split:

- `stage.yaml`: syntactic stage (no numeric calibration / settings)
- `calibration.yaml`: **parameter-only** bindings (calibration functor)
- `settings.yaml`: numerical/settings bindings (grid sizes, bounds, tolerances, …)
- `methods.yml`: methodization choices (schemes/methods + wiring to `symbols.settings`)
- `initial_values.yaml`: optional solver warm-starts / initial guesses (not calibration)

It also updates `symbols:` to the **decorator-based** form (e.g. `β: @in (0,1)`), and introduces a first-class `symbols.settings` group.

In particular, the exogenous shock is declared in syntax via a distribution decorator:

- `symbols.exogenous.y: [@in Y, @dist Normal(μ_y, σ_y)]`
- `μ_y, σ_y` are declared in `symbols.parameters` and bound in `calibration.yaml`

Note: runtime support for `model(stage) → calibrate(stage, calibration) → apply_settings(stage, settings)` is specified in `AI/prompts/dev-specs/dolo+/spec_0.1/0.1_c/spec_0.1c.md` but may not yet be implemented in code.
