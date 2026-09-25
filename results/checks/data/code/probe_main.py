# region imports
from AlgorithmImports import *
import numpy as np
# endregion


class DataProbe(QCAlgorithm):
    """Checks two data assumptions the strategy repos rely on, and plots monthly answers.

    1. Rank-space returns in stat-arb-rank-space are computed from Fundamental.market_cap at
       the first on_data call of each calendar day. That is only meaningful if the cap moves
       from one trading day to the next. For the 100 largest names, chart "Caps" plots per
       month: the share of day-over-day comparisons where the cap did not change, the share
       where the cap moved by the same ratio as the price (cap = price x shares), the share
       where the price moved but the cap did not, the mean number of on_data calls per day,
       and the mean hour of the first call.
    2. The DCF growth bounds (-5% to +15%) assume OperationRatios.ebitda_growth.one_year is a
       decimal fraction (0.10 = 10%). Chart "EBITDA growth" plots, at each month start, the
       median and the 90th percentile of its absolute value across the top 100.
    Everything is aggregated to one point per month because the free tier keeps few chart
    points and only 10 KB of logs per backtest.
    """

    def initialize(self) -> None:
        year = int(self.get_parameter("year", 2012))
        self.set_start_date(year, 1, 1)
        self.set_end_date(year, 12, 31)
        self.set_cash(100_000)
        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self.select)
        self.members: set = set()
        self.prev_cap: dict = {}
        self.prev_price: dict = {}
        self.last_day = None
        self.month = None
        self.reset_month()

    def reset_month(self) -> None:
        self.m = {"compared": 0, "unchanged": 0, "with_price": 0, "price_only": 0,
                  "days": 0, "calls": 0, "first_hour_sum": 0.0}

    def select(self, fundamental: List[Fundamental]) -> List[Symbol]:
        candidates = [
            f for f in fundamental
            if f.has_fundamental_data and f.market_cap > 0 and f.price > 1
            and f.security_reference.is_primary_share
        ]
        candidates.sort(key=lambda f: f.market_cap, reverse=True)
        return [f.symbol for f in candidates[:100]]

    def on_securities_changed(self, changes: SecurityChanges) -> None:
        for security in changes.added_securities:
            self.members.add(security.symbol)
        for security in changes.removed_securities:
            self.members.discard(security.symbol)

    def flush_month(self) -> None:
        m = self.m
        if m["compared"]:
            self.plot("Caps", "cap unchanged share", m["unchanged"] / m["compared"])
            self.plot("Caps", "cap moved with price share", m["with_price"] / m["compared"])
            self.plot("Caps", "price moved, cap unchanged share", m["price_only"] / m["compared"])
        if m["days"]:
            self.plot("Calls", "on_data calls per day", m["calls"] / m["days"])
            self.plot("Calls", "hour of first call", m["first_hour_sum"] / m["days"])
        self.reset_month()

    def on_data(self, data: Slice) -> None:
        today = self.time.date()
        self.m["calls"] += 1
        if today == self.last_day:
            return
        self.last_day = today
        if self.month is not None and today.month != self.month:
            self.flush_month()
            self.m["calls"] = 1
        new_month = today.month != self.month
        self.month = today.month
        self.m["days"] += 1
        self.m["first_hour_sum"] += self.time.hour + self.time.minute / 60.0

        growth = []
        for symbol in self.members:
            security = self.securities[symbol]
            f = security.fundamentals
            if f is None or not security.has_data:
                continue
            cap = float(f.market_cap)
            price = float(security.price)
            if cap <= 0 or price <= 0:
                continue
            if symbol in self.prev_cap:
                prev_cap, prev_price = self.prev_cap[symbol], self.prev_price[symbol]
                self.m["compared"] += 1
                if cap == prev_cap:
                    self.m["unchanged"] += 1
                    if price != prev_price:
                        self.m["price_only"] += 1
                elif abs(cap / prev_cap - price / prev_price) < 1e-6:
                    self.m["with_price"] += 1
            self.prev_cap[symbol] = cap
            self.prev_price[symbol] = price
            if new_month:
                g = f.operation_ratios.ebitda_growth.one_year
                if g is not None and not np.isnan(g) and g != 0:
                    growth.append(float(g))
        if new_month and growth:
            values = np.array(growth)
            self.plot("EBITDA growth", "median one_year", float(np.median(values)))
            self.plot("EBITDA growth", "p90 of absolute value", float(np.percentile(np.abs(values), 90)))

    def on_end_of_algorithm(self) -> None:
        self.flush_month()
