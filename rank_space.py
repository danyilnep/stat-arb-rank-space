"""Rank-space statistical arbitrage: the mathematics, with no QuantConnect dependency.

This module holds the numerical core of the parametric strategy in Y.-F. Li and
G. Papanicolaou, "Statistical Arbitrage in Rank Space", arXiv:2410.06568v1 (Stanford, October
2024). Equation, section and appendix numbers refer to that version; v2 (June 2026) renumbers
them. It depends on numpy only. ``main.RankSpaceStatArb.rank_weights`` calls these functions once per
trading day, and ``tests/test_rank_space.py`` checks their mathematical properties and that
they reproduce the inline code of the recorded QuantConnect runs bit for bit.

Notation: n ranks (100 here, 500 in the paper), a factor window of T = 252 days, a loading
window of L = 60 days and K = 1 factor. ``X`` is the T x n matrix of rank-space excess returns,
oldest row first. A "position" is the residual-space position w^eps per rank, in {-1, 0, +1}.

Map to the paper
----------------
======================  ======================================================================
Function                Paper
======================  ======================================================================
DailyCaps               Not in the paper, which reads daily capitalisations from CRSP. Turns
                        QuantConnect's monthly Morningstar market cap into a daily one.
rank_space_returns      Section 2.1.2, Eq. 2.1.9: the return of rank k is the change in the
                        capitalisation held at rank k, whichever company holds it on each day.
excess_returns          Eq. 2.1.10: rank returns in excess of the risk-free rate.
market_decomposition    Algorithm 1 (Section 2.1): leading principal component as the factor,
                        loadings by regression on the factor, transformation matrix
                        Phi = I - beta omega (Eq. 2.1.12, the rank-space form of Eq. 2.1.4),
                        residuals eps = Phi (r - r_f) (Eq. 2.1.11; Eq. 2.1.3 in name space).
fit_ou                  Algorithm 2, first two lines (Section 2.2.1): cumulative residuals over
                        the window (Eq. 2.2.1, in rank space Eq. 2.2.3; Eq. 2.2.2 is the
                        name-space form), an Ornstein-Uhlenbeck fit
                        dX = (mu - X) dt / tau + sigma dB (Eq. 2.2.4), the s-score
                        s = (x - mu) / sigma (Eq. 2.2.5).
update_positions        Algorithm 2, third line: the open, hold and close rule of Eq. 2.2.7,
                        with the thresholds of Eq. 2.2.8 (open 1.25, close 0.5) and the
                        filter tau < 30 days.
paper_weights           Algorithm 2, last two lines: equity weights w^R = Phi^T w^eps
                        (Eq. 2.2.10 in rank space; Eq. 2.2.9 is the name-space form),
                        L1-normalised.
traded_weights          Not in the paper. The book this implementation actually holds on
                        names; the paper's own rank-to-name step is Section 2.3.
======================  ======================================================================

Deviations from the paper, with reasons
---------------------------------------
1. The weights traded are not the paper's. ``paper_weights`` computes Phi^T w, which puts a
   piece of the market hedge on every rank and resizes every leg whenever any position opens
   or closes. Traded on names (run v1, which ranked on the monthly market-cap field), that
   dense book reached QuantConnect's 10,000-order limit on 16 August 2013, 3.6 years after
   trading began on 4 January 2010: about 11 orders per trading day, sent on 566 dates, with a
   median of 6.5 orders on those dates and 90 or more on 22 of them
   (``results/superseded/v1_2010_2024/orders.csv``). How often it would trade on daily
   capitalisations was not measured. ``traded_weights`` instead holds a fixed leg per open
   rank and one SPY position carrying the same aggregate factor exposure, so that an order
   goes out only for an open, a close, a rank changing hands or a drift past a band. The
   paper's weights are still computed every day and their before-cost rank-space P&L is
   recorded next to the realised equity, so the signal can be judged apart from the book.
2. The OU parameters come from an AR(1) least-squares regression of the cumulative residuals,
   the estimation procedure of the paper's Appendix 5.2 (after Avellaneda and Lee 2010); the
   paper's Section 2.2.1 calls the resulting estimates maximum likelihood, and with Gaussian
   innovations the least-squares a and b are the conditional maximum-likelihood estimates. The
   residual variance uses ddof=2 (unbiased for two fitted parameters) where the conditional
   maximum-likelihood estimate divides by the number of pairs; with L = 60 (59 pairs) this
   makes sigma about 1.7% larger (sqrt(59/57)) and every s-score about 1.7% smaller in
   magnitude. Kept because the recorded runs used it. The sigma of the s-score is the
   equilibrium standard deviation sqrt(var(e) / (1 - b^2)), the right-hand block of the paper's
   Eq. 5.2.2, as in Avellaneda and Lee. That equation's left-hand block, Var(xi) =
   sigma^2 (1 - exp(-2 kappa dt)) / (2 kappa), instead makes sigma the diffusion coefficient of
   Eq. 2.2.4, larger than the equilibrium standard deviation by a factor sqrt(2 kappa) (kappa per
   year). The paper does not resolve the two; the choice sets the scale of every s-score
   against the 1.25 and 0.5 thresholds.
3. The tau < 30 days filter gates opening only. Eq. 2.2.7 also attaches it to the two holding
   cases, so in the paper a held position closes when its fitted tau rises above 30 days.
   Here a held position closes only inside the close band or when its fit becomes invalid.
   Kept because the recorded runs used this rule.
4. The holding rule is a symmetric band: a position is kept while |s| >= c_close and closed
   once |s| < c_close. A long whose score jumps in one day from below -1.25 to above +0.5 is
   kept, where the Avellaneda and Lee rule (close a long once s > -c_close) would close it.
   Kept because the recorded runs used it.
5. Invalid fits. When the AR(1) coefficient b is not in (0, 1), or the fit leaves no residual
   variance, no OU process with a finite positive tau exists; the s-score is set to NaN, no
   position opens on that rank and an open one is closed. The paper does not say what to do.
6. The loadings regression has an intercept, and the residuals eps = Phi X keep it, exactly as
   Algorithm 1 defines eps (Phi carries no intercept). Each rank's cumulative residual
   therefore drifts by its intercept per day, and the OU fit's own intercept absorbs it.
7. The risk-free rate is today's annual rate divided by 252, subtracted from every row of the
   window rather than each day's own rate. Missing returns are set to zero by np.nan_to_num;
   with positive capitalisations this does not arise in practice.
8. The AR(1) fit uses the L - 1 = 59 consecutive pairs of the 60-point cumulative path. The
   paper's Eq. 5.2.1 as printed regresses over alpha = 1..L, L pairs, the first of which starts
   from x_{t-L} = 0 (the empty sum of Eq. 2.2.2); that pair, (0, eps_{t-L+1}), is left out here.
9. The PCA is the SVD of the column-demeaned X, i.e. the eigenvectors of the sample covariance of
   the excess returns. Algorithm 1 and the paper's Eq. 5.1.1 decompose the excess returns
   themselves, uncentred. The effect of centring on the leading vector was not measured; the
   regression intercept (deviation 6) still absorbs each rank's mean in the loadings.

Choices where Algorithm 1 leaves room: no scaling by each rank's volatility before the PCA;
omega is the unit-norm leading eigenvector, so the factor return F = X omega^T satisfies
Algorithm 1's line "solve F_t = omega_t (r_t - r_f)" by construction (the paper's Eq. 5.1.2
scales it by 1 / sigma_1 instead, which leaves beta omega and Phi unchanged). Deviations of
data and execution (100 ranks, Morningstar capitalisations, daily rebalancing, order
thresholds) are listed in ``main.py``.

Behaviour contract: every function performs the numpy calls of the recorded ``main.py``
(SHA-256 6b42cfb3... as run on QuantConnect) in the same order with the same arguments. ``DailyCaps``, added for v4,
has no counterpart in that code. Do not "tidy" an expression here without re-running the
equivalence test; a reordered floating-point sum changes the positions and therefore the
published results.
"""

