# region imports
from AlgorithmImports import *
import numpy as np
from collections import deque
# endregion


class BasisPointFeeModel(FeeModel):
    """Proportional transaction cost, as in the paper (default 2 basis points)."""

    def __init__(self, basis_points: float) -> None:
        super().__init__()
        self.rate = basis_points / 10_000.0

    def get_order_fee(self, parameters: OrderFeeParameters) -> OrderFee:
        value = parameters.security.price * abs(parameters.order.quantity)
        return OrderFee(CashAmount(value * self.rate, "USD"))


class RankSpaceStatArb(QCAlgorithm):
    """Statistical arbitrage in rank space, Algorithms 1 and 2 of
    Li and Papanicolaou, "Statistical Arbitrage in Rank Space" (arXiv 2410.06568).

    Each day the largest `n_ranks` US stocks by market capitalisation are
    ranked, and returns are computed in rank space: the return of rank k is the
    change in the capitalisation held at rank k, whichever company that is.
    Algorithm 1 removes one PCA market factor (252-day window for the factor,
    60-day window for the loadings, refitted daily) and leaves residual returns
    per rank. Algorithm 2 accumulates the residuals over the 60-day window, fits
    an Ornstein-Uhlenbeck process to each rank's path, and opens a residual
    position when the s-score crosses 1.25 (closing at 0.5) for ranks whose
    mean-reversion time is under 30 days. Residual positions are mapped to
    equity weights with the transformation matrix, L1-normalised, and traded on
    the companies holding those ranks that day.

    Deviations from the paper, all documented in the README: daily rather than
    225-minute rebalancing between rank and name space (the paper's latency
    cost is therefore paid in full), a smaller default universe (100 ranks
    instead of 500, for the free backtest node), and QuantConnect's point-in-
    time Morningstar market capitalisations in place of CRSP.

    Origin: a 2024 Mercury Capital Management quant-team project
    that attempted the same paper with a CNN and
    minute data inside QuantConnect's free research node.
    """

    def initialize(self) -> None:
        self.set_start_date(2010, 1, 1)
        self.set_end_date(2024, 12, 31)
        self.set_cash(1_000_000)

        # Paper parameters.
        self.n = int(self.get_parameter("n_ranks", 100))
        self.factor_window = int(self.get_parameter("factor_window", 252))
        self.loading_window = int(self.get_parameter("loading_window", 60))
        self.k_factors = int(self.get_parameter("k_factors", 1))
        self.open_threshold = float(self.get_parameter("open_threshold", 1.25))
        self.close_threshold = float(self.get_parameter("close_threshold", 0.5))
        self.max_tau = float(self.get_parameter("max_tau_days", 30))
        self.fee_bps = float(self.get_parameter("fee_bps", 2))
        self.gross_leverage = float(self.get_parameter("gross_leverage", 1.0))
        self.buffer = 30  # extra names subscribed so rank switches at the boundary are covered

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)
        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self.select)
        self.settings.minimum_order_margin_portfolio_percentage = 0.002

        self.members: set = set()
        self.prev_caps: Optional[np.ndarray] = None
        self.rank_returns: deque = deque(maxlen=self.factor_window)
        self.position = np.zeros(self.n)  # residual-space position per rank, in {-1, 0, 1}
        self.last_day = None
        self.days_traded = 0

        self.set_warm_up(timedelta(days=int(self.factor_window * 1.6)))

    # ------------------------------------------------------------------ universe
    def select(self, fundamental: List[Fundamental]) -> List[Symbol]:
        candidates = [
            f for f in fundamental
            if f.has_fundamental_data and f.market_cap > 0 and f.price > 1
            and f.security_reference.is_primary_share
        ]
        candidates.sort(key=lambda f: f.market_cap, reverse=True)
        return [f.symbol for f in candidates[: self.n + self.buffer]]

    def on_securities_changed(self, changes: SecurityChanges) -> None:
        for security in changes.added_securities:
            if security.symbol == self.spy:
                continue
            security.set_fee_model(BasisPointFeeModel(self.fee_bps))
            self.members.add(security.symbol)
        for security in changes.removed_securities:
            self.members.discard(security.symbol)
            if security.invested:
                self.liquidate(security.symbol, tag="left universe")

    # ------------------------------------------------------------------ daily step
    def on_data(self, data: Slice) -> None:
        today = self.time.date()
        if today == self.last_day:
            return
        self.last_day = today

        ranked = self.ranked_caps()
        if ranked is None:
            return
        symbols, caps = ranked

        if self.prev_caps is not None:
            self.rank_returns.append(caps / self.prev_caps - 1.0)
        self.prev_caps = caps

        if self.is_warming_up or len(self.rank_returns) < self.factor_window:
            return

        weights = self.rank_weights()
        targets = {}
        for k, symbol in enumerate(symbols):
            if abs(weights[k]) > 0:
                targets[symbol] = targets.get(symbol, 0.0) + float(weights[k])
        portfolio_targets = [PortfolioTarget(s, w) for s, w in targets.items()]
        self.set_holdings(portfolio_targets, liquidate_existing_holdings=True)
        self.days_traded += 1
        if self.days_traded % 63 == 0:
            self.log(f"{today} open ranks {int(np.count_nonzero(self.position))} "
                     f"gross {sum(abs(w) for w in targets.values()):.2f}")

    def ranked_caps(self):
        """Symbols and capitalisations at ranks 1..n from today's point-in-time data."""
        rows = []
        for symbol in self.members:
            security = self.securities[symbol]
            f = security.fundamentals
            if f is None or not security.has_data:
                continue
            cap = f.market_cap
            if cap is None or cap <= 0:
                continue
            rows.append((float(cap), symbol))
        if len(rows) < self.n:
            return None
        rows.sort(key=lambda r: r[0], reverse=True)
        top = rows[: self.n]
        return [s for _, s in top], np.array([c for c, _ in top])

    # ------------------------------------------------------------------ algorithms 1 and 2
    def rank_weights(self) -> np.ndarray:
        rf_daily = self.risk_free_interest_rate_model.get_interest_rate(self.time) / 252.0
        R = np.array(self.rank_returns)  # T x n, oldest first
        X = R - rf_daily
        X = np.nan_to_num(X)

        # Algorithm 1: PCA on the factor window, loadings on the loading window.
        Xc = X - X.mean(axis=0)
        _, _, vt = np.linalg.svd(Xc, full_matrices=False)
        omega = vt[: self.k_factors]                     # K x n
        XL = X[-self.loading_window:]                    # L x n
        F = XL @ omega.T                                 # L x K factor returns
        A = np.column_stack([np.ones(len(XL)), F])
        coef, *_ = np.linalg.lstsq(A, XL, rcond=None)    # (K+1) x n
        beta = coef[1:].T                                # n x K
        phi = np.eye(self.n) - beta @ omega              # n x n
        eps = XL @ phi.T                                 # L x n residual returns

        # Algorithm 2: cumulative residuals, OU fit by AR(1), s-scores.
        x = np.cumsum(eps, axis=0)
        x_prev, x_next = x[:-1], x[1:]
        mp, mn = x_prev.mean(axis=0), x_next.mean(axis=0)
        var = ((x_prev - mp) ** 2).sum(axis=0)
        cov = ((x_prev - mp) * (x_next - mn)).sum(axis=0)
        safe_var = np.where(var > 0, var, 1.0)
        b = np.where(var > 0, cov / safe_var, np.nan)
        a = mn - b * mp
        resid = x_next - (a + b * x_prev)
        var_e = resid.var(axis=0, ddof=2)
        valid = np.isfinite(b) & (b > 0) & (b < 1) & (var_e > 0)
        b_safe = np.where(valid, b, 0.5)
        tau = np.where(valid, -1.0 / np.log(b_safe), np.inf)
        mu = np.where(valid, a / (1.0 - b_safe), 0.0)
        sigma_eq = np.where(valid, np.sqrt(var_e / (1.0 - b_safe ** 2)), np.nan)
        s = np.where(valid, (x[-1] - mu) / np.where(valid, sigma_eq, 1.0), np.nan)

        pos = self.position
        for k in range(self.n):
            if not np.isfinite(s[k]):
                pos[k] = 0
                continue
            if pos[k] == 0:
                if tau[k] < self.max_tau:
                    if s[k] < -self.open_threshold:
                        pos[k] = 1
                    elif s[k] > self.open_threshold:
                        pos[k] = -1
            elif abs(s[k]) < self.close_threshold:
                pos[k] = 0

        w = phi.T @ pos
        l1 = np.abs(w).sum()
        if l1 > 0:
            w = w / l1 * self.gross_leverage
        return w

    def on_end_of_algorithm(self) -> None:
        self.log(f"final equity {self.portfolio.total_portfolio_value:,.0f}, days traded {self.days_traded}")
