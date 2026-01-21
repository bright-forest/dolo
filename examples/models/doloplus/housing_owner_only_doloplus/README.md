# Housing Owner Model (Dolo+ Two-Stage ADC Format)

## Overview

A simplified housing model in Dolo+ format with two sequential stages per period.
Based on the FUES housing-renting model from Fella (2014), with renting removed.

## Model Structure

### Two Stages per Period

1. **Housing Choice Stage** (`stages/housing_choice.yaml`)
   - Income shock realized
   - Discrete choice over housing stock H_nxt
   - Transaction costs phi when adjusting housing
   - Computes cash-on-hand after housing adjustment

2. **Consumption Choice Stage** (`stages/consumption_choice.yaml`)
   - Given cash-on-hand and housing, choose consumption
   - Solved via Endogenous Grid Method (EGM)
   - FUES upper envelope handles non-convexities

### ADC Structure (Per Stage)

Each stage follows the Arrival-Decision-Continuation structure:

**Housing Stage:**
- Arrival: (a, H, y_pre) - assets, housing, previous shock
- Decision: (a, H, y) - after shock, choose H_nxt
- Continuation: (w, H_nxt, y) - cash-on-hand after adjustment

**Consumption Stage:**
- Arrival: (w, H_nxt, y) - from housing stage
- Decision: (w, H_nxt, y) - choose c
- Continuation: (a_nxt, H_nxt, y) - end-of-period assets

### Key Equations

**Housing budget (stage 1):**
```
w = (1 + r)*a + z(y) + H - (1 + phi*I_{H_nxt != H})*H_nxt
```

**Savings (stage 2):**
```
a_nxt = w - c
```

**Utility (Cobb-Douglas/CRRA):**
```
u(c, H) = ((c^theta * (kappa*H + iota)^(1-theta))^(1-gamma)) / (1-gamma)
```

## File Structure

```
housing_owner_only_doloplus/
  period.yaml          # Period definition (connects stages)
  calibration.yaml     # Parameter values
  settings.yaml        # Numerical settings
  README.md            # This file
  stages/
    housing_choice.yaml     # Stage 1: housing decision
    consumption_choice.yaml # Stage 2: consumption decision
```

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| beta | Discount factor | 0.93 |
| gamma | CRRA coefficient | 2.0 |
| r | Interest rate | 0.06 |
| phi | Housing transaction cost | 0.07 |
| theta | Consumption weight | 0.77 |
| kappa | Housing service scaling | 0.075 |
| iota | Housing service constant | 0.01 |

## Solution Method

- **Housing choice**: Discrete choice with upper envelope
- **Consumption**: EGM with FUES (Fast Upper Envelope Scan)
- **Income shocks**: Discrete Markov process (49 states)

## Source

Adapted from:
- FUES repository: https://github.com/akshayshanker/FUES
- Branch: time_inconsistency
- Original config: `examples/housing_renting/config_HR/test_0.4/`
- Reference: Fella, G. (2014). "A Generalized Endogenous Grid Method for
  Non-Smooth and Non-Concave Problems." Review of Economic Dynamics.