from typing import NamedTuple

import numpy as np

__all__ = [
    "DailyCaps",
    "Decomposition",
    "OUFit",
    "excess_returns",
    "fit_ou",
    "market_decomposition",
    "paper_weights",
    "rank_space_returns",
    "traded_weights",
    "update_positions",
]


class Decomposition(NamedTuple):
    """Output of Algorithm 1 for one day."""

    omega: np.ndarray           # K x n, leading eigenvector(s) of the factor window, unit norm
    factor_returns: np.ndarray  # L x K, F = X_L omega^T on the loading window
    alpha: np.ndarray           # n, regression intercepts (used only to estimate beta)
    beta: np.ndarray            # n x K, loadings of each rank on the factor
    phi: np.ndarray             # n x n, transformation matrix Phi = I - beta omega
    residuals: np.ndarray       # L x n, eps_t = Phi X_t for each day of the loading window


class OUFit(NamedTuple):
    """Output of the Ornstein-Uhlenbeck fit of Algorithm 2 for one day, one entry per rank."""

    x: np.ndarray         # L x n, cumulative residuals x_{t-L+a} = sum_{j<=a} eps_{t-L+j}
    a: np.ndarray         # AR(1) intercept
    b: np.ndarray         # AR(1) slope, NaN when the lagged path has no variance
    valid: np.ndarray     # bool: 0 < b < 1 and positive residual variance
    tau: np.ndarray       # mean-reversion time in trading days, inf when not valid
    mu: np.ndarray        # long-run mean of x, 0 when not valid
    sigma_eq: np.ndarray  # equilibrium standard deviation of x, 1 when not valid
    s_score: np.ndarray   # (x_T - mu) / sigma_eq, NaN when not valid


