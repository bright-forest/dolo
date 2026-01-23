"""
Solver for port-cons_period with sequential information structure.

This solver handles the port-cons_period from unified_modular-examples-using-port-with-shocks.md
where:
  1. Portfolio choice (ς) is made BEFORE shocks (Ψ, θ) realize
  2. Consumption choice (c) is made AFTER shocks realize, observing m

Since dolo cannot handle two sequential decisions with different information sets,
we use FIXED-POINT ITERATION:

  1. Initialize consumption policy χ(m)
  2. Solve portfolio problem given χ(m)
  3. Solve consumption problem given portfolio value function
  4. Iterate until convergence

The value function composition:
  𝒱(k) = max_ς E_{Ψ,θ}[𝒱_cons(m)]
       = max_ς E_{Ψ,θ}[max_c {u(c) + β 𝒱(m - c)}]
  
where m = k(ς Ψ + (1-ς) R) + θ
"""

import numpy as np
from scipy.optimize import minimize_scalar, brentq
from scipy.interpolate import interp1d
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


class PortConsModel:
    """
    Port-cons_period model with sequential information structure.
    
    Parameters
    ----------
    beta : float
        Discount factor
    rho : float
        Relative risk aversion (CRRA)
    R : float
        Risk-free gross return
    mu_psi : float
        Log of expected risky gross return
    sigma_psi : float
        Std dev of log risky return
    sigma_theta : float
        Std dev of log transitory income
    """
    
    def __init__(self, beta=0.96, rho=10.0, R=1.0, mu_psi=0.058,
                 sigma_psi=0.15, sigma_theta=0.10):
        self.beta = beta
        self.rho = rho
        self.R = R
        self.mu_psi = mu_psi
        self.sigma_psi = sigma_psi
        self.sigma_theta = sigma_theta
        
        # Grids
        self.k_grid = np.linspace(0.1, 10.0, 100)  # Kapital grid
        self.m_grid = np.linspace(0.1, 15.0, 150)  # Market resources grid
        
        # Quadrature for expectations
        self.n_quad = 7
        self._setup_quadrature()
        
        # Initialize policies
        self.cons_policy = None  # χ(m)
        self.port_policy = None  # ς(k)
        self.V_cons = None       # 𝒱_cons(m)
        self.V_port = None       # 𝒱_port(k)
    
    def _setup_quadrature(self):
        """Setup Gauss-Hermite quadrature for bivariate normal."""
        nodes, weights = np.polynomial.hermite.hermgauss(self.n_quad)
        nodes = nodes * np.sqrt(2)
        weights = weights / np.sqrt(np.pi)
        
        # Create tensor product for bivariate
        self.z_psi, self.z_theta = np.meshgrid(nodes, nodes)
        self.w_psi, self.w_theta = np.meshgrid(weights, weights)
        self.z_psi = self.z_psi.flatten()
        self.z_theta = self.z_theta.flatten()
        self.quad_weights = (self.w_psi * self.w_theta).flatten()
        
        # Transform to shock levels
        self.psi_nodes = np.exp(self.sigma_psi * self.z_psi + self.mu_psi - self.sigma_psi**2/2)
        self.theta_nodes = np.exp(self.sigma_theta * self.z_theta - self.sigma_theta**2/2)
    
    def u(self, c):
        """CRRA utility."""
        if np.any(c <= 0):
            return -np.inf * np.ones_like(c) if hasattr(c, '__len__') else -np.inf
        if abs(self.rho - 1) < 1e-10:
            return np.log(c)
        return c**(1 - self.rho) / (1 - self.rho)
    
    def u_prime(self, c):
        """Marginal utility."""
        return c**(-self.rho)
    
    def u_prime_inv(self, mu):
        """Inverse marginal utility."""
        return mu**(-1/self.rho)
    
    def initialize_policies(self):
        """Initialize with simple heuristic policies."""
        # Initial consumption: constant fraction of resources
        self.cons_policy = interp1d(self.m_grid, 0.5 * self.m_grid,
                                   kind='linear', fill_value='extrapolate')
        # Initial portfolio: constant share
        self.port_policy = interp1d(self.k_grid, 0.5 * np.ones_like(self.k_grid),
                                   kind='linear', fill_value='extrapolate')
        # Initial value functions (very rough)
        self.V_cons = interp1d(self.m_grid, self.u(0.5 * self.m_grid) / (1 - self.beta),
                              kind='linear', fill_value='extrapolate')
        self.V_port = interp1d(self.k_grid, self.u(0.5 * self.k_grid) / (1 - self.beta),
                              kind='linear', fill_value='extrapolate')
    
    def solve_consumption_step(self):
        """
        Solve consumption problem given portfolio value function.
        
        𝒱_cons(m) = max_c {u(c) + β E[𝒱_port(a)]}
        
        where a = m - c and expectation is over next period's shocks.
        
        Since cons stage has no shocks, and 𝒱_port(a) already includes
        the expectation over next period's shocks, we have:
        
        𝒱_cons(m) = max_c {u(c) + β 𝒱_port(m - c)}
        
        FOC: u'(c) = β 𝒱'_port(a)
        """
        new_cons = np.zeros_like(self.m_grid)
        new_V_cons = np.zeros_like(self.m_grid)
        
        # Compute marginal value of portfolio function (numerical derivative)
        dk = 1e-6
        V_port_prime = lambda k: (self.V_port(k + dk) - self.V_port(k - dk)) / (2 * dk)
        
        for i, m in enumerate(self.m_grid):
            if m <= 0.01:
                new_cons[i] = 0.01
                new_V_cons[i] = self.u(0.01)
                continue
            
            # Solve FOC: u'(c) = β V'_port(m - c)
            def foc(c):
                if c <= 0 or c >= m:
                    return np.inf
                a = m - c
                if a < self.k_grid[0]:
                    return np.inf
                return self.u_prime(c) - self.beta * V_port_prime(a)
            
            # Try to find interior solution
            try:
                c_opt = brentq(foc, 0.01, m - 0.01)
            except:
                # Corner solution: consume everything or minimum
                c_opt = min(m - 0.01, max(0.01, m * 0.9))
            
            new_cons[i] = c_opt
            a = m - c_opt
            new_V_cons[i] = self.u(c_opt) + self.beta * self.V_port(max(a, self.k_grid[0]))
        
        self.cons_policy = interp1d(self.m_grid, new_cons, kind='linear', fill_value='extrapolate')
        self.V_cons = interp1d(self.m_grid, new_V_cons, kind='linear', fill_value='extrapolate')
        
        return new_cons
    
    def solve_portfolio_step(self):
        """
        Solve portfolio problem given consumption policy.
        
        𝒱_port(k) = max_ς E_{Ψ,θ}[𝒱_cons(m)]
        
        where m = k(ς Ψ + (1-ς) R) + θ
        
        Since consumption is chosen optimally after observing m:
        𝒱_cons(m) = u(χ(m)) + β 𝒱_port(m - χ(m))
        """
        new_port = np.zeros_like(self.k_grid)
        new_V_port = np.zeros_like(self.k_grid)
        
        for i, k in enumerate(self.k_grid):
            def neg_expected_V(varsigma):
                """Negative expected value for minimization."""
                if varsigma < 0 or varsigma > 1:
                    return np.inf
                
                # Compute m for each shock realization
                R_port = varsigma * self.psi_nodes + (1 - varsigma) * self.R
                m_vals = k * R_port + self.theta_nodes
                
                # Get V_cons at each m
                V_vals = np.array([self.V_cons(max(m, self.m_grid[0])) for m in m_vals])
                
                # Expected value
                EV = np.sum(self.quad_weights * V_vals)
                return -EV
            
            # Optimize over ς
            result = minimize_scalar(neg_expected_V, bounds=(0.001, 0.999), method='bounded')
            new_port[i] = result.x
            new_V_port[i] = -result.fun
        
        self.port_policy = interp1d(self.k_grid, new_port, kind='linear', fill_value='extrapolate')
        self.V_port = interp1d(self.k_grid, new_V_port, kind='linear', fill_value='extrapolate')
        
        return new_port
    
    def solve(self, tol=1e-4, max_iter=100, verbose=True):
        """
        Solve by fixed-point iteration.
        
        Returns
        -------
        dict with keys:
            'converged': bool
            'iterations': int
            'cons_policy': function χ(m)
            'port_policy': function ς(k)
            'V_cons': function 𝒱_cons(m)
            'V_port': function 𝒱_port(k)
        """
        self.initialize_policies()
        
        if verbose:
            print("="*60)
            print("PORT-CONS PERIOD: Fixed-Point Iteration Solver")
            print("="*60)
            print(f"Parameters: β={self.beta}, ρ={self.rho}, R={self.R}")
            print(f"           E[Ψ]={np.exp(self.mu_psi):.4f}, σ_Ψ={self.sigma_psi}, σ_θ={self.sigma_theta}")
            print("-"*60)
        
        for it in range(max_iter):
            # Save old policies
            old_cons = self.cons_policy(self.m_grid).copy()
            old_port = self.port_policy(self.k_grid).copy()
            
            # Iteration steps
            self.solve_portfolio_step()
            self.solve_consumption_step()
            
            # Check convergence
            cons_diff = np.max(np.abs(self.cons_policy(self.m_grid) - old_cons))
            port_diff = np.max(np.abs(self.port_policy(self.k_grid) - old_port))
            
            if verbose and it % 10 == 0:
                print(f"Iter {it:3d}: Δχ = {cons_diff:.6f}, Δς = {port_diff:.6f}")
            
            if cons_diff < tol and port_diff < tol:
                if verbose:
                    print(f"Converged at iteration {it}")
                return {
                    'converged': True,
                    'iterations': it,
                    'cons_policy': self.cons_policy,
                    'port_policy': self.port_policy,
                    'V_cons': self.V_cons,
                    'V_port': self.V_port
                }
        
        if verbose:
            print(f"Did not converge after {max_iter} iterations")
        return {
            'converged': False,
            'iterations': max_iter,
            'cons_policy': self.cons_policy,
            'port_policy': self.port_policy,
            'V_cons': self.V_cons,
            'V_port': self.V_port
        }


