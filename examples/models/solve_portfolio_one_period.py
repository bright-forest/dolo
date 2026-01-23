"""
One-period Merton-Samuelson portfolio problem with post-decision income shocks.

This script solves the standalone portfolio problem from the port-with-shocks
architecture (unified_modular-examples-using-port-with-shocks.md).

Problem:
    V(k) = max_{ς ∈ [0,1]} E_ζ[u(m)]
    
    where:
        m = k(ς Ψ + (1-ς) R) + θ      (market resources after shocks)
        u(m) = m^(1-ρ)/(1-ρ)          (CRRA utility)
        ζ = (Ψ, θ)                    (joint lognormal shocks)

Shock distributions:
    log(Ψ) ~ N(μ_Ψ - σ²_Ψ/2, σ²_Ψ)   => E[Ψ] = exp(μ_Ψ)
    log(θ) ~ N(-σ²_θ/2, σ²_θ)        => E[θ] = 1

Merton-Samuelson formula (without income shock):
    ς* = (E[Ψ] - R) / (ρ × Var(Ψ))
    
With income shocks, the portfolio share varies with k because:
    - Income floor θ provides insurance
    - Poor agents (low k) can afford more portfolio risk
    - Rich agents (high k) behave closer to pure Merton-Samuelson
"""

import numpy as np
from scipy.optimize import minimize_scalar
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for headless environments
import matplotlib.pyplot as plt


def merton_samuelson_portfolio_share(equity_premium, risk_aversion, return_variance):
    """
    Classic Merton-Samuelson formula for optimal portfolio share.
    
    ς* = (E[R_risky] - R_f) / (ρ × Var(R_risky))
    
    This is the limit as wealth -> infinity (income becomes negligible).
    """
    return equity_premium / (risk_aversion * return_variance)


def compute_expected_utility(varsigma, k, rho, R, mu_psi, sigma_psi, sigma_theta,
                             n_quadrature=7):
    """
    Compute E[u(m)] for given portfolio share using Gauss-Hermite quadrature.
    
    Parameters
    ----------
    varsigma : float
        Portfolio share in risky asset
    k : float
        Initial kapital (investable assets)
    rho : float
        Relative risk aversion
    R : float
        Risk-free gross return
    mu_psi : float
        Log of expected risky gross return
    sigma_psi : float
        Std dev of log risky return
    sigma_theta : float
        Std dev of log transitory income shock
    n_quadrature : int
        Number of Gauss-Hermite nodes per dimension
        
    Returns
    -------
    float
        Expected utility E[u(m)]
    """
    # Gauss-Hermite quadrature nodes and weights
    nodes, weights = np.polynomial.hermite.hermgauss(n_quadrature)
    nodes = nodes * np.sqrt(2)  # Scale for standard normal
    weights = weights / np.sqrt(np.pi)  # Normalize
    
    total = 0.0
    for z_psi, w_psi in zip(nodes, weights):
        for z_theta, w_theta in zip(nodes, weights):
            # Transform to lognormal shocks (mean-corrected)
            psi = np.exp(sigma_psi * z_psi + mu_psi - sigma_psi**2/2)
            theta = np.exp(sigma_theta * z_theta - sigma_theta**2/2)
            
            # Market resources after portfolio return and income shock
            Rport = varsigma * psi + (1 - varsigma) * R
            m = k * Rport + theta
            
            # CRRA utility
            if m > 0:
                if abs(rho - 1) < 1e-10:
                    u = np.log(m)
                else:
                    u = m**(1-rho) / (1-rho)
            else:
                u = -1e10  # Very negative for infeasible outcomes
            
            total += w_psi * w_theta * u
    
    return total


def solve_one_period_portfolio(k, rho, R=1.0, mu_psi=0.058, sigma_psi=0.15,
                               sigma_theta=0.10, n_quadrature=7):
    """
    Solve one-period portfolio problem for optimal share varsigma*.
    
    Parameters
    ----------
    k : float
        Initial kapital (investable assets)
    rho : float
        Relative risk aversion
    R : float
        Risk-free gross return
    mu_psi : float
        Log of expected risky gross return (E[Ψ] = exp(mu_psi))
    sigma_psi : float
        Std dev of log risky return
    sigma_theta : float
        Std dev of log transitory income shock
    n_quadrature : int
        Number of Gauss-Hermite nodes per dimension
        
    Returns
    -------
    dict
        Dictionary with keys:
        - 'varsigma_star': optimal portfolio share
        - 'expected_utility': E[u(m)] at optimum
        - 'k': input kapital
        - 'rho': risk aversion
    """
    def neg_expected_utility(varsigma):
        return -compute_expected_utility(varsigma, k, rho, R, mu_psi, sigma_psi,
                                         sigma_theta, n_quadrature)
    
    # Optimize over [0, 1] with small buffer to avoid boundary issues
    result = minimize_scalar(neg_expected_utility, bounds=(0.001, 0.999),
                            method='bounded')
    
    return {
        'varsigma_star': result.x,
        'expected_utility': -result.fun,
        'k': k,
        'rho': rho
    }