class DailyCaps:
    """Daily point-in-time capitalisations rolled forward from a monthly market-cap field.

    QuantConnect's Morningstar ``Fundamental.market_cap`` is a month-end snapshot: it holds one
    value, the previous month-end close times the shares then outstanding, for a whole month and
    changes on the first trading day of the next month (checked on QuantConnect, see
    ``docs/data-checks.md``). Rank-space returns need a capitalisation that moves every day, and
    ``company_profile.shares_outstanding`` cannot be used instead because it is restated for
    later splits. This class anchors each company at its last reported value and rolls it
    forward with the split- and dividend-adjusted price:

        c_t = C_anchor * P_t / P_anchor

    re-anchoring whenever the reported value changes. The ratio of two adjusted prices is the
    total return between the two dates, so splits cancel, and a dividend counts as return until
    the next month-end snapshot resets the level. Share-count changes inside a month are missed
    until that reset; in the check (AAPL, MSFT and XOM, January 2019, no dividend in between)
    the rolled-forward value landed within 0.06% to 0.31% of the next reported snapshot. Keys
    are any hashable identifier (QuantConnect ``Symbol`` objects in ``main.py``).
    """

    def __init__(self) -> None:
        self._anchors: dict = {}

    def update(self, key, reported_cap: float, adjusted_price: float) -> float:
        """Record today's reported cap and adjusted price for ``key``; return today's cap.

        On the first observation, or when the reported value differs from the anchored one,
        the company is re-anchored and the reported value is returned unchanged. Otherwise the
        anchored value is scaled by the adjusted-price ratio since the anchor day. A
        non-positive adjusted price cannot be rolled forward, so the reported value is returned
        and the anchor is left as it was.
        """
        if adjusted_price <= 0:
            return reported_cap
        anchor = self._anchors.get(key)
        if anchor is None or anchor[0] != reported_cap:
            self._anchors[key] = (reported_cap, adjusted_price)
            return reported_cap
        return anchor[0] * adjusted_price / anchor[1]

    def __len__(self) -> int:
        return len(self._anchors)


def rank_space_returns(caps: np.ndarray, prev_caps: np.ndarray) -> np.ndarray:
    """Rank-space return per rank (Eq. 2.1.9).

    r_(k),t = c_(k),t / c_(k),t-1 - 1, where c_(k),t is the capitalisation at rank k on day t.
    Both arrays are sorted by rank, so the company behind rank k may differ between the two
    days; that is the point of rank space.
    """
    return caps / prev_caps - 1.0


