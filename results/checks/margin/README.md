# Margin check: v3 at half the leg weight

Written by `analysis/build_results.py` from the exports in `results/raw/`; a rebuild overwrites it.

The v3 runs held a fixed leg of 5% of equity per open rank plus an SPY hedge, and QuantConnect rejected about four orders in ten of them for insufficient buying power. Two backtests on 25 September ran the same v3 code at half the leg weight, on the same day and LEAN build as the re-runs at the full weight (`../reproduction/`), with the same `main.py`. Both use the monthly reported market cap, as v3 did. v4 takes 0.025 as its default leg weight.

| Chunk | Key | Leg weight | Orders | Filled | Rejected | Rejected share | Cancelled | Open at stop | Order cap | Last fill | Net | Sharpe | Fees | Gross exposure, median | Samples at 1.9x or more |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2011 to 2017 | `rerun__sa_v3_2011` | 0.05 | 10,001 | 4,985 | 4,465 | 44.65% | 551 | 0 | hit 2017-02-09 | 2017-02-02 | +1.804% | −0.119 | $57,054 | 1.20 | 20.8% |
| 2011 to 2017 | `sa__half_leg_2011` | 0.025 | 7,654 | 6,696 | 237 | 3.10% | 721 | 0 | not reached | 2017-12-27 | +5.165% | −0.162 | $41,279 | 0.63 | 1.5% |
| 2018 to 2024 | `rerun__sa_v3_2018` | 0.05 | 10,001 | 5,443 | 4,091 | 40.91% | 465 | 2 | hit 2024-02-05 | 2024-02-02 | +24.124% | 0.072 | $72,077 | 1.35 | 21.7% |
| 2018 to 2024 | `sa__half_leg_2018` | 0.025 | 7,555 | 6,955 | 2 | 0.03% | 598 | 0 | not reached | 2024-12-26 | +16.148% | −0.375 | $45,236 | 0.69 | 0.2% |

At a leg weight of 0.05, QuantConnect rejected 4,465 of 10,001 orders (44.6%) in 2011 to 2017 and 4,091 of 10,001 orders (40.9%) in 2018 to 2024; the analysis QuantConnect attaches to each run counts the same number of insufficient-buying-power errors. Its sample error puts the initial margin at 50% of the order value, so the account could hold about twice its equity in positions. Rejected orders count toward the order cap, which these runs reached on 9 February 2017 and 5 February 2024. At 0.025 the same code had 237 of 7,654 rejected (3.10%) and 2 of 7,555 rejected (0.03%), did not reach the order cap and ran to 31 December 2017 and 31 December 2024.

The gross exposure column is `exposure_long` minus `exposure_short` over the equity samples (the same definition as in each run folder's `equity.csv`). Halving the legs brought the median from 1.20 to 0.63 (2011 to 2017) and 1.35 to 0.69 (2018 to 2024) times equity. Both columns are computed from the exposures as exported, before the rounding to four decimals in `equity.csv`.

Net return and Sharpe are not comparable between the rows: the full-weight runs stopped at the order cap, the half-weight runs cover the whole configured period, and a run with smaller legs holds less of the signal. The check is about whether the book QuantConnect holds is the book the signal asks for.

## Files

| File | Content |
|---|---|
| `comparison.csv` | The table above with QuantConnect identifiers, creation time, LEAN build, SHA-256 of `main.py` as QuantConnect ran it, configured window, first fill and the count of insufficient-buying-power errors QuantConnect's analysis reports |
| `half_leg_2011_2017/statistics.json`, `half_leg_2018_2024/statistics.json` | QuantConnect's statistics, runtime, trade and portfolio statistics, parameters, backtest metadata and analysis warnings for each half-weight run, plus a `derived` block as in the run folders |

The full-weight runs' statistics are in `../reproduction/comparison.csv`; every order of all four runs is in the raw exports.
