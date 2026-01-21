# Conjugate Bellman Transform: Consumption-Savings Model

This directory contains the **semiconjugate (conjugate) transformation** of the
standard consumption-savings model from `consumption_savings_iid_egm_doloplus/`.

## The Key Insight

The transformation moves the expectation **INSIDE** the decision problem:

**Original (S = E ∘ max):**
```
V = E_y[ max_c{ u(c) + β*V' } ]
    ^^^^
    Expectation is OUTSIDE the max
```

**Conjugate (Ŝ = max ∘ E):**
```
V = max_c{ u(c) + β*E_y[V'] }
                  ^^^^
    Expectation is INSIDE the max (in continuation value)
```

This is **NOT** about moving which mover has the expectation.  
It's about the **structure of the decision problem itself**.

## ADC Representation

### Original Stage

```yaml
cntn_to_dcsn_mover:
  Bellman: |
    V[_dcsn] = max_{c}(u(c) + β*V[_cntn])
    #                        ^^^^^^^^
    # "Raw" continuation value

dcsn_to_arvl_mover:
  Bellman: |
    V[_arvl] = E_{y}(V[_dcsn])
    #          ^^^^
    # Expectation is HERE (outside the max)
```

### Conjugate Stage

```yaml
cntn_to_dcsn_mover:
  Bellman: |
    V[_dcsn] = max_{c}(u(c) + β*E_{y}(V[_cntn]))
    #                        ^^^^^^^^^^^^^^^
    # Expectation INSIDE the decision!

dcsn_to_arvl_mover:
  Bellman: |
    V[_arvl] = V[_dcsn]
    # Identity (no expectation here)
```

## Why This Matters

### Computational Advantage

**Original:** Must solve the max for EACH shock realization, then average
```
For each y_i:
    V_i(w) = max_c{ u(c) + β*V'(g(w,c,y_i)) }
V(w) = Σ p_i * V_i(w)
```
Cost: O(n_y × n_grid × optimization_cost)

**Conjugate:** Average first (smooth), then solve ONE max
```
Ṽ(a) = Σ p_i * V'(g(a, y_i))           # Precompute expected continuation
V(w) = max_c{ u(c) + β*Ṽ(w-c) }        # ONE smooth optimization
```
Cost: O(n_grid × (n_y + optimization_cost))

### Smoothness

In the conjugate form, the agent optimizes over a **smooth** continuation value:
- No discontinuities from the max operating over different shock realizations
- Better numerical stability
- Faster convergence
- Natural fit with EGM (the grid is over post-decision states)

## Mathematical Foundation: Stachurski Semiconjugacy

### The Iterates Lemma

From `AI/prompts/03012025/final-report/source-reports/semiconjugacy-iterates.tex`:

**Definition (Order Semiconjugacy):**
Let $(V, S)$ and $(\hat{V}, \hat{S})$ be dynamical systems. They are *order semiconjugate under $F, G$* when:

$$S = G \circ F \quad \text{and} \quad \hat{S} = F \circ G$$

**Lemma (Iterates under Semiconjugacy):**
For all $n \geq 1$:

$$S^n = G \circ \hat{S}^{n-1} \circ F \quad \text{and} \quad \hat{S}^n = F \circ S^{n-1} \circ G$$

### The Maps

**F: V → Ṽ (Value → Expected Value)**
$$F: V \mapsto \tilde{V}$$
$$\tilde{V}(a) = E_y[V(g(a, y))]$$

**G: Ṽ → V (Expected Value → Optimized Value)**
$$G: \tilde{V} \mapsto V$$
$$V(w) = \max_c\{u(c) + \beta \cdot \tilde{V}(w - c)\}$$

## Files

| File | Description |
|------|-------------|
| `stage.yaml` | Conjugate stage with E_y inside the decision |
| `calibration.yaml` | Parameter values (same as original) |
| `settings.yaml` | Numerical settings (same as original) |

## Usage

```python
from dolo.compiler.semiconjugate import conjugate_transform

# Load original stage
import yaml
with open("../consumption_savings_iid_egm_doloplus/stage.yaml") as f:
    original = yaml.safe_load(f)

# Apply transformation
transform = conjugate_transform(original)
conjugate = transform.conjugate_stage

# Compare the decision equations
print("Original:", original['equations']['cntn_to_dcsn_mover']['Bellman'])
# V[_dcsn] = max_{c}(u(c) + β*V[_cntn])

print("Conjugate:", conjugate['equations']['cntn_to_dcsn_mover']['Bellman'])
# V[_dcsn] = max_{c}(u(c) + β*E_{y}(V[_cntn]))
#                          ^^^^^^^^^^^^^^^^
#                    Expectation moved inside!
```

## References

- Stachurski & Sargent (2025). *Dynamic Programming, Vol. 2*, Ch. Transforms
- Ma, Stachurski & Toda (2022). "Q-Transform" paper
- Carroll (2006). "The Method of Endogenous Gridpoints"
