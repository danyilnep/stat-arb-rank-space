# Data checks

Written by `analysis/build_results.py` from the exports in `results/raw/`; a rebuild overwrites it.

Rank-space returns are the day-to-day change in the capitalisation held at each rank, so the strategy needs a capitalisation that moves every day. Runs v1 to v3 took it from Morningstar's `Fundamental.market_cap` in QuantConnect. Probe backtests that place no orders tested what that field does:

| Backtest | Key | QuantConnect project / backtest | Created (UTC) | LEAN | Period |
|---|---|---|---|---|---|
| Probe | `probe2__2012` | 36923739 / `843f4a7d9ac7d1d4fe5c23dea76eda92` | 2026-09-25 00:28:47 | v2.5.0.0.18126 | 2012-01-01 to 2012-12-31 |
| Probe | `probe2__2019` | 36923739 / `7e0a587bfa6cb6d324391beb453792be` | 2026-09-25 00:29:33 | v2.5.0.0.18126 | 2019-01-01 to 2019-12-31 |
| Cap probe | `capprobe2__2019` | 36924577 / `10bf1b25d6e517a9f7ddb811dba709d9` | 2026-09-25 00:36:08 | v2.5.0.0.18126 | 2019-01-02 to 2019-02-15 |

The probe (`code/probe_main.py`, one backtest per year through its `year` parameter) holds the 100 largest primary shares by `market_cap` with a price above $1, as the strategy's universe does, and aggregates what it sees to one chart point per month, because a free-tier backtest keeps few chart points. A first version of the probe had no once-per-day guard and counted repeat calls on the same day; it was discarded, and `probe2` is the corrected version.

| File | Content |
|---|---|
| `market_cap_updates.csv` | How often `market_cap` changed from one day to the next, per month |
| `cap_probe_2019.csv` | The cap probe's log, one row per name and day, with the daily cap `rank_space.DailyCaps` rolls forward from it |
| `cap_probe_reanchor.csv` | Each change of the reported cap in the cap probe, with the rolled-forward estimate for that day, its error, the adjusted and unadjusted price ratios since the anchor and the share-count change the snapshots imply |
| `cap_probe_2019.log` | The cap probe's log lines as exported |
| `ebitda_growth_monthly.csv` | Median and 90th percentile of the absolute value of `operation_ratios.ebitda_growth.one_year` per month (a check for the companion DCF repository, measured by the same probe) |
| `code/probe_main.py` | The probe's code as QuantConnect stored it (identical in both probe backtests) |
| `code/cap_probe_main.py` | The cap probe's code as QuantConnect stored it |

## Market cap updates

`market_cap_updates.csv`: one row per month. At the first data point of each day the probe compares every name's `market_cap` and price with the values it saw on the previous day.

| Column | Meaning |
|---|---|
| `year`, `month` | The month the comparisons fall in |
| `cap_unchanged_share` | Share of comparisons in which the cap did not change |
| `cap_moved_with_price_share` | Share in which the cap changed by the same ratio as the price (within 1e-6), as price times shares would |
| `price_moved_cap_unchanged_share` | Share in which the price changed and the cap did not |
| `calls_per_day` | Mean number of `on_data` calls per day |
| `hour_of_first_call` | Mean New York hour of the day's first `on_data` call |

QuantConnect stores each monthly point when the next month starts (the last one at the end of the backtest), so the build assigns each point to the month before its timestamp.

From February to December, between 94.7% and 95.7% of the comparisons in a month found the cap unchanged, while in 66.5% to 84.5% the price had moved and the cap had not. The cap moved in step with the price in no comparison in 23 of the 24 months; the exception is June 2019 (0.05% of comparisons). In January the share unchanged is exactly 1.0 in both years. That pattern fits a value that changes once a month: the probe starts on 1 January, so January's comparisons contain no change, and in later months about one comparison in 21 finds a change, one per name per month (a month has about 21 trading days).

`on_data` ran 1.52 to 1.90 times a day on average in a month, which is why the probe, like the strategy, acts only at the first call of each day. The mean New York hour of that first call was 2.4 to 8.4 in a month: on some dates the first call comes at midnight, on others at the 16:00 close. The strategy's order times show the same mix (`../../v4/timing.csv`). Where the first call of one date is at 16:00 and that of the next date at midnight, both see the same closing price, which is why the share of comparisons with both cap and price unchanged is not zero.

## Cap probe

