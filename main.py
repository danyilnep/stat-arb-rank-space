"""Statistical arbitrage in rank space on QuantConnect: data, state and execution.

Implements the parametric strategy (Algorithms 1 and 2) of Y.-F. Li and G. Papanicolaou,
"Statistical Arbitrage in Rank Space", arXiv:2410.06568v1 (Stanford, October 2024), as a
QuantConnect LEAN algorithm. Equation and section numbers refer to that version; v2 (June 2026)
renumbers them. The mathematics lives in ``rank_space.py`` (numpy only, unit-tested); this file
holds what needs QuantConnect: the universe, the daily loop, the state carried between days
and the orders.

Map to the paper
----------------
=============================  =================================================================
Code                           Paper
=============================  =================================================================
select, ranked_caps            Section 2.1.2, rank space: the largest ``n_ranks`` companies by
                               daily capitalisation (``rank_space.DailyCaps``), sorted, so
                               index k is rank k+1 on that day.
on_data (rank returns)         Eq. 2.1.9 via ``rank_space_returns``: the change in the
                               capitalisation at each rank from one day to the next.
rank_weights                   Algorithm 1 (``market_decomposition``) and Algorithm 2
                               (``fit_ou``, ``update_positions``, ``paper_weights``), plus the
                               traded book (``traded_weights``).
trade                          The rank-to-name step of Section 2.3: each rank's leg is held on
                               the company occupying that rank today and moves when the rank
                               changes hands.
BasisPointFeeModel             Transaction cost of Section 2.3.1, eta = 2 basis points of the
                               value traded.
on_data (paper P&L)            The before-cost rank-space P&L of the paper's own weights,
                               plotted as chart "Rank vs name" next to the realised equity.
=============================  =================================================================

Deviations from the paper, with reasons (mathematical ones are listed in ``rank_space.py``)
-------------------------------------------------------------------------------------------
1. 100 ranks instead of 500, so that a multi-year daily backtest fits QuantConnect's free
   backtest node.
2. Capitalisations come from QuantConnect's Morningstar data on its US equity universe
   (delisted names included, primary shares priced above $1) instead of CRSP.
   ``Fundamental.market_cap`` is a month-end snapshot held for a whole month, so from v4 on
   (``cap_source = "rolled"``, the default) each company's reported cap is rolled forward daily
   with its adjusted price by ``rank_space.DailyCaps`` and ranks are formed on that daily value.
   Runs v1 to v3 ranked and computed rank returns on the raw monthly field, which left most
   daily rank returns at exactly zero; ``cap_source = "reported"`` reproduces that behaviour.
   The evidence is in ``docs/data-checks.md``.
3. Rebalancing from daily data instead of every 225 minutes intraday (Section 2.3, Algorithm 4).
   Minute data for 130 names over several years does not fit the free tier. ``on_data`` acts
   once per calendar date, at the first data event QuantConnect delivers for it: at 00:00 New
   York time on about seven dates in ten and at 16:00 (13:00 on early-close days) on the rest
   (``results/v4/timing.csv``). Either way it ranks on the latest universe selection, which
   carries the previous trading day's close. Its orders are market-on-open orders: those of a
   midnight pass fill at that morning's open, those of a 16:00 pass at the next trading day's
   open, one session later, so about one open in five gets no orders and about as many get the
   orders of two passes. The paper's weights, as booked in ``on_data``, have no such execution
   lag: they earn the rank returns from one close to the next. The paper's latency cost (the
   rank switching between rebalancing points, first term of Eq. 2.3.6) comes on top.
4. The traded book is a fixed ``leg_weight`` per open rank plus one SPY hedge, not the paper's
   Phi^T w (``rank_space.py``, deviation 1). An order is sent only when a position opens or
   closes, a rank changes hands, or a holding drifts from its target by more than
   ``order_threshold`` (``hedge_threshold`` for SPY). A hedge smaller than ``hedge_threshold`` of
   equity is not held at all. Reason: QuantConnect's free tier stops a backtest at 10,000 orders,
   and every order avoided extends the period a run can cover. The leg is 2.5% of equity from
   v4 on. The superseded v3 held 5%, which asked for more gross exposure than QuantConnect's
   default margin model allows, so about four orders in ten were rejected and counted toward
   the order cap; the same code at 2.5% had 3.10% and 0.03% rejected
   (``results/checks/margin/``).
5. Neither the latency cost nor the execution lag is modelled as a separate term; both are paid
   inside the realised P&L, because the legs really are moved between companies only when the
   algorithm trades. The 2 bp fee applies to every order, SPY included.
6. Periods: v4 ran in eight windows starting on 1 January of 2011, 2013, 2015, 2017, 2018,
   2020, 2022 and 2024 (``start_year``), not over the paper's 2006 to 2022. At about 40%
   turnover a day a run reaches the 10,000-order cap after about 20 months (18.8 to 22.0 in
   ``results/v4/summary.csv``), so every window but 2024 stopped before the end of its second
   year and its last months are not covered; the 2024 window ran the full year. The two
   six-year chunks of v3 (2011 to 2017, 2018 to 2024) are superseded.
7. The paper-weight P&L applies the weights computed on day t to the rank returns of day t+1,
   before costs. It measures the signal in rank space; it is not a tradable equity curve.

Other settings: $1,000,000 start; 403 calendar days of warm-up (1.6 x 252) so the 252-day factor
window is full before the first trade; 30 names subscribed beyond rank 100 so a company entering
the top 100 already has data; risk-free rate from QuantConnect's interest-rate model.

Origin: a 2024 Mercury Capital Management quant-team project that attempted the same paper
with a CNN and minute data inside QuantConnect's free research node. The 2024 material is in
``received/``.
"""