def excess_returns(rank_returns, rf_daily) -> np.ndarray:
    """T x n matrix of rank-space excess returns, oldest row first (Eq. 2.1.10).

    X = nan_to_num(R - r_f), with R stacked from ``rank_returns`` (a sequence of length-n
    arrays) and ``rf_daily`` a scalar daily rate applied to every row (deviation 7).
    """
    R = np.array(rank_returns)  # T x n, oldest first
    return np.nan_to_num(R - rf_daily)


def market_decomposition(X: np.ndarray, loading_window: int, k_factors: int = 1) -> Decomposition:
    """Algorithm 1: split rank-space excess returns into a factor part and residuals.

    1. PCA on the whole factor window: Xc = X - mean(X) = U S V^T; omega = first K rows of V^T.
       The paper's SVD is of X itself, uncentred (module docstring, deviation 9).
    2. Factor returns on the loading window X_L (the last ``loading_window`` rows): F = X_L omega^T.
    3. Loadings by least squares with an intercept, per rank i: X_L[:, i] = alpha_i + F beta_i + u_i.
    4. Phi = I - beta omega (Eq. 2.1.12).
    5. Residuals eps_t = Phi X_t for every day of the loading window (Eq. 2.1.11), stacked as
       X_L Phi^T. Row by row, eps_t = X_t - beta (omega . X_t): the return minus the loading
       times that day's factor return, with no intercept removed.

    The window lengths (252 days for the PCA, 60 for the loadings) are the paper's Section 3.1
    settings; both fits are redone every day.
    """
    # PCA via SVD of the demeaned window; full_matrices=False keeps it T x n sized.
    Xc = X - X.mean(axis=0)
    _, _, vt = np.linalg.svd(Xc, full_matrices=False)
    omega = vt[:k_factors]                           # K x n eigenvectors (unit norm)
    XL = X[-loading_window:]                         # L x n
    F = XL @ omega.T                                 # L x K factor returns
    # Intercept column first, so coef[0] is alpha and coef[1:] are the loadings.
    A = np.column_stack([np.ones(len(XL)), F])
    coef, *_ = np.linalg.lstsq(A, XL, rcond=None)    # (K+1) x n
    beta = coef[1:].T                                # n x K loadings
    phi = np.eye(X.shape[1]) - beta @ omega          # n x n transformation matrix
    eps = XL @ phi.T                                 # L x n residual returns
    return Decomposition(omega=omega, factor_returns=F, alpha=coef[0], beta=beta, phi=phi,
                         residuals=eps)


def fit_ou(residuals: np.ndarray) -> OUFit:
    """Algorithm 2, first half: OU fit of each rank's cumulative residual and its s-score.

    Cumulative residuals (Eq. 2.2.3, the rank-space form of Eq. 2.2.2): x_a = eps_1 + ... + eps_a
    for a = 1..L.

    The OU process dX = (mu - X) dt / tau + sigma dB (Eq. 2.2.4), sampled daily, is the AR(1)
    x_{a+1} = a + b x_a + e with b = exp(-1/tau). Per rank, by least squares on the L - 1 pairs
    (deviation 8; Eq. 5.2.1 as printed has L):

        b        = cov(x_a, x_{a+1}) / var(x_a)
        a        = mean(x_{a+1}) - b mean(x_a)
        tau      = -1 / ln(b)                      (trading days)
        mu       = a / (1 - b)
        sigma_eq = sqrt(var(e) / (1 - b^2))        (stationary standard deviation of x; the
                                                    right-hand block of Eq. 5.2.2, deviation 2)
        s        = (x_L - mu) / sigma_eq           (Eq. 2.2.5)

    var(e) uses ddof=2 (deviation 2). A rank is valid only when 0 < b < 1 and var(e) > 0;
    otherwise tau = inf and s = NaN (deviation 5). The np.where guards keep log, division and
    sqrt away from invalid entries, so no runtime warning is raised for them.
    """
    x = np.cumsum(residuals, axis=0)
    x_prev, x_next = x[:-1], x[1:]
    mp, mn = x_prev.mean(axis=0), x_next.mean(axis=0)
    var = ((x_prev - mp) ** 2).sum(axis=0)
    cov = ((x_prev - mp) * (x_next - mn)).sum(axis=0)
    b = np.where(var > 0, cov / np.where(var > 0, var, 1.0), np.nan)
    a = mn - b * mp
    resid = x_next - (a + b * x_prev)
    var_e = resid.var(axis=0, ddof=2)
    valid = np.isfinite(b) & (b > 0) & (b < 1) & (var_e > 0)
    # 0.5 is a harmless placeholder for invalid ranks; their results are masked below.
    b_safe = np.where(valid, b, 0.5)
    tau = np.where(valid, -1.0 / np.log(b_safe), np.inf)
    mu = np.where(valid, a / (1.0 - b_safe), 0.0)
    sigma_eq = np.where(valid, np.sqrt(var_e / (1.0 - b_safe ** 2)), 1.0)
    s = np.where(valid, (x[-1] - mu) / sigma_eq, np.nan)
    return OUFit(x=x, a=a, b=b, valid=valid, tau=tau, mu=mu, sigma_eq=sigma_eq, s_score=s)


