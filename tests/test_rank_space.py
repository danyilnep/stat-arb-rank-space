"""Tests for rank_space.py (the mathematics) and for the refactored main.py.

Three groups:

* Properties of each step of Algorithms 1 and 2: the regression residuals are uncorrelated
  with the factor, Phi removes the factor and nothing else, the AR(1) fit recovers a known OU
  process, the position rule of Eq. 2.2.7 opens, holds and closes as documented, the paper's
  weights are L1-normalised, and the traded hedge offsets the legs' factor exposure.
* Equivalence: ``main.RankSpaceStatArb.rank_weights`` after the refactor against a verbatim copy
  of the inline code that ran on QuantConnect (runs sa__v3_2011 and sa__v3_2018), on 240 seeded
  random panels over several sequential days. Every output must be bit-for-bit identical.
* Consistency: the defaults in main.py match config.json; main.py and rank_space.py have the
  same syntax tree, docstrings removed, as the code the v4 backtests ran (from the raw export of
  sa__v4_2018 in results/raw/), so they differ from it only in docstrings and comments; and
  results/provenance/code_hashes.json agrees with the code in results/raw/ and results/runs.csv.

The raw exports publish the code with one docstring paragraph rewritten to leave out the names
of the other 2024 team members. results/provenance/code_hashes.json records, per export and
code file, the SHA-256 as run on QuantConnect ("as_run") and as published ("published"); the
tests check the published hash against the code in results/raw/ and the as-run hash against
the values recorded when the backtests ran.

Equation numbers refer to arXiv:2410.06568v1.

main.py imports QuantConnect's ``AlgorithmImports``; the tests replace it with a stub module that
defines only the names main.py needs at import time. No QuantConnect code runs here.
"""

import ast
import csv
import gzip
import hashlib
import importlib.util
import inspect
import json
import os
import re
import sys
import types
import typing
import warnings
from collections import deque
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

import rank_space as rs

ROOT = Path(__file__).resolve().parents[1]
OPEN, CLOSE, MAX_TAU = 1.25, 0.5, 30.0


def factor_panel(rng, rows, n, idio_scale=0.01):
    """One-factor returns plus Gaussian idiosyncratic noise, rows x n."""
    f = rng.normal(0.0, 0.01, rows)
    loadings = rng.uniform(0.5, 1.5, n)
    return f[:, None] * loadings[None, :] + rng.normal(0.0, idio_scale, (rows, n))


def ar1_increments(rng, rows, n, b_low=0.5, b_high=0.98, scale=0.01):
    """Daily increments of independent AR(1) paths, so their cumulative sums mean-revert."""
    b = rng.uniform(b_low, b_high, n)
    x = np.zeros((rows + 1, n))
    shocks = rng.normal(0.0, scale, (rows, n))
    for t in range(rows):
        x[t + 1] = b * x[t] + shocks[t]
    return np.diff(x, axis=0)


# ---------------------------------------------------------------------------- Eq. 2.1.9
def test_rank_space_returns_is_change_in_cap_at_each_rank():
    caps = np.array([400.0, 250.0, 100.0])
    prev = np.array([320.0, 250.0, 200.0])
    assert np.array_equal(rs.rank_space_returns(caps, prev), np.array([0.25, 0.0, -0.5]))


def test_excess_returns_subtracts_rate_and_zeroes_missing():
    X = rs.excess_returns([np.array([0.01, np.nan]), np.array([0.03, 0.02])], 0.01)
    assert X.shape == (2, 2)
    assert np.allclose(X, [[0.0, 0.0], [0.02, 0.01]], rtol=0.0, atol=1e-15)


# ---------------------------------------------------------------------------- Algorithm 1
@pytest.mark.parametrize("seed, k_factors", [(1, 1), (2, 1), (3, 2), (4, 1)])
def test_residuals_uncorrelated_with_factor_over_loading_window(seed, k_factors):
    rng = np.random.default_rng(seed)
    X = factor_panel(rng, 252, 40)
    d = rs.market_decomposition(X, 60, k_factors)
    Fc = d.factor_returns - d.factor_returns.mean(axis=0)
    ec = d.residuals - d.residuals.mean(axis=0)
    for j in range(k_factors):
        corr = (ec * Fc[:, [j]]).sum(axis=0) / np.sqrt((ec ** 2).sum(axis=0) * (Fc[:, j] ** 2).sum())
        assert np.max(np.abs(corr)) < 1e-10


