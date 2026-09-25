# region imports
from AlgorithmImports import *
# endregion


class CapProbe(QCAlgorithm):
    """Logs, day by day, what the daily Fundamental universe feed says about three large caps.

    For AAPL, MSFT and XOM from 2 January to 15 February 2019, one log line per name per day:
    the unadjusted price (f.price), the adjusted price, Morningstar's market cap, shares
    outstanding (company_profile.shares_outstanding) and unadjusted price times shares. The
    question is whether f.market_cap moves daily or in steps, and whether price x shares is a
    usable daily capitalisation. Logs are used because this free-tier backtest keeps too few
    custom-chart points; the output is about 6 KB, inside the 10 KB log allowance.
    """

    def initialize(self) -> None:
        self.set_start_date(2019, 1, 2)
        self.set_end_date(2019, 2, 15)
        self.set_cash(100_000)
        self.watch = {"AAPL", "MSFT", "XOM"}
        self.add_universe(self.select)

    def select(self, fundamental: List[Fundamental]) -> List[Symbol]:
        for f in fundamental:
            ticker = f.symbol.value
            if ticker not in self.watch or not f.has_fundamental_data:
                continue
            shares = float(f.company_profile.shares_outstanding or 0)
            self.log(
                f"{self.time:%Y-%m-%d} {ticker} px {f.price:.2f} adj {f.adjusted_price:.2f} "
                f"mcap {f.market_cap / 1e9:.2f} sh {shares / 1e9:.4f} pxsh {f.price * shares / 1e9:.2f}"
            )
        return []