# region imports
from AlgorithmImports import *
import numpy as np
from collections import deque

from rank_space import (
    DailyCaps,
    excess_returns,
    fit_ou,
    market_decomposition,
    paper_weights,
    rank_space_returns,
    traded_weights,
    update_positions,
)
# endregion


class BasisPointFeeModel(FeeModel):
    """Proportional transaction cost, as in the paper (default 2 basis points).

    fee = rate * |quantity| * price, with rate = basis_points / 10,000. This is the eta term of
    Section 2.3.1 (eta = 0.0002) applied to each order's traded value.
    """

    def __init__(self, basis_points: float) -> None:
        super().__init__()
        self.rate = basis_points / 10_000.0

    def get_order_fee(self, parameters: OrderFeeParameters) -> OrderFee:
        value = parameters.security.price * abs(parameters.order.quantity)
        return OrderFee(CashAmount(value * self.rate, "USD"))


class RankSpaceStatArb(QCAlgorithm):
    """Statistical arbitrage in rank space, Algorithms 1 and 2 of Li and Papanicolaou.

    On each date the largest ``n_ranks`` US stocks by market capitalisation (by default the monthly
    Morningstar value rolled forward daily, see ``select``) are ranked, and returns are computed
    in rank space: the return of rank k is the change in the capitalisation held at rank k,
    whichever company that is. Algorithm 1 removes one PCA market factor and leaves
    residual returns per rank; Algorithm 2 fits an Ornstein-Uhlenbeck process to each rank's
    cumulative residual and opens a residual position when the s-score crosses the open
    threshold. The positions are held on the companies occupying the ranks.

    Project parameters (QuantConnect project parameters or ``config.json``), with defaults:

    ``start_year`` 2018, ``end_year`` 2024
        Backtest from 1 January of ``start_year`` to 31 December of ``end_year``. On
        QuantConnect's free tier a run stops earlier, at 10,000 orders, which v4 reaches after
        about 20 months; the published v4 windows were set through these two parameters.
    ``n_ranks`` 100
        Number of ranks (the paper uses 500).
    ``factor_window`` 252, ``loading_window`` 60
        Days of rank returns for the PCA factor, and for the loadings and the OU fit.
    ``open_threshold`` 1.25, ``close_threshold`` 0.5, ``max_tau_days`` 30
        s-score to open and to close, and the mean-reversion time an opening needs.
    ``fee_bps`` 2
        Transaction cost in basis points of traded value.
    ``cap_source`` "rolled"
        "rolled": daily capitalisations rolled forward from the monthly Morningstar field
        (v4). "reported": the raw monthly field, as runs v1 to v3 used it.
    ``leg_weight`` 0.025
        Fraction of equity per open residual position. v3 used 0.05, which asked for more gross
        exposure than the default margin model allows and had about 41% to 45% of its orders
        rejected; at 0.025 the v3 check runs had 3.1% and 0.03% rejected.
    ``order_threshold`` 0.015, ``hedge_threshold`` 0.02
        Drift from target, as a fraction of equity, before a leg (or the SPY hedge) is re-traded.

    Fixed in code: one factor, the SPY hedge capped at 50% of equity, 30 buffer names.
    """

    def initialize(self) -> None:
        self.set_start_date(int(self.get_parameter("start_year", 2018)), 1, 1)
        self.set_end_date(int(self.get_parameter("end_year", 2024)), 12, 31)
        self.set_cash(1_000_000)

        # Paper parameters.
        self.n = int(self.get_parameter("n_ranks", 100))
        self.factor_window = int(self.get_parameter("factor_window", 252))
        self.loading_window = int(self.get_parameter("loading_window", 60))
        self.k_factors = 1  # the paper finds one factor enough in rank space (Section 3.2)
        self.open_threshold = float(self.get_parameter("open_threshold", 1.25))
        self.close_threshold = float(self.get_parameter("close_threshold", 0.5))
        self.max_tau = float(self.get_parameter("max_tau_days", 30))
        self.fee_bps = float(self.get_parameter("fee_bps", 2))
        # Implementation parameters.
        self.cap_source = str(self.get_parameter("cap_source", "rolled"))
        if self.cap_source not in ("rolled", "reported"):
            raise ValueError(f"cap_source must be 'rolled' or 'reported', not {self.cap_source!r}")
        self.leg_weight = float(self.get_parameter("leg_weight", 0.025))
        self.order_threshold = float(self.get_parameter("order_threshold", 0.015))
        self.hedge_threshold = float(self.get_parameter("hedge_threshold", 0.02))
        self.max_hedge = 0.5
        self.buffer = 30  # extra names subscribed so rank switches at the boundary are covered

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.securities[self.spy].set_fee_model(BasisPointFeeModel(self.fee_bps))
        self.set_benchmark(self.spy)
        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self.select)
        # Allow small rebalancing orders; the thresholds in trade() decide what is worth sending.
        self.settings.minimum_order_margin_portfolio_percentage = 0.0

        self.members: set = set()
        self.daily_caps = DailyCaps()   # anchors for rolling the monthly cap forward (v4)
        self.caps_today: dict = {}      # Symbol -> capitalisation from the latest selection
        self.prev_caps: Optional[np.ndarray] = None
        self.rank_returns: deque = deque(maxlen=self.factor_window)  # rolling T x n window
        self.position = np.zeros(self.n)        # residual-space position per rank, in {-1, 0, 1}
        self.paper_weights: Optional[np.ndarray] = None  # yesterday's Phi^T w, L1-normalised
        self.paper_cum = 1.0                     # before-cost rank-space P&L of the paper's weights
        self.start_equity = None
        self.last_day = None
        self.days_traded = 0
        self.opens = 0
        self.closes = 0
        self.orders_sent = 0

        # 1.6 x 252 = 403 calendar days, enough trading days to fill the factor window.
        self.set_warm_up(timedelta(days=int(self.factor_window * 1.6)))

    # ------------------------------------------------------------------ universe
    def select(self, fundamental: List[Fundamental]) -> List[Symbol]:
        """Daily universe: the n_ranks + buffer largest primary shares priced above $1.

        QuantConnect runs it at midnight after each trading day, on that day's close, before the
        next date's data; ``on_data`` ranks on the latest run. With ``cap_source =
        "rolled"`` every eligible company's monthly Morningstar cap is rolled forward with its
        adjusted price, so the ranking and the capitalisations stored in ``caps_today`` move
        daily. With ``"reported"`` the raw field is used, as in runs v1 to v3; the sort is then
        the same stable sort on the same values as the recorded code.
        """
        candidates = []
        for f in fundamental:
            if not (f.has_fundamental_data and f.market_cap > 0 and f.price > 1
                    and f.security_reference.is_primary_share):
                continue
            if self.cap_source == "rolled":
                cap = self.daily_caps.update(f.symbol, float(f.market_cap), float(f.adjusted_price))
            else:
                cap = float(f.market_cap)
            candidates.append((cap, f.symbol))
        candidates.sort(key=lambda c: c[0], reverse=True)
        top = candidates[: self.n + self.buffer]
        self.caps_today = {symbol: cap for cap, symbol in top}
        return [symbol for _, symbol in top]

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
                self.orders_sent += 1

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
            # Rank-space return (Eq. 2.1.9): caps and prev_caps are both sorted by rank, so the
            # company behind a rank may differ between the two days.
            todays_return = rank_space_returns(caps, self.prev_caps)
            self.rank_returns.append(todays_return)
            if self.paper_weights is not None:
                # Yesterday's paper weights earn today's rank returns, before costs.
                self.paper_cum *= 1.0 + float(self.paper_weights @ todays_return)
        self.prev_caps = caps

        if self.is_warming_up or len(self.rank_returns) < self.factor_window:
            return
        if self.start_equity is None:
            self.start_equity = self.portfolio.total_portfolio_value

        leg_weights, hedge_weight = self.rank_weights()
        self.trade(symbols, leg_weights, hedge_weight)

        self.days_traded += 1
        if self.days_traded % 5 == 0:
            realised = (self.portfolio.total_portfolio_value / self.start_equity - 1.0) * 100.0
            self.plot("Rank vs name", "rank space, paper weights, before costs", (self.paper_cum - 1.0) * 100.0)
            self.plot("Rank vs name", "name space, realised, after costs", realised)
        if self.days_traded % 63 == 0:
            self.log(f"{today} open ranks {int(np.count_nonzero(self.position))} opens {self.opens} "
                     f"closes {self.closes} orders {self.orders_sent} hedge {hedge_weight:+.2f} "
                     f"paper {self.paper_cum - 1.0:+.3f}")

    def ranked_caps(self):
        """Symbols and capitalisations at ranks 1..n from today's point-in-time data.

        This is the rank-to-name map for the day: entry k is the company holding rank k+1.
        Returns None until at least n subscribed names have data.
        """
        rows = []
        for symbol in self.members:
            security = self.securities[symbol]
            f = security.fundamentals
            if f is None or not security.has_data:
                continue
            # v4 reads the daily cap computed in select(); v1 to v3 read the monthly field.
            cap = self.caps_today.get(symbol) if self.cap_source == "rolled" else f.market_cap
            if cap is None or cap <= 0:
                continue
            rows.append((float(cap), symbol))
        if len(rows) < self.n:
            return None
        rows.sort(key=lambda r: r[0], reverse=True)
        top = rows[: self.n]
        return [s for _, s in top], np.array([c for c, _ in top])

    # ------------------------------------------------------------------ algorithms 1 and 2
    def rank_weights(self):
        """One day of Algorithms 1 and 2; returns (legs per rank, SPY hedge weight).

        Updates ``self.position`` in place, the ``opens`` and ``closes`` counters, and
        ``self.paper_weights``. Numerically identical to the inline code of the recorded runs
        (``tests/test_rank_space.py`` checks this against a verbatim copy).
        """
        rf_daily = self.risk_free_interest_rate_model.get_interest_rate(self.time) / 252.0
        X = excess_returns(self.rank_returns, rf_daily)  # T x n, oldest first

        # Algorithm 1: PCA factor on the factor window, loadings on the loading window, Phi.
        decomposition = market_decomposition(X, self.loading_window, self.k_factors)

        # Algorithm 2: cumulative residuals, OU fit by AR(1), s-scores, open/hold/close rule.
        ou = fit_ou(decomposition.residuals)
        opens, closes = update_positions(self.position, ou.s_score, ou.tau, self.open_threshold,
                                         self.close_threshold, self.max_tau)
        self.opens += opens
        self.closes += closes

        # The paper's weights (Phi^T w, L1-normalised), kept for the before-cost comparison.
        self.paper_weights = paper_weights(decomposition.phi, self.position)

        # Traded weights: a fixed leg per open rank, one SPY hedge for the factor exposure.
        return traded_weights(self.position, decomposition.beta, decomposition.omega,
                              self.leg_weight, self.max_hedge)

    # ------------------------------------------------------------------ execution
    def trade(self, symbols, leg_weights, hedge_weight) -> None:
        """Rank-to-name execution: put each rank's leg on the company holding that rank today.

        Targets are fractions of equity. Holdings with no target are closed (the rank's
        position closed or the rank passed to another company); a target is re-sent only when
        the holding has drifted past the threshold, to keep the order count down.
        """
        equity = self.portfolio.total_portfolio_value
        targets = {}
        for k, symbol in enumerate(symbols):
            if leg_weights[k] != 0:
                targets[symbol] = targets.get(symbol, 0.0) + float(leg_weights[k])
        if abs(hedge_weight) > self.hedge_threshold:
            targets[self.spy] = hedge_weight

        for kvp in self.portfolio:
            symbol, holding = kvp.key, kvp.value
            if holding.invested and symbol not in targets:
                self.liquidate(symbol, tag="closed")
                self.orders_sent += 1

        for symbol, target in targets.items():
            current = self.portfolio[symbol].holdings_value / equity if equity > 0 else 0.0
            threshold = self.hedge_threshold if symbol == self.spy else self.order_threshold
            if abs(target - current) > threshold:
                self.set_holdings(symbol, target)
                self.orders_sent += 1

    def on_end_of_algorithm(self) -> None:
        self.log(f"final equity {self.portfolio.total_portfolio_value:,.0f}; days traded {self.days_traded}; "
                 f"opens {self.opens}; closes {self.closes}; orders {self.orders_sent}; "
                 f"paper rank-space P&L {self.paper_cum - 1.0:+.3f}")