def test_residuals_are_regression_residuals_plus_intercept():
    """eps = Phi X keeps the intercept: eps = (X_L - alpha - F beta^T) + alpha."""
    rng = np.random.default_rng(5)
    X = factor_panel(rng, 252, 30)
    d = rs.market_decomposition(X, 60)
    XL = X[-60:]
    u = XL - d.alpha - d.factor_returns @ d.beta.T
    assert np.allclose(d.residuals, u + d.alpha, rtol=0.0, atol=1e-15)
    assert np.allclose(d.residuals.mean(axis=0), d.alpha, rtol=0.0, atol=1e-15)
    assert np.allclose(d.factor_returns, XL @ d.omega.T, rtol=0.0, atol=0.0)
    assert np.isclose(np.linalg.norm(d.omega[0]), 1.0)


def test_phi_subtracts_loading_times_factor_return():
    """Phi r = r - beta (omega . r) for any return vector r (Eq. 2.1.11 and 2.1.12, rank space)."""
    rng = np.random.default_rng(6)
    X = factor_panel(rng, 252, 25)
    d = rs.market_decomposition(X, 60)
    for _ in range(5):
        r = rng.normal(0.0, 0.02, 25)
        assert np.allclose(d.phi @ r, r - d.beta @ (d.omega @ r), rtol=0.0, atol=1e-15)
    # Row t of the residual matrix is Phi applied to that day's return.
    assert np.allclose(d.residuals[-1], d.phi @ X[-1], rtol=0.0, atol=1e-15)


def test_phi_maps_pure_factor_return_to_its_intercept_free_residual():
    """On a pure one-factor panel r_t = f_t v + c, Phi removes f_t v and leaves c - (c . v) v."""
    rng = np.random.default_rng(8)
    n = 20
    v = rng.normal(size=n)
    v /= np.linalg.norm(v)
    f = rng.normal(0.0, 0.01, 252)
    c = rng.normal(0.0, 0.001, n)
    X = f[:, None] * v[None, :] + c[None, :]
    d = rs.market_decomposition(X, 60)
    assert np.isclose(abs(d.omega[0] @ v), 1.0, rtol=0.0, atol=1e-12)
    assert np.allclose(d.phi @ v, 0.0, atol=1e-12)
    expected = c - (c @ v) * v
    assert np.allclose(d.residuals, np.broadcast_to(expected, d.residuals.shape), rtol=0.0, atol=1e-12)
    for t in (0, 100, 251):
        assert np.allclose(d.phi @ X[t], expected, rtol=0.0, atol=1e-12)


# ---------------------------------------------------------------------------- Algorithm 2, OU fit
def simulate_ou_path(rng, tau, mu, sigma, steps):
    b = np.exp(-1.0 / tau)
    x = np.empty(steps)
    x[0] = mu
    shocks = rng.normal(0.0, sigma, steps)
    for t in range(1, steps):
        x[t] = mu + b * (x[t - 1] - mu) + shocks[t]
    return x


@pytest.mark.parametrize("tau", [3.0, 10.0, 20.0])
def test_ou_fit_recovers_tau_mu_sigma(tau):
    rng = np.random.default_rng(int(tau * 100))
    mu, sigma = 0.3, 0.02
    x = simulate_ou_path(rng, tau, mu, sigma, 50_000)
    fit = rs.fit_ou(np.diff(x, prepend=0.0)[:, None])  # increments; fit_ou re-accumulates them
    assert np.allclose(fit.x[:, 0], x, rtol=0.0, atol=1e-9)
    assert bool(fit.valid[0])
    assert abs(fit.tau[0] - tau) / tau < 0.10
    sigma_eq_true = sigma / np.sqrt(1.0 - np.exp(-2.0 / tau))
    assert abs(fit.sigma_eq[0] - sigma_eq_true) / sigma_eq_true < 0.05
    assert abs(fit.mu[0] - mu) < 0.1 * sigma_eq_true


@pytest.mark.parametrize("sign", [+1.0, -1.0])
def test_s_score_sign_and_size(sign):
    rng = np.random.default_rng(11)
    x = simulate_ou_path(rng, 10.0, 0.0, 0.02, 50_000)
    base = rs.fit_ou(np.diff(x, prepend=0.0)[:, None])
    target = base.mu[0] + sign * 4.0 * base.sigma_eq[0]
    x = np.append(x, target)  # move the last point four equilibrium deviations away
    fit = rs.fit_ou(np.diff(x, prepend=0.0)[:, None])
    s = fit.s_score[0]
    assert np.sign(s) == sign
    assert 3.5 < abs(s) < 4.5
    assert s == (fit.x[-1, 0] - fit.mu[0]) / fit.sigma_eq[0]