def update_positions(position: np.ndarray, s_score: np.ndarray, tau: np.ndarray,
                     open_threshold: float, close_threshold: float, max_tau: float) -> tuple[int, int]:
    """Algorithm 2, Eq. 2.2.7: advance each rank's residual position by one day, in place.

    Per rank k, with the previous position w in {-1, 0, +1}:

    * s not finite (the fit is invalid): w = 0; closing an open position counts as a close.
    * w = 0 and tau < max_tau: open long (+1) if s < -open_threshold, short (-1) if
      s > +open_threshold. Buy the residual when it is cheap, sell it when it is rich.
    * w != 0: close (w = 0) when |s| < close_threshold, otherwise hold. tau is not checked
      while holding (deviation 3) and the band is symmetric (deviation 4).

    ``position`` is modified in place, as ``main.py`` keeps it as algorithm state between days.
    Returns (opens, closes) made today.
    """
    opens = 0
    closes = 0
    pos = position
    for k in range(len(pos)):
        if not np.isfinite(s_score[k]):
            if pos[k] != 0:
                closes += 1
            pos[k] = 0
            continue
        if pos[k] == 0:
            if tau[k] < max_tau:
                if s_score[k] < -open_threshold:
                    pos[k] = 1
                    opens += 1
                elif s_score[k] > open_threshold:
                    pos[k] = -1
                    opens += 1
        elif abs(s_score[k]) < close_threshold:
            pos[k] = 0
            closes += 1
    return opens, closes


def paper_weights(phi: np.ndarray, position: np.ndarray) -> np.ndarray:
    """The paper's equity weights in rank space: Phi^T w^eps / ||Phi^T w^eps||_1 (Eq. 2.2.10).

    Phi^T w = w - omega^T (beta^T w): the residual legs plus a factor hedge spread over every
    rank in proportion to omega. Zero weights when no position is open. Used here only to
    measure the before-cost rank-space P&L of the paper's portfolio (deviation 1).
    """
    w_paper = phi.T @ position
    l1 = np.abs(w_paper).sum()
    return w_paper / l1 if l1 > 0 else np.zeros(len(position))


def traded_weights(position: np.ndarray, beta: np.ndarray, omega: np.ndarray,
                   leg_weight: float, max_hedge: float) -> tuple[np.ndarray, float]:
    """The book this implementation trades: fixed legs plus one SPY hedge (deviation 1).

    legs_k = w_k * leg_weight, a fixed fraction of equity per open rank.

    The factor part of Phi^T w is -omega^T (beta . w): (beta . w) units of the eigenportfolio
    omega, short, whose dollar weight is sum(omega). With legs scaled by leg_weight the hedge
    is therefore

        hedge = clip(-(beta . w) * sum(omega) * leg_weight, -max_hedge, +max_hedge)

    held in SPY, which stands in for the eigenportfolio dollar for dollar. The product
    (beta . w) * sum(omega) does not depend on the sign SVD gives omega, because beta flips
    with it. The clip caps the hedge at ``max_hedge`` of equity.
    """
    legs = position * leg_weight
    factor_exposure = float(beta[:, 0] @ position)
    hedge = float(np.clip(-factor_exposure * float(omega[0].sum()) * leg_weight,
                          -max_hedge, max_hedge))
    return legs, hedge
