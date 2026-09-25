# Reproduction of the v3 runs

Written by `analysis/build_results.py` from the exports in `results/raw/`; a rebuild overwrites it.

The two recorded v3 runs (now in `../../superseded/`) ran on 22 September 2026 with a single `main.py`. The code was then split into `main.py` and `rank_space.py`, and later extended to v4. Four backtests on 25 September test whether either change altered what v3 does:

| Chunk | Run | Key | QuantConnect project / backtest | Created (UTC) | LEAN | Parameters | `main.py`, as run | `rank_space.py`, as run |
|---|---|---|---|---|---|---|---|---|
| 2018 to 2024 | Recorded v3 run | `sa__v3_2018` | 36836415 / `34bc2a26371280c36ee4bd62f36b7f93` | 2026-09-22 18:00:54 | v2.5.0.0.18116 | code defaults | `6b42cfb3...` | n/a |
| 2018 to 2024 | Re-run, refactored code | `rerun__sa_v3_2018` | 36836415 / `750e8e081cbadc1707fa2cc4f61d77e1` | 2026-09-25 00:01:34 | v2.5.0.0.18126 | code defaults | `aec2f202...` | `576c149b...` |
| 2018 to 2024 | Control, recorded main.py | `control__sa_v3_2018_recorded_code` | 36924052 / `3b47a7efaa9763937ce344ad01e5a70b` | 2026-09-25 00:13:07 | v2.5.0.0.18126 | code defaults | `6b42cfb3...` | n/a |
| 2018 to 2024 | v4 code, v3 parameters | `check__v3_via_params_2018` | 36836415 / `59c153e30f7dbc30d429dc5690e972c3` | 2026-09-25 00:46:13 | v2.5.0.0.18126 | cap_source=reported; leg_weight=0.05 | `15789ef3...` | `024d3f7c...` |
| 2011 to 2017 | Recorded v3 run | `sa__v3_2011` | 36836415 / `52a7a3c0c4125798b5e32ced4a0591be` | 2026-09-22 18:05:47 | v2.5.0.0.18116 | start_year=2011; end_year=2017 | `6b42cfb3...` | n/a |
| 2011 to 2017 | Re-run, refactored code | `rerun__sa_v3_2011` | 36836415 / `d854bcc40d82f63ac56ef65ab22cb7fc` | 2026-09-25 00:10:10 | v2.5.0.0.18126 | start_year=2011; end_year=2017 | `aec2f202...` | `576c149b...` |

- The re-runs ran the refactored v3 code, before v4, with the v3 parameters as its defaults (`leg_weight` default 0.05).
- The control ran the recorded `main.py` (the same SHA-256 as the recorded runs) again, in a separate QuantConnect project, on the same day and LEAN build as the re-run.
- The check ran the v4 code, the repository's `main.py` and `rank_space.py` of the v4 runs, with `cap_source=reported` and `leg_weight=0.05`, the settings that give v3's behaviour.
- Hashes are the SHA-256 of each file as QuantConnect ran it, from `../../provenance/code_hashes.json`; `comparison.csv` has them in full. Where the copy of a file in `../../raw/` has one docstring paragraph rewritten to leave out the other team members' names, its own hash differs (`runs.csv` gives both).

## LEAN versions

The exports of the recorded runs do not carry a LEAN version; it comes from `raw/engines__original_runs.json.gz`, a separate export of the server statistics of each original backtest. QuantConnect upgraded LEAN between the recorded runs (v2.5.0.0.18116) and the checks (v2.5.0.0.18126).

## Result

The runs of 25 September on the 2018 to 2024 chunk (`rerun__sa_v3_2018`, `control__sa_v3_2018_recorded_code`, `check__v3_via_params_2018`) are identical to each other: all 27 statistics, all 3,013 closed trades and all 10,001 orders, compared on every exported field. The split into `main.py` and `rank_space.py` changed nothing, and the v4 code reproduces v3 through its parameters.

Against the recorded runs of 22 September, the re-runs differ. The recorded code, re-run in the control, shows the same difference, so it comes from QuantConnect's side (data and engine), not from the code:

| Statistic | Recorded, 2018 to 2024 | Re-run, 2018 to 2024 | Recorded, 2011 to 2017 | Re-run, 2011 to 2017 |
|---|---|---|---|---|
| Compounding Annual Return | 3.648% | 3.606% | 0.110% | 0.293% |
| Drawdown | 10.600% | 10.900% | 9.600% | 9.600% |
| Expectancy | 0.035 | 0.034 | 0.005 | 0.007 |
| End Equity | 1244351.93 | 1241239.65 | 1006746.65 | 1018042.84 |
| Net Profit | 24.435% | 24.124% | 0.675% | 1.804% |
| Sharpe Ratio | 0.077 | 0.072 | -0.149 | -0.119 |
| Sortino Ratio | 0.087 | 0.081 | -0.183 | -0.146 |
| Probabilistic Sharpe Ratio | 0.290% | 0.277% | 0.033% | 0.046% |
| Alpha | 0.002 | 0.002 | -0.006 | -0.005 |
| Beta | 0.026 | 0.027 | -0.006 | -0.007 |
| Information Ratio | -0.424 | -0.426 | -0.703 | -0.688 |
| Tracking Error | 0.173 | 0.172 | 0.132 | 0.132 |
| Treynor Ratio | 0.158 | 0.143 | 1 | 0.771 |
| Total Fees | $72130.44 | $72076.76 | $56727.99 | $57053.51 |
| Portfolio Turnover | 13.81% | 13.82% | 12.68% | 12.73% |
| Closed trades (exported) | 3,010 | 3,013 | 2,709 | 2,717 |
| Orders (exported) | 10,001 | 10,001 | 10,001 | 10,001 |

Of the 27 statistics, 15 differ in at least one chunk.

## Where the runs part

`first_divergence.csv` gives, for each chunk, the first order (in order-id order) whose time, symbol, quantity, fill price or status differs between the recorded run and its re-run:

- 2018 to 2024: order 27 (position 26), submitted 2018-01-02, MDT: recorded 765 shares at 65.1053, re-run 772 shares at 64.5805. Every earlier order is the same.
- 2011 to 2017: order 21 (position 20), submitted 2011-01-12, MDT: recorded 2,015 shares at 24.9114, re-run 2,031 shares at 24.7106. Every earlier order is the same.

`fill_price_ratios.csv` pairs the filled orders of each recorded run and its re-run that share submission time and symbol, and gives the re-run's fill price over the recorded one per symbol. 149 symbols in the 2018 to 2024 chunk and 137 in the 2011 to 2017 chunk have such pairs; all but these have a ratio of exactly 1 on every pair:

| Chunk | Symbol | Matched fills | Ratio, lowest | Ratio, highest |
|---|---|---|---|---|
| 2018 to 2024 | LRCX | 16 | 1.000031 | 1.000031 |
| 2018 to 2024 | MDT | 46 | 0.991938 | 0.991938 |
| 2011 to 2017 | MDT | 55 | 0.991938 | 0.991938 |

One constant factor across years of fills is what a change in a stock's price adjustment produces: QuantConnect's default for US equities is to trade on split- and dividend-adjusted prices, and a newly booked dividend rescales the whole earlier history of the stock. The exports show the factor, not its cause. A 0.81% lower MDT price means more shares for the same target value, so the first MDT order already differs, and the book, the order sequence and the statistics drift apart from there.

## Files

| File | Content |
|---|---|
| `comparison.csv` | One row per run: chunk, key, role, QuantConnect identifiers, creation time, LEAN build, parameters, SHA-256 of `main.py` and `rank_space.py` as QuantConnect ran them (blank where the run had no `rank_space.py`), QuantConnect's 27 statistics exactly as exported (text, with QuantConnect's rounding and units), the number of closed trades and orders, and four identity flags |
| `first_divergence.csv` | The first differing order of each chunk, recorded and re-run side by side (order id, submission and fill time in UTC, symbol, quantity, fill price, status) |
| `fill_price_ratios.csv` | Per chunk and symbol: matched filled orders and the lowest and highest ratio of re-run to recorded fill price |

Identity flags: `orders_identical_to_recorded` and `orders_identical_to_rerun` are true when every exported field of every order (id, type, submission and fill time, symbol, quantity, price, status, direction, value, tag, fee) equals that of the chunk's recorded run or re-run, in order-id order; `trades_identical_to_recorded` and `trades_identical_to_rerun` do the same for every field of every closed trade, in the exported order, except the trade `id`, a random UUID QuantConnect draws anew in each run.