def test_invalid_fits_are_masked_without_warnings():
    L = 60
    flat = np.zeros(L)                         # no variance: b undefined
    trend = np.ones(L)                         # x = 1, 2, 3, ...: b = 1, no mean reversion
    alternating = np.tile([1.0, -1.0], L // 2)  # x = 1, 0, 1, 0: b = -1
    rng = np.random.default_rng(12)
    good = np.diff(simulate_ou_path(rng, 5.0, 0.0, 0.01, L), prepend=0.0)
    eps = np.column_stack([flat, trend, alternating, good])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fit = rs.fit_ou(eps)
    assert fit.valid.tolist() == [False, False, False, True]
    assert np.isnan(fit.b[0]) and fit.b[1] == 1.0 and fit.b[2] < 0
    assert np.all(np.isinf(fit.tau[:3])) and np.all(np.isnan(fit.s_score[:3]))
    assert np.array_equal(fit.mu[:3], np.zeros(3)) and np.array_equal(fit.sigma_eq[:3], np.ones(3))
    assert np.isfinite(fit.s_score[3]) and 0.0 < fit.tau[3] < np.inf


# ---------------------------------------------------------------------------- Algorithm 2, Eq. 2.2.7
def step(pos, s, tau):
    return rs.update_positions(pos, np.asarray(s, dtype=float), np.asarray(tau, dtype=float),
                               OPEN, CLOSE, MAX_TAU)


def test_opens_long_below_and_short_above_the_open_threshold():
    pos = np.zeros(5)
    counts = step(pos, [-1.3, 1.3, -1.2, 1.2, -1.25], [10.0] * 5)
    assert pos.tolist() == [1.0, -1.0, 0.0, 0.0, 0.0]  # strict inequality at exactly -1.25
    assert counts == (2, 0)


def test_holds_outside_the_close_band_and_closes_inside():
    pos = np.array([1.0, -1.0, 1.0, -1.0, 1.0])
    counts = step(pos, [-0.8, 0.8, -0.3, 0.49, -0.5], [10.0] * 5)
    assert pos.tolist() == [1.0, -1.0, 0.0, 0.0, 1.0]  # |s| = 0.5 exactly is held
    assert counts == (0, 2)


def test_refuses_to_open_when_tau_too_long_or_score_not_finite():
    pos = np.zeros(5)
    counts = step(pos, [-2.0, 2.0, -2.0, np.nan, np.inf], [30.0, 45.0, np.inf, 10.0, 10.0])
    assert pos.tolist() == [0.0] * 5
    assert counts == (0, 0)


def test_non_finite_score_closes_an_open_position():
    pos = np.array([1.0, -1.0, 0.0])
    counts = step(pos, [np.nan, -np.inf, np.nan], [10.0, 10.0, 10.0])
    assert pos.tolist() == [0.0, 0.0, 0.0]
    assert counts == (0, 2)


def test_holding_ignores_tau_and_uses_a_symmetric_band():
    """Documented deviations 3 and 4 in rank_space.py."""
    pos = np.array([1.0, 1.0, -1.0])
    counts = step(pos, [-1.0, 2.0, -2.0], [100.0, 10.0, 10.0])
    assert pos.tolist() == [1.0, 1.0, -1.0]
    assert counts == (0, 0)


def test_position_path_over_several_days():
    pos = np.zeros(1)
    scores = [-0.2, -1.3, -0.9, -0.4, 1.4, 0.6, 0.1, np.nan, -1.5]
    path, opens, closes = [], 0, 0
    for s in scores:
        o, c = step(pos, [s], [10.0])
        opens, closes = opens + o, closes + c
        path.append(pos[0])
    assert path == [0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0, 0.0, 1.0]
    assert (opens, closes) == (3, 2)


# ---------------------------------------------------------------------------- weights
def test_paper_weights_are_phi_transpose_w_with_unit_l1_norm():
    rng = np.random.default_rng(13)
    X = factor_panel(rng, 252, 30)
    d = rs.market_decomposition(X, 60)
    pos = np.zeros(30)
    pos[[2, 7, 19]] = [1.0, -1.0, 1.0]
    w = rs.paper_weights(d.phi, pos)
    raw = pos - d.omega.T @ (d.beta.T @ pos)  # Phi^T w = w - omega^T (beta^T w)
    assert np.isclose(np.abs(w).sum(), 1.0, rtol=0.0, atol=1e-12)
    assert np.allclose(w, raw / np.abs(raw).sum(), rtol=0.0, atol=1e-15)


def test_paper_weights_are_zero_when_no_position_is_open():
    rng = np.random.default_rng(14)
    phi = rng.normal(size=(10, 10))
    w = rs.paper_weights(phi, np.zeros(10))
    assert w.shape == (10,) and not np.any(w)


def test_legs_are_position_times_leg_weight():
    rng = np.random.default_rng(15)
    d = rs.market_decomposition(factor_panel(rng, 252, 20), 60)
    pos = rng.choice([-1.0, 0.0, 1.0], size=20)
    legs, _ = rs.traded_weights(pos, d.beta, d.omega, 0.05, 0.5)
    assert np.array_equal(legs, pos * 0.05)


def test_hedge_offsets_the_aggregate_factor_exposure():
    rng = np.random.default_rng(16)
    d = rs.market_decomposition(factor_panel(rng, 252, 20), 60)
    checked = 0
    for _ in range(200):
        pos = rng.choice([-1.0, 0.0, 1.0], size=20)
        exposure = float(d.beta[:, 0] @ pos) * float(d.omega[0].sum()) * 0.05
        _, hedge = rs.traded_weights(pos, d.beta, d.omega, 0.05, 0.5)
        if exposure == 0.0:
            assert hedge == 0.0
            continue
        assert np.sign(hedge) == -np.sign(exposure)
        if abs(exposure) < 0.5:
            assert np.isclose(hedge, -exposure, rtol=1e-12, atol=0.0)
        checked += 1
    assert checked > 100


def test_hedge_is_clipped_at_max_hedge():
    n = 10
    omega = np.full((1, n), 1.0 / np.sqrt(n))
    beta = np.full((n, 1), 3.0)
    long_book = np.ones(n)
    _, hedge = rs.traded_weights(long_book, beta, omega, 0.05, 0.5)
    assert hedge == -0.5
    _, hedge = rs.traded_weights(-long_book, beta, omega, 0.05, 0.5)
    assert hedge == 0.5


def test_hedge_does_not_depend_on_the_eigenvector_sign():
    rng = np.random.default_rng(17)
    d = rs.market_decomposition(factor_panel(rng, 252, 20), 60)
    pos = rng.choice([-1.0, 0.0, 1.0], size=20)
    _, h1 = rs.traded_weights(pos, d.beta, d.omega, 0.05, 0.5)
    _, h2 = rs.traded_weights(pos, -d.beta, -d.omega, 0.05, 0.5)
    assert np.isclose(h1, h2, rtol=1e-12, atol=1e-15)


# ---------------------------------------------------------------------------- equivalence with the recorded runs
class RecordedV3:
    """State holder whose ``rank_weights`` is the code QuantConnect ran, pasted verbatim.

    Source: ``main.py`` of runs sa__v3_2011 and sa__v3_2018 (QuantConnect project 36836415),
    SHA-256 as run on QuantConnect 6b42cfb3baa3271e3c87e7a043ad9f4f331caae97dcddc9927a3583c67edd49b,
    method ``RankSpaceStatArb.rank_weights``. The published copy in results/raw/ differs from it
    only in one paragraph of the class docstring. Do not edit the method body.
    """

    def rank_weights(self):
        rf_daily = self.risk_free_interest_rate_model.get_interest_rate(self.time) / 252.0
        R = np.array(self.rank_returns)  # T x n, oldest first
        X = np.nan_to_num(R - rf_daily)

        # Algorithm 1: PCA on the factor window, loadings on the loading window.
        Xc = X - X.mean(axis=0)
        _, _, vt = np.linalg.svd(Xc, full_matrices=False)
        omega = vt[: self.k_factors]                     # K x n eigenvectors (unit norm)
        XL = X[-self.loading_window:]                    # L x n
        F = XL @ omega.T                                 # L x K factor returns
        A = np.column_stack([np.ones(len(XL)), F])
        coef, *_ = np.linalg.lstsq(A, XL, rcond=None)    # (K+1) x n
        beta = coef[1:].T                                # n x K loadings
        phi = np.eye(self.n) - beta @ omega              # n x n transformation matrix
        eps = XL @ phi.T                                 # L x n residual returns

        # Algorithm 2: cumulative residuals, OU fit by AR(1), s-scores.
        x = np.cumsum(eps, axis=0)
        x_prev, x_next = x[:-1], x[1:]
        mp, mn = x_prev.mean(axis=0), x_next.mean(axis=0)
        var = ((x_prev - mp) ** 2).sum(axis=0)
        cov = ((x_prev - mp) * (x_next - mn)).sum(axis=0)
        b = np.where(var > 0, cov / np.where(var > 0, var, 1.0), np.nan)
        a = mn - b * mp
        resid = x_next - (a + b * x_prev)
        var_e = resid.var(axis=0, ddof=2)
        valid = np.isfinite(b) & (b > 0) & (b < 1) & (var_e > 0)
        b_safe = np.where(valid, b, 0.5)
        tau = np.where(valid, -1.0 / np.log(b_safe), np.inf)
        mu = np.where(valid, a / (1.0 - b_safe), 0.0)
        sigma_eq = np.where(valid, np.sqrt(var_e / (1.0 - b_safe ** 2)), 1.0)
        s = np.where(valid, (x[-1] - mu) / sigma_eq, np.nan)

        pos = self.position
        for k in range(self.n):
            if not np.isfinite(s[k]):
                if pos[k] != 0:
                    self.closes += 1
                pos[k] = 0
                continue
            if pos[k] == 0:
                if tau[k] < self.max_tau:
                    if s[k] < -self.open_threshold:
                        pos[k] = 1
                        self.opens += 1
                    elif s[k] > self.open_threshold:
                        pos[k] = -1
                        self.opens += 1
            elif abs(s[k]) < self.close_threshold:
                pos[k] = 0
                self.closes += 1

        # The paper's weights (Phi^T w, L1-normalised), kept for the before-cost comparison.
        w_paper = phi.T @ pos
        l1 = np.abs(w_paper).sum()
        self.paper_weights = w_paper / l1 if l1 > 0 else np.zeros(self.n)

        # Traded weights: a fixed leg per open rank, one SPY hedge for the factor exposure.
        legs = pos * self.leg_weight
        factor_exposure = float(beta[:, 0] @ pos)
        hedge = float(np.clip(-factor_exposure * float(omega[0].sum()) * self.leg_weight,
                              -self.max_hedge, self.max_hedge))
        return legs, hedge


PROVENANCE = ROOT / "results" / "provenance" / "code_hashes.json"
# main.py of the recorded v3 runs, SHA-256 as run on QuantConnect.
V3_CODE_SHA256_AS_RUN = "6b42cfb3baa3271e3c87e7a043ad9f4f331caae97dcddc9927a3583c67edd49b"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _provenance():
    """Per export key and code file: {"as_run", "published", "names_removed"}."""
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))["hashes"] if PROVENANCE.exists() else None