The cap probe (`code/cap_probe_main.py`) logs, for AAPL, MSFT and XOM on every day of its run, the unadjusted price, the adjusted price, `market_cap`, `company_profile.shares_outstanding` and unadjusted price times shares. The log runs in the universe selection, which QuantConnect calls before the day's data, so the prices on a line dated D are the previous trading day's close.

`cap_probe_2019.log` holds the 98 exported log lines; `cap_probe_2019.csv` parses the 96 that match the probe's format into `date`, `ticker`, `price_unadjusted`, `price_adjusted`, `market_cap_bn`, `shares_outstanding_bn` and `price_x_shares_bn` (billions, as logged, rounded to two decimals by the log), and adds `rolled_cap_bn`: the value `rank_space.DailyCaps.update` returns when fed each day's `market_cap_bn` and `price_adjusted` in date order, the same call the algorithm makes in its universe selection when `cap_source` is `rolled`.

- AAPL: `market_cap_bn` is 746.08 from 2019-01-02 to 2019-01-31 and 784.81 from 2019-02-01 to 2019-02-15, while `price_unadjusted` takes 32 different values over the 32 logged days.
- MSFT: `market_cap_bn` is 780.36 from 2019-01-02 to 2019-01-31 and 801.21 from 2019-02-01 to 2019-02-15, while `price_unadjusted` takes 31 different values over the 32 logged days.
- XOM: `market_cap_bn` is 288.92 from 2019-01-02 to 2019-01-31 and 310.33 from 2019-02-01 to 2019-02-15, while `price_unadjusted` takes 31 different values over the 32 logged days.

On the first logged day the unadjusted price times the logged shares, over the reported cap, is 4.0000 for AAPL, 1.0000 for MSFT, 1.0000 for XOM. The reported cap is the previous close times a share count; for AAPL the logged `shares_outstanding` is four times that count, because the field is restated for splits made after the date, so price times `shares_outstanding` cannot stand in for the cap of a past date.

`cap_probe_reanchor.csv`: at each change of the reported cap, the previous anchor rolled forward with the adjusted price to that day, against the new snapshot:

| Ticker | Anchor date | Anchor cap, bn | Re-anchor date | Rolled estimate, bn | New snapshot, bn | Error |
|---|---|---|---|---|---|---|
| AAPL | 2019-01-02 | 746.08 | 2019-02-01 | 787.23 | 784.81 | +0.31% |
| MSFT | 2019-01-02 | 780.36 | 2019-02-01 | 802.34 | 801.21 | +0.14% |
| XOM | 2019-01-02 | 288.92 | 2019-02-01 | 310.52 | 310.33 | +0.06% |

`error_pct` is the estimate over the new snapshot, minus one, in percent. The estimate misses changes in the share count during the month (buybacks, issuance) and counts a dividend as return, while the snapshot, a price times a share count, does not; the logged prices are also rounded to cents. Each re-anchor steps the daily cap by that error.

Between each anchor and its re-anchor the adjusted and the unadjusted price moved by the same ratio to within 0.012%, inside the rounding of the logged prices, so no dividend or split fell in between. The share count implied by the snapshots (`implied_share_change_pct`: the new snapshot over the anchor cap times the unadjusted price ratio, minus one) changed by −0.31% (AAPL), −0.14% (MSFT), −0.05% (XOM): that accounts for most of each error, and the rest is within the rounding of the logged prices.

## Consequence for this repository

Runs v1 to v3 ranked the universe and computed rank returns on the raw monthly field. On most days no rank's cap had changed, so most daily rank returns were exactly zero, and on the day the snapshot changed they carried a month of price movement at once. Those runs are kept in `../../superseded/` as a record. v4 (`cap_source = "rolled"`, the default) rolls each company's reported cap forward daily with `rank_space.DailyCaps` and forms ranks and rank returns on that value.

## EBITDA growth

`ebitda_growth_monthly.csv`: `year`, `month`, `median_one_year`, `p90_abs_one_year`. The stat-arb strategy does not use this field; the probe measured it for the DCF repository (automated-dcf-point-in-time). At the first data point of each month the probe takes `ebitda_growth.one_year` of every name it holds (missing, NaN and zero values left out) and plots the median and the 90th percentile of the absolute value.

The monthly median lies between 0.102 and 0.144 in 2012 and between 0.088 and 0.100 in 2019; the 90th percentile of the absolute value lies between 0.424 and 0.569. The field is a decimal fraction (0.10 means 10%).