def main():
    """Solve and visualize the one-period portfolio problem."""
    
    # Baseline parameters
    R = 1.0
    mu_psi = 0.058  # E[Ψ] ≈ 1.06 (6% expected gross return)
    sigma_psi = 0.15
    sigma_theta = 0.10
    
    # Compute Merton-Samuelson benchmark (no income shock)
    E_psi = np.exp(mu_psi)
    equity_premium = E_psi - R
    var_psi = (np.exp(sigma_psi**2) - 1) * np.exp(2*mu_psi)  # Exact variance
    
    print("="*70)
    print("ONE-PERIOD PORTFOLIO PROBLEM: PORT-WITH-SHOCKS ARCHITECTURE")
    print("="*70)
    print(f"\nParameters:")
    print(f"  R (risk-free return):      {R:.2f}")
    print(f"  E[Ψ] (expected risky):     {E_psi:.4f}")
    print(f"  σ_Ψ (risky volatility):    {sigma_psi:.2f}")
    print(f"  Var(Ψ):                    {var_psi:.6f}")
    print(f"  E[θ] (expected income):    1.0")
    print(f"  σ_θ (income volatility):   {sigma_theta:.2f}")
    print(f"  Equity premium:            {equity_premium:.4f} ({100*equity_premium:.1f}%)")
    
    # Merton-Samuelson formula
    print("\n" + "-"*70)
    print("Merton-Samuelson Formula (no income shock limit):")
    print("-"*70)
    for rho in [4, 6, 8, 10, 15, 20]:
        ms_share = merton_samuelson_portfolio_share(equity_premium, rho, var_psi)
        print(f"  ρ = {rho:4.0f}: ς* = {min(ms_share, 1.0):.4f}" + 
              (" (capped at 1)" if ms_share > 1 else ""))
    
    # Solve with income shocks for different rho
    print("\n" + "-"*70)
    print("With Income Shocks (k = 1.0):")
    print("-"*70)
    k = 1.0
    for rho in [4, 6, 8, 10, 15, 20]:
        result = solve_one_period_portfolio(k, rho, R, mu_psi, sigma_psi, sigma_theta)
        ms_share = merton_samuelson_portfolio_share(equity_premium, rho, var_psi)
        print(f"  ρ = {rho:4.0f}: ς* = {result['varsigma_star']:.4f}  "
              f"(MS limit: {min(ms_share, 1.0):.4f})")
    
    # Policy function: varsigma*(k) for different k
    print("\n" + "-"*70)
    print("Policy Function ς*(k) for ρ = 10:")
    print("-"*70)
    rho = 10.0
    k_grid = np.array([0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0])
    results = []
    for k_val in k_grid:
        result = solve_one_period_portfolio(k_val, rho, R, mu_psi, sigma_psi, sigma_theta)
        results.append(result)
        print(f"  k = {k_val:6.1f}: ς* = {result['varsigma_star']:.4f}")
    
    ms_limit = merton_samuelson_portfolio_share(equity_premium, rho, var_psi)
    print(f"\n  Merton-Samuelson limit (k → ∞): ς* → {ms_limit:.4f}")
    
    # Create visualization
    print("\n" + "-"*70)
    print("Creating visualization...")
    print("-"*70)
    
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    
    # Plot 1: Policy function ς*(k)
    ax1 = axes[0]
    k_fine = np.linspace(0.1, 20, 50)
    varsigma_fine = []
    for k_val in k_fine:
        result = solve_one_period_portfolio(k_val, rho, R, mu_psi, sigma_psi, sigma_theta)
        varsigma_fine.append(result['varsigma_star'])
    
    ax1.plot(k_fine, varsigma_fine, 'b-', linewidth=2, label='ς*(k)')
    ax1.axhline(ms_limit, color='r', linestyle='--', linewidth=1.5,
                label=f'Merton-Samuelson limit: {ms_limit:.3f}')
    ax1.set_xlabel('k (kapital)', fontsize=12)
    ax1.set_ylabel('ς* (optimal risky share)', fontsize=12)
    ax1.set_title(f'Portfolio Policy Function (ρ = {rho})', fontsize=14)
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim([0, 20])
    ax1.set_ylim([0, 1])
    
    # Plot 2: Policy for different rho
    ax2 = axes[1]
    rho_values = [6, 10, 15, 20]
    colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(rho_values)))
    
    for rho_val, color in zip(rho_values, colors):
        varsigma_rho = []
        for k_val in k_fine:
            result = solve_one_period_portfolio(k_val, rho_val, R, mu_psi, sigma_psi, sigma_theta)
            varsigma_rho.append(result['varsigma_star'])
        ax2.plot(k_fine, varsigma_rho, color=color, linewidth=2, label=f'ρ = {rho_val}')
    
    ax2.set_xlabel('k (kapital)', fontsize=12)
    ax2.set_ylabel('ς* (optimal risky share)', fontsize=12)
    ax2.set_title('Portfolio Policy for Different Risk Aversion', fontsize=14)
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim([0, 20])
    ax2.set_ylim([0, 1])
    
    plt.tight_layout()
    plt.savefig('portfolio_one_period_solution.png', dpi=150, bbox_inches='tight')
    print("Saved: portfolio_one_period_solution.png")
    
    # plt.show()  # Commented out for non-interactive use
    
    return results


if __name__ == "__main__":
    main()
