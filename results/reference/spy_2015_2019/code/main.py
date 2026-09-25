# region imports
from AlgorithmImports import *
# endregion


class AuditBenchmarks(QCAlgorithm):
    """Reference buy-and-hold runs used by the audit notes of both strategy repos.

    mode = spy_2015_2019: SPY held from 1 Jan 2015 to 31 Dec 2019, the window of the
           2024 rank-space CNN backtest.
    mode = basket_2023:  equal-weight hold of the seven stocks the 2024 DCF prototype
           traded (AAPL, AVGO, NVO, XOM, UNH, PG, NKE) through calendar 2023.
    """

    def initialize(self) -> None:
        mode = self.get_parameter("mode", "spy_2015_2019")
        self.set_cash(100_000)
        if mode == "basket_2023":
            self.set_start_date(2023, 1, 1)
            self.set_end_date(2023, 12, 31)
            tickers = ["AAPL", "AVGO", "NVO", "XOM", "UNH", "PG", "NKE"]
        else:
            self.set_start_date(2015, 1, 1)
            self.set_end_date(2019, 12, 31)
            tickers = ["SPY"]
        self.symbols = [self.add_equity(t, Resolution.DAILY).symbol for t in tickers]
        self.set_benchmark("SPY")
        self.invested = False

    def on_data(self, data: Slice) -> None:
        if self.invested or not all(data.contains_key(s) for s in self.symbols):
            return
        weight = 1.0 / len(self.symbols)
        self.set_holdings([PortfolioTarget(s, weight) for s in self.symbols])
        self.invested = True