def main():
    """Solve and visualize the port-cons period problem."""
    
    # Create and solve model
    model = PortConsModel(beta=0.96, rho=10.0, R=1.0,
                         mu_psi=0.058, sigma_psi=0.15, sigma_theta=0.10)
    
    result = model.solve(verbose=True)
    
    print("\n" + "="*60)
    print("SOLUTION SUMMARY")
    print("="*60)
    
    # Sample policy values
    print("\nPortfolio Policy ς*(k):")
    for k in [0.5, 1.0, 2.0, 5.0, 10.0]:
        print(f"  k = {k:5.1f}: ς* = {model.port_policy(k):.4f}")
    
    print("\nConsumption Policy χ(m):")
    for m in [0.5, 1.0, 2.0, 5.0, 10.0]:
        c = model.cons_policy(m)
        print(f"  m = {m:5.1f}: c = {c:.4f}, c/m = {c/m:.4f}")
    
    # Create visualization
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    
    # Portfolio policy
    ax1 = axes[0, 0]
    ax1.plot(model.k_grid, model.port_policy(model.k_grid), 'b-', linewidth=2)
    ax1.set_xlabel('k (kapital)')
    ax1.set_ylabel('ς* (portfolio share)')
    ax1.set_title('Portfolio Policy ς*(k)')
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim([0, 1])
    
    # Consumption policy
    ax2 = axes[0, 1]
    ax2.plot(model.m_grid, model.cons_policy(model.m_grid), 'r-', linewidth=2, label='c = χ(m)')
    ax2.plot(model.m_grid, model.m_grid, 'k--', linewidth=1, alpha=0.5, label='45° line')
    ax2.set_xlabel('m (market resources)')
    ax2.set_ylabel('c (consumption)')
    ax2.set_title('Consumption Policy χ(m)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # Consumption ratio
    ax3 = axes[1, 0]
    c_ratio = model.cons_policy(model.m_grid) / model.m_grid
    ax3.plot(model.m_grid, c_ratio, 'g-', linewidth=2)
    ax3.set_xlabel('m (market resources)')
    ax3.set_ylabel('c/m (consumption ratio)')
    ax3.set_title('Consumption-to-Resources Ratio')
    ax3.grid(True, alpha=0.3)
    
    # Value functions
    ax4 = axes[1, 1]
    ax4.plot(model.k_grid, model.V_port(model.k_grid), 'b-', linewidth=2, label='𝒱_port(k)')
    ax4.plot(model.m_grid[:len(model.k_grid)], model.V_cons(model.m_grid[:len(model.k_grid)]), 
             'r--', linewidth=2, label='𝒱_cons(m)')
    ax4.set_xlabel('k or m')
    ax4.set_ylabel('Value')
    ax4.set_title('Value Functions')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    plt.suptitle('Port-Cons Period: Sequential Portfolio and Consumption Choice', fontsize=14)
    plt.tight_layout()
    plt.savefig('port_cons_period_solution.png', dpi=150)
    print("\nSaved: port_cons_period_solution.png")
    
    return model, result


if __name__ == "__main__":
    model, result = main()