def _recorded_export():
    """The raw QuantConnect export of run sa__v3_2018: results/raw/ first, then a local copy."""
    candidates = [ROOT / "results" / "raw" / "sa__v3_2018.json.gz"]
    folder = Path(os.environ.get("RANK_SPACE_QC_EXPORT", ROOT.parent / "_qc-export"))
    candidates.append(folder / "sa__v3_2018.json")
    return next((path for path in candidates if path.exists()), None)


@pytest.mark.skipif(_recorded_export() is None or _provenance() is None,
                    reason="raw QuantConnect export of run sa__v3_2018 or the provenance file not found")
def test_reference_is_a_verbatim_copy_of_the_recorded_code():
    path = _recorded_export()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        recorded = json.load(fh)["code"]["main.py"]
    entry = _provenance()["sa__v3_2018"]["main.py"]
    assert entry["as_run"] == V3_CODE_SHA256_AS_RUN
    assert _sha256(recorded) == entry["published"]
    assert inspect.getsource(RecordedV3.rank_weights) in recorded


class _RateModel:
    def __init__(self, annual_rates):
        self.annual_rates = annual_rates

    def get_interest_rate(self, time):
        return self.annual_rates[time]


@pytest.fixture(scope="module")
def qc_main():
    """main.py imported against a stub AlgorithmImports module."""
    stub = types.ModuleType("AlgorithmImports")
    for name in ("QCAlgorithm", "FeeModel", "OrderFeeParameters", "OrderFee", "CashAmount",
                 "Fundamental", "Symbol", "SecurityChanges", "Slice", "Resolution"):
        setattr(stub, name, type(name, (), {}))
    stub.List = typing.List
    stub.Optional = typing.Optional
    stub.timedelta = timedelta
    saved = sys.modules.get("AlgorithmImports")
    sys.modules["AlgorithmImports"] = stub
    try:
        spec = importlib.util.spec_from_file_location("qc_main_under_test", ROOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is None:
            del sys.modules["AlgorithmImports"]
        else:
            sys.modules["AlgorithmImports"] = saved
    return module


def _configure(algo, n, factor_window, loading_window, params, annual_rates):
    """Set exactly the attributes the recorded rank_weights() reads, as initialize() would."""
    algo.n = n
    algo.factor_window = factor_window
    algo.loading_window = loading_window
    algo.k_factors = 1
    algo.open_threshold = params["open_threshold"]
    algo.close_threshold = params["close_threshold"]
    algo.max_tau = params["max_tau"]
    algo.leg_weight = params["leg_weight"]
    algo.max_hedge = 0.5
    algo.rank_returns = deque(maxlen=factor_window)
    algo.position = np.zeros(n)
    algo.paper_weights = None
    algo.opens = 0
    algo.closes = 0
    algo.risk_free_interest_rate_model = _RateModel(annual_rates)
    algo.time = 0
    return algo


def _same(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return np.array_equal(a, b, equal_nan=True) and a.dtype == b.dtype and a.tobytes() == b.tobytes()


N_PANELS = 240


def test_refactor_reproduces_the_recorded_rank_weights(qc_main, record_property):
    """240 seeded panels, several days each: positions, weights, hedge and counters identical.

    Panel kinds (seed % 4): 0 Gaussian returns; 1 one factor plus mean-reverting residuals, so
    positions open and close; 2 as 1 with missing values; 3 as 1 with small windows, where after
    the first day some ranks (the open ones first) stop moving, so their fits become invalid and
    the non-finite branch closes them. n, the factor window and the loading window vary.
    """
    totals = {"days": 0, "opens": 0, "closes": 0, "nonfinite_closes": 0, "wide": 0}
    for seed in range(N_PANELS):
        rng = np.random.default_rng(20_260_925 + seed)
        kind = seed % 4
        n = int(rng.integers(3, 121))
        if kind == 3:
            loading_window = int(rng.integers(8, 21))
            factor_window = int(rng.integers(loading_window + 2, 81))
            days = loading_window + int(rng.integers(2, 6))
        else:
            loading_window = int(rng.integers(8, 81))
            factor_window = int(rng.integers(loading_window + 2, 301))
            days = int(rng.integers(2, 13))
        totals["wide"] += int(n > factor_window)
        params = {
            "open_threshold": float(rng.choice([1.25, 1.0, 1.5])),
            "close_threshold": float(rng.choice([0.5, 0.25, 0.75])),
            "max_tau": float(rng.choice([30.0, 15.0, 60.0])),
            "leg_weight": float(rng.choice([0.05, 0.02, 0.1])),
        }
        rows = factor_window + days - 1
        if kind == 3:
            annual_rates = [float(rng.uniform(0.0, 0.06))] * days
        else:
            annual_rates = [float(r) for r in rng.uniform(0.0, 0.06, days)]
        if kind == 0:
            panel = rng.normal(0.0, 0.01, (rows, n))
        else:
            panel = factor_panel(rng, rows, n, idio_scale=0.0) + ar1_increments(rng, rows, n)
        if kind == 2:
            panel[rng.random((rows, n)) < 0.01] = np.nan

        ref = _configure(RecordedV3(), n, factor_window, loading_window, params, annual_rates)
        new = _configure(qc_main.RankSpaceStatArb(), n, factor_window, loading_window, params, annual_rates)
        for t in range(factor_window):
            ref.rank_returns.append(panel[t])
            new.rank_returns.append(panel[t])

        stale = np.array([], dtype=int)
        for day in range(days):
            if day > 0:
                row = panel[factor_window + day - 1].copy()
                if stale.size:
                    # Excess return exactly zero: the recorded code subtracts rate / 252.0.
                    row[stale] = annual_rates[day] / 252.0
                ref.rank_returns.append(row)
                new.rank_returns.append(row)
            ref.time = new.time = day
            before = ref.position.copy()

            legs_ref, hedge_ref = ref.rank_weights()
            legs_new, hedge_new = new.rank_weights()

            where = f"seed {seed} day {day}"
            assert _same(ref.position, new.position), where
            assert _same(ref.paper_weights, new.paper_weights), where
            assert _same(legs_ref, legs_new), where
            assert _same(hedge_ref, hedge_new), where
            assert type(hedge_ref) is type(hedge_new) is float, where
            assert (ref.opens, ref.closes) == (new.opens, new.closes), where

            X = rs.excess_returns(ref.rank_returns, annual_rates[day] / 252.0)
            s = rs.fit_ou(rs.market_decomposition(X, loading_window).residuals).s_score
            totals["nonfinite_closes"] += int(np.sum((before != 0) & ~np.isfinite(s)))
            totals["days"] += 1
            if kind == 3 and day == 0:
                open_ranks = np.flatnonzero(ref.position)
                extra = rng.choice(n, size=min(2, n), replace=False)
                stale = np.unique(np.concatenate([open_ranks[:3], extra])).astype(int)
        totals["opens"] += ref.opens
        totals["closes"] += ref.closes

    # The comparison is only meaningful if every branch of the state machine was exercised.
    for key, value in totals.items():
        record_property(key, value)  # visible with --junitxml
    assert totals["opens"] > 100 and totals["closes"] > 50, totals
    assert totals["nonfinite_closes"] > 0, totals
    assert totals["wide"] > 0, totals


# ---------------------------------------------------------------------------- daily capitalisations (v4)
def test_daily_caps_first_observation_returns_the_reported_value():
    caps = rs.DailyCaps()
    assert caps.update("A", 100.0, 10.0) == 100.0
    assert len(caps) == 1


def test_daily_caps_roll_forward_with_the_adjusted_price_between_reports():
    caps = rs.DailyCaps()
    caps.update("A", 100.0, 10.0)
    assert caps.update("A", 100.0, 11.0) == pytest.approx(110.0, rel=1e-15)
    assert caps.update("A", 100.0, 9.5) == pytest.approx(95.0, rel=1e-15)


def test_daily_caps_reanchor_when_the_reported_value_changes():
    caps = rs.DailyCaps()
    caps.update("A", 100.0, 10.0)
    caps.update("A", 100.0, 12.0)
    assert caps.update("A", 118.0, 12.0) == 118.0          # new month-end snapshot wins
    assert caps.update("A", 118.0, 13.0) == pytest.approx(118.0 * 13.0 / 12.0, rel=1e-15)


def test_daily_caps_keep_companies_apart_and_ignore_non_positive_prices():
    caps = rs.DailyCaps()
    caps.update("A", 100.0, 10.0)
    caps.update("B", 50.0, 5.0)
    assert caps.update("A", 100.0, 20.0) == pytest.approx(200.0)
    assert caps.update("B", 50.0, 0.0) == 50.0            # cannot roll: reported value, anchor kept
    assert caps.update("B", 50.0, 6.0) == pytest.approx(60.0)


class _F:
    """Minimal stand-in for a QuantConnect Fundamental object in select()."""

    def __init__(self, symbol, market_cap, adjusted_price, price=10.0, has=True, primary=True):
        self.symbol = symbol
        self.market_cap = market_cap
        self.adjusted_price = adjusted_price
        self.price = price
        self.has_fundamental_data = has
        self.security_reference = types.SimpleNamespace(is_primary_share=primary)


def _selector(qc_main, cap_source, n=3, buffer=1):
    algo = qc_main.RankSpaceStatArb()
    algo.n, algo.buffer, algo.cap_source = n, buffer, cap_source
    algo.daily_caps = rs.DailyCaps()
    algo.caps_today = {}
    return algo


def _recorded_select(fundamental, n, buffer):
    """select() of the recorded runs v1 to v3 (SHA-256 6b42cfb3... as run on QuantConnect), pasted verbatim."""
    candidates = [
        f for f in fundamental
        if f.has_fundamental_data and f.market_cap > 0 and f.price > 1
        and f.security_reference.is_primary_share
    ]
    candidates.sort(key=lambda f: f.market_cap, reverse=True)
    return [f.symbol for f in candidates[: n + buffer]]


def test_select_reported_matches_the_recorded_select(qc_main):
    rng = np.random.default_rng(4)
    for trial in range(300):
        size = int(rng.integers(1, 40))
        universe = [
            _F(f"S{i}", float(rng.choice([0.0, rng.uniform(1, 100), 50.0])), float(rng.uniform(1, 50)),
               price=float(rng.choice([0.5, 5.0, 20.0])), has=bool(rng.random() > 0.1),
               primary=bool(rng.random() > 0.1))
            for i in range(size)
        ]
        algo = _selector(qc_main, "reported", n=int(rng.integers(1, 10)), buffer=int(rng.integers(0, 5)))
        assert algo.select(universe) == _recorded_select(universe, algo.n, algo.buffer), trial


def test_select_rolled_ranks_on_the_daily_cap(qc_main):
    algo = _selector(qc_main, "rolled", n=1, buffer=1)
    # Day 1: reported caps put A first.
    day1 = [_F("A", 100.0, 10.0), _F("B", 90.0, 10.0), _F("C", 10.0, 10.0)]
    assert algo.select(day1) == ["A", "B"]
    # Day 2: same monthly snapshot, but B's price rose 20% and A's fell 10%: B now leads.
    day2 = [_F("A", 100.0, 9.0), _F("B", 90.0, 12.0), _F("C", 10.0, 10.0)]
    assert algo.select(day2) == ["B", "A"]
    assert algo.caps_today == {"B": pytest.approx(108.0), "A": pytest.approx(90.0)}
    # The reported field alone would have kept A first on day 2.
    reported = _selector(qc_main, "reported", n=1, buffer=1)
    assert reported.select(day2) == ["A", "B"]


# ---------------------------------------------------------------------------- consistency
def test_config_json_parameters_match_main_py_defaults():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    defaults = dict(re.findall(r'get_parameter\("(\w+)", ([0-9.]+)\)', source))
    text_defaults = dict(re.findall(r'get_parameter\("(\w+)", "(\w+)"\)', source))
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert set(config["parameters"]) == set(defaults) | set(text_defaults)
    for name, value in defaults.items():
        assert float(config["parameters"][name]) == float(value), name
    for name, value in text_defaults.items():
        assert config["parameters"][name] == value, name


# The code of the eight v4 backtests (identical in every v4 export), SHA-256 as run on QuantConnect.
V4_CODE_SHA256_AS_RUN = {
    "main.py": "15789ef3b315f11a5f05caa0e1480b85a222a5f5dc1bf5039205fd301a94b0d5",
    "rank_space.py": "024d3f7c23c4d998d411828cba5852ca3b424f57a467037b6b743f1244aa75b6",
}
RAW = ROOT / "results" / "raw"
V4_KEYS = ("sa__v4_2011", "sa__v4_2013", "sa__v4_2015", "sa__v4_2017", "sa__v4_2018", "sa__v4_2020",
           "sa__v4_2022", "sa__v4_2024")


def _v4_export():
    path = RAW / "sa__v4_2018.json.gz"
    return path if path.exists() else None


def _raw_code(key):
    """The code files stored with an export in results/raw/, as {name: text}."""
    with gzip.open(RAW / f"{key}.json.gz", "rt", encoding="utf-8") as fh:
        document = json.load(fh)
    return document.get("code") if isinstance(document, dict) else None


def _syntax_without_docstrings(source: str) -> str:
    """The module's syntax tree with every module, class and function docstring removed.

    Comments never reach the tree, so two sources with the same result differ only in
    docstrings and comments.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


@pytest.mark.skipif(_v4_export() is None or _provenance() is None,
                    reason="raw QuantConnect export of run sa__v4_2018 or the provenance file not found")
@pytest.mark.parametrize("name", sorted(V4_CODE_SHA256_AS_RUN))
def test_repository_code_is_the_v4_code_apart_from_docstrings_and_comments(name):
    published = _raw_code("sa__v4_2018")[name]
    entry = _provenance()["sa__v4_2018"][name]
    assert entry["as_run"] == V4_CODE_SHA256_AS_RUN[name]
    assert _sha256(published) == entry["published"]
    here = (ROOT / name).read_text(encoding="utf-8")
    assert _syntax_without_docstrings(here) == _syntax_without_docstrings(published)


@pytest.mark.skipif(_v4_export() is None or _provenance() is None,
                    reason="raw QuantConnect exports of the v4 runs or the provenance file not found")
def test_every_v4_window_ran_the_same_code():
    provenance = _provenance()
    first = _raw_code(V4_KEYS[0])
    for key in V4_KEYS:
        code = _raw_code(key)
        assert code == first, key
        for name, as_run in V4_CODE_SHA256_AS_RUN.items():
            assert provenance[key][name]["as_run"] == as_run, (key, name)


@pytest.mark.skipif(_provenance() is None, reason="results/provenance/code_hashes.json not found")
def test_provenance_hashes_match_the_published_code():
    """Every export with code has an entry per code file, and its published hash is that file's hash."""
    provenance = _provenance()
    with_code = {}
    for path in sorted(RAW.glob("*.json.gz")):
        code = _raw_code(path.name[: -len(".json.gz")])
        if isinstance(code, dict):
            with_code[path.name[: -len(".json.gz")]] = code
    assert set(provenance) == set(with_code)
    redacted = 0
    for key, code in with_code.items():
        assert set(provenance[key]) == set(code), key
        for name, text in code.items():
            entry = provenance[key][name]
            assert entry["published"] == _sha256(text), (key, name)
            assert re.fullmatch(r"[0-9a-f]{64}", entry["as_run"]), (key, name)
            assert entry["names_removed"] == (entry["as_run"] != entry["published"]), (key, name)
            redacted += entry["names_removed"]
    # Only main.py was redacted, and rank_space.py and the notebooks are as run.
    assert all(not entry["names_removed"] for files in provenance.values()
               for name, entry in files.items() if name != "main.py")
    assert redacted > 0


@pytest.mark.skipif(_provenance() is None, reason="results/provenance/code_hashes.json not found")
def test_runs_csv_hashes_come_from_the_provenance_file_and_the_raw_code():
    provenance = _provenance()
    with (ROOT / "results" / "runs.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for row in rows:
        code = _raw_code(row["key"])
        for column, name in (("code_sha256", "main.py"), ("rank_space_sha256", "rank_space.py")):
            if name in code:
                assert row[f"{column}_as_run"] == provenance[row["key"]][name]["as_run"], (row["key"], name)
                assert row[f"{column}_published"] == _sha256(code[name]), (row["key"], name)
            else:
                assert row[f"{column}_as_run"] == row[f"{column}_published"] == "", (row["key"], name)
    v3 = [row for row in rows if row["version"] == "v3"]
    assert v3 and all(row["code_sha256_as_run"] == V3_CODE_SHA256_AS_RUN for row in v3)


@pytest.mark.skipif(_provenance() is None, reason="results/provenance/code_hashes.json not found")
def test_code_copies_under_results_are_the_published_code():
    """results/**/code/main.py of a run folder is byte for byte the main.py of that run's raw export."""
    folders = {
        "superseded/v1_2010_2024": "sa__v1", "superseded/v2_2018_2024": "sa__v2",
        "superseded/v3_2011_2017": "sa__v3_2011", "superseded/v3_2018_2024": "sa__v3_2018",
        "reference/spy_2015_2019": "audit__spy_2015_2019",
    }
    for folder, key in folders.items():
        copy = (ROOT / "results" / folder / "code" / "main.py").read_bytes().replace(b"\r\n", b"\n")
        assert copy == _raw_code(key)["main.py"].encode("utf-8"), folder
