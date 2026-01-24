# port-with-shocks (Dolo+ example)

This folder is a clean, modular example aligned with `docs/theory/references/unified/sections/`:

**Example: Portfolio Choice with Correlated Shocks**

Core idea:
- Portfolio choice is made **before** shocks.
- Return and income shocks are realized **jointly after** the portfolio decision (post-decision shock timing).
- Consumption then happens in a deterministic stage (no shocks in the cons stage).

## Stages

- `noport_stage.yaml`: shock realization stage (no decision), maps `k → m` with a transitory shock.
- `port_stage.yaml`: portfolio stage, maps `k → m` with control `ς` and joint post-decision shocks.
- `cons_stage.yaml`: consumption stage (EGM-style), maps `m → a` deterministically with control `c`.

## Period definitions

We provide three period types as separate YAML files (same ordering as the unified docs):

1. `cons_period.yaml` : `noport → cons` (period arvl `k`, period cntn `a`)
2. `port_cons_period.yaml` : `port → cons` (period arvl `k`, period cntn `a`)
3. `cons_port_period.yaml` : `cons → port` (period arvl `m`, period cntn `w` where `w` is a relabel of the port output `m`)

## “Optimal” period YAML structure (current direction)

Existing examples in this repo keep `period.yaml` minimal (`name` + ordered `stages:`), and assume that connections are implicit when variable names line up.

For port-with-shocks, variable names sometimes **must** be relabelled:
- within-period connectors (e.g. `a → k` when feeding cons output into port input)
- end-of-period relabels (e.g. `m → w` for the cons→port period type)
- between-period links (e.g. `k_{t+1} = a_t` for `k→a` periods)

So the “optimal” period YAML should allow optional explicit connector maps while keeping identity cases lightweight:

- **If names match**: omit the connector entry entirely (implicit identity).
- **If names differ**: provide a simple rename map (e.g. `{a: k}`).
- **If a bridge stage is required**: express it as an explicit stage in the period sequence (e.g. `noport` bridging `a → m`).

