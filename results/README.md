# Results

Every QuantConnect backtest behind this repository, as exported (apart from the one docstring paragraph described under Provenance), plus the tables derived from them; `checks/backtest_lists.csv` accounts for every backtest in the projects involved, including the three discarded probe versions that are not published (Backtest lists below). `analysis/build_results.py` writes everything here except `raw/`, `provenance/` and the `qc_report.html` files, which it copies in with `--import-from`; `analysis/make_figures.py` draws `figures/` from the CSV files.

## Current version: v4

v4 ranks companies on a daily capitalisation, the monthly Morningstar value rolled forward with each company's adjusted price (`rank_space.DailyCaps`, `cap_source = "rolled"`), and holds a leg of 2.5% of equity per open rank. It ran in eight windows, each from 1 January of its start year, on $1,000,000. `v4/summary.csv` has one row per window:

| Window | Folder | First fill | Last fill | Months | Net | Sharpe | Max drawdown | Fees | Fees, % of start | Turnover per day | Paper weights, before costs | Annualised | Realised, after costs | Order cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2011 to 2012 | `v4/2011_2012/` | 2011-01-03 | 2012-09-13 | 20.3 | −8.460% | −1.430 | 9.8% | $50,811 | 5.08% | 41.71% | +80.63% | +41.7% | −8.46% | hit 2012-09-14 |
| 2013 to 2014 | `v4/2013_2014/` | 2013-01-02 | 2014-10-30 | 21.9 | −6.042% | −1.332 | 8.3% | $50,980 | 5.10% | 39.08% | +63.56% | +31.1% | −6.18% | hit 2014-10-31 |
| 2015 to 2016 | `v4/2015_2016/` | 2015-01-02 | 2016-11-03 | 22.0 | −0.409% | −0.368 | 4.0% | $52,385 | 5.24% | 38.68% | +82.74% | +38.8% | −0.03% | hit 2016-11-04 |
| 2017 to 2018 | `v4/2017_2018/` | 2017-01-03 | 2018-10-09 | 21.2 | +2.301% | −0.387 | 6.0% | $50,004 | 5.00% | 39.71% | +71.80% | +36.0% | +1.78% | hit 2018-10-10 |
| 2018 to 2019 | `v4/2018_2019/` | 2018-01-03 | 2019-09-06 | 20.1 | +8.920% | 0.315 | 3.3% | $54,628 | 5.46% | 42.08% | +96.21% | +49.9% | +9.10% | hit 2019-09-09 |
| 2020 to 2021 | `v4/2020_2021/` | 2020-01-02 | 2021-07-27 | 18.8 | −9.963% | −0.993 | 10.3% | $49,654 | 4.97% | 45.74% | +99.76% | +55.6% | −9.96% | hit 2021-07-28 |
| 2022 to 2023 | `v4/2022_2023/` | 2022-01-04 | 2023-09-19 | 20.5 | −0.919% | −0.847 | 9.7% | $52,265 | 5.23% | 41.54% | +123.34% | +60.2% | −0.92% | hit 2023-09-20 |
| 2024 | `v4/2024/` | 2024-01-03 | 2024-12-31 | 11.9 | −8.928% | −2.761 | 11.2% | $29,644 | 2.96% | 41.28% | +40.40% | +41.2% | −8.78% | not reached |

Net, Sharpe, maximum drawdown, fees and turnover are QuantConnect's statistics up to the day each window stopped. "Paper weights, before costs" is the last value of the algorithm's "Rank vs name" chart: the cumulative P&L of the paper's own L1-normalised weights on rank-space returns, before costs, from the first trading day. "Annualised" compounds it over the days from the first fill to that sample. "Realised, after costs" is the traded book's equity change at the same sample. QuantConnect's Sharpe ratio subtracts the average rate of its risk-free interest-rate model, while the account earned no interest on its cash, and its probabilistic Sharpe ratio (`psr_pct`) is the probability that the Sharpe ratio exceeds 1, not 0 (see the main README).

Across the windows the paper's weights made +40.4% to +123.3% before costs, and the traded book −10.0% to +9.1% after costs at the same sample (net −10.0% to +8.9% at the stop). The book turned over 38.7% to 45.7% of its value a day, because ranks change hands between companies as prices move, and paid $29,644 to $54,628 in fees per window at 2 basis points.

Seven of the eight windows stopped at QuantConnect's 10,000-order cap; the 2024 window ran to the configured end. The two-year windows covered 18.8 to 22.0 months of trading each. No v4 window traded in these spans: 14 September to 31 December 2012, 31 October to 31 December 2014, 4 November to 31 December 2016, 7 September to 31 December 2019, 28 July to 31 December 2021 and 20 September to 31 December 2023. The 2017 to 2018 window overlaps the 2018 to 2019 window from 3 January to 9 October 2018.

Rejected orders were rare in v4: 0 to 35 per window (`orders_invalid` in `v4/summary.csv`). Cancelled orders were not: 389 to 735 per window, 5.9% to 7.3% of each window's orders, and they count toward the order cap (Order timing below).

## Order timing

`v4/timing.csv` has one row per window, counted from its `orders.csv` in New York time. A decision pass is one submission time: the algorithm acts once per calendar date, at the first data event QuantConnect delivers for that date. 25.5% to 33.6% of each window's passes were submitted at 16:00 (13:00 on early-close days), the rest at 00:00. Every pass ranks on the latest universe selection, which QuantConnect runs at midnight after each trading day on that day's close (`checks/data/`), so the signal of a pass on date D uses the close of the trading day before D. Orders from a midnight pass fill at the open of D; orders from a 16:00 pass fill at the next trading day's open, one session later. As a result 16.8% to 20.9% of each window's trading days had no fill at the open and 17.2% to 20.9% received the orders of two passes, and 20.1% to 28.6% of filled orders came from a 16:00 pass.

Of the 5,001 cancelled orders, 4,996 were sent by a 16:00 pass, and for 4,999 the next pass sent a new order for the same company before the first had filled. Passes dated on a day the exchange was closed: 1 in the 2020 to 2021 window and 1 in the 2022 to 2023 window. Two passes (`passes_repeating_a_close`) each came after another pass with no trading day in between, so no new universe selection ran before them: each ranked on the same capitalisations as the pass before and added a row of zero rank returns to the 252-day window. The order lists show only passes that sent orders. Trading days are NYSE sessions from the first to the last fill, by the pandas holiday rules in `build_results.py` plus the closures of 29 and 30 October 2012 and 5 December 2018; every fill falls on one.

## Calendar years

`v4/calendar_years.csv` splits each window's paper-weights series into calendar years, the unit of the paper's Table 1. Each year runs from the first fill, or from the previous year's last sample, to the year's last sample; the return over it is compounded and annualised as the paper's Algorithm 5 does, to the power 252 over the NYSE sessions covered. `table1_pct` is the paper's Table 1 figure for that year (arXiv:2410.06568v1, rank space, parametric model, before costs) and `difference_pts` the annualised figure minus it. Of the 13 window-years with a Table 1 figure, 9 are above it, by 1.64 to 35.82 points, and 4 below, by 3.25 to 28.57 points:

| Window | Year | Part | From | To | Sessions | Cumulative | Annualised | Table 1 | Difference |
|---|---|---|---|---|---|---|---|---|---|
| 2011 to 2012 | 2011 | whole | 2011-01-03 | 2011-12-28 | 250 | +50.03% | +50.52% | 40.14% | +10.38 |
| 2011 to 2012 | 2012 | part | 2011-12-28 | 2012-09-14 | 180 | +20.39% | +29.67% | 41.06% | −11.39 |
| 2013 to 2014 | 2013 | whole | 2013-01-02 | 2013-12-27 | 250 | +30.82% | +31.10% | 27.92% | +3.18 |
| 2013 to 2014 | 2014 | part | 2013-12-27 | 2014-10-28 | 210 | +25.03% | +30.74% | 43.82% | −13.08 |
| 2015 to 2016 | 2015 | whole | 2015-01-02 | 2015-12-29 | 250 | +43.01% | +43.42% | 41.78% | +1.64 |
| 2015 to 2016 | 2016 | part | 2015-12-29 | 2016-11-03 | 215 | +27.78% | +33.29% | 61.86% | −28.57 |
| 2017 to 2018 | 2017 | whole | 2017-01-03 | 2017-12-28 | 250 | +27.09% | +27.33% | 30.58% | −3.25 |
| 2017 to 2018 | 2018 | part | 2017-12-28 | 2018-10-08 | 195 | +35.19% | +47.64% | 27.78% | +19.86 |
| 2018 to 2019 | 2018 | whole | 2018-01-03 | 2018-12-28 | 249 | +53.03% | +53.82% | 27.78% | +26.04 |
| 2018 to 2019 | 2019 | part | 2018-12-28 | 2019-09-03 | 170 | +28.22% | +44.55% | 41.42% | +3.13 |
| 2020 to 2021 | 2020 | whole | 2020-01-02 | 2020-12-28 | 250 | +60.27% | +60.88% | 25.06% | +35.82 |
| 2020 to 2021 | 2021 | part | 2020-12-28 | 2021-07-27 | 145 | +24.64% | +46.63% | 37.60% | +9.03 |
| 2022 to 2023 | 2022 | whole | 2022-01-04 | 2022-12-29 | 249 | +70.58% | +71.68% | 36.79% | +34.89 |
| 2022 to 2023 | 2023 | part | 2022-12-29 | 2023-09-19 | 180 | +30.93% | +45.83% | not in the paper | |
| 2024 | 2024 | whole | 2024-01-03 | 2024-12-27 | 249 | +40.40% | +40.97% | not in the paper | |

Each window folder holds `statistics.json`, `equity.csv`, `rank_vs_name.csv`, `orders.csv` and `trades.csv` (described under Files below). All eight windows ran the same code: `main.py` and `rank_space.py` with the SHA-256 as run on QuantConnect in `runs.csv` (`code_sha256_as_run`, `rank_space_sha256_as_run`). The published copies are stored under `code` in each raw export, with their own hashes in `code_sha256_published` and `rank_space_sha256_published` (Provenance below).

## Superseded: v1 to v3

v1 to v3 formed ranks and rank-space returns from `Fundamental.market_cap` as reported. That field is a month-end snapshot held for the whole following month: in the probe of `checks/data/`, from February to December 94.7% to 95.7% of the day-to-day comparisons in a month found a top-100 company's cap unchanged (January, when the probe starts, has no month boundary), and in the cap probe the reported value of AAPL, MSFT and XOM changed once, on 1 February 2019, over six weeks. So in v1 to v3 most daily rank returns were exactly zero and the rest carried a month of movement on one day. The rank-space signal those runs traded, and the paper-weight P&L they report, are not the daily rank-space quantities of the paper. The runs are kept as a record of what was run:

| Run | Folder | Configured | Last fill | Order cap hit | Net | Sharpe | Fees | Orders filled / rejected | Paper weights, before costs |
|---|---|---|---|---|---|---|---|---|---|
| v3, 2011 to 2017 chunk | `superseded/v3_2011_2017/` | 2011-01-01 to 2017-12-31 | 2017-02-02 | 2017-02-10 | +0.675% | −0.149 | $56,728 | 4,976 / 4,473 | +39.18% |
| v3, 2018 to 2024 chunk | `superseded/v3_2018_2024/` | 2018-01-01 to 2024-12-31 | 2024-02-02 | 2024-02-06 | +24.435% | 0.077 | $72,130 | 5,438 / 4,093 | +5.41% |
| v2, legs renormalised daily | `superseded/v2_2018_2024/` | 2018-01-01 to 2024-12-31 | 2023-03-06 | 2023-03-07 | +9.342% | −0.084 | $54,939 | 9,457 / 0 | −0.40% |
| v1, dense paper weights on every rank | `superseded/v1_2010_2024/` | 2010-01-01 to 2024-12-31 | 2013-08-15 | 2013-08-16 | −11.166% | −0.692 | $32,513 | 9,778 / 0 | n/a |

v1 held the paper's dense weights on every rank, v2 renormalised the legs daily, and v3 held a fixed leg of 5% of equity per open rank. v3's legs asked for more gross exposure than QuantConnect's default margin allows, so about four orders in ten were rejected (`checks/margin/`). The superseded folders have the same files as the v4 windows plus `code/main.py`, the code QuantConnect ran; the v3 folders also have `yearly.csv` and `qc_report.html`. Both v3 chunks ran the same `main.py` (SHA-256 `6b42cfb3...` as run on QuantConnect); its published copy is `code/main.py` in either v3 folder.

## Checks

| Run | Key | Folder | Net | What it tests |
|---|---|---|---|---|
| v3 re-run, 2018 to 2024 | `rerun__sa_v3_2018` | `checks/reproduction/` | +24.124% | Refactored v3 code against the recorded v3 run |
| v3 control, recorded main.py, 2018 to 2024 | `control__sa_v3_2018_recorded_code` | `checks/reproduction/` | +24.124% | Recorded v3 `main.py`, re-run on the re-run's day and LEAN build |
| v4 code with v3 parameters, 2018 to 2024 | `check__v3_via_params_2018` | `checks/reproduction/` | +24.124% | v4 code with `cap_source=reported` and `leg_weight=0.05` |
| v3 re-run, 2011 to 2017 | `rerun__sa_v3_2011` | `checks/reproduction/` | +1.804% | Refactored v3 code against the recorded v3 run |
| v3 half legs, 2011 to 2017 | `sa__half_leg_2011` | `checks/margin/half_leg_2011_2017/` | +5.165% | v3 at a leg weight of 0.025, against the re-run at 0.05 |
| v3 half legs, 2018 to 2024 | `sa__half_leg_2018` | `checks/margin/half_leg_2018_2024/` | +16.148% | v3 at a leg weight of 0.025, against the re-run at 0.05 |

- `checks/reproduction/`: the re-run, the control and the v4 code with v3 parameters are identical to each other in every statistic, closed trade and order, so neither the refactor nor v4 changed v3's logic. All three differ from the run recorded on 22 September from the first MDT order on: MDT's fill prices changed by one constant factor between the two dates, and the two dates also ran on different LEAN builds.
- `checks/margin/`: at 0.05 legs QuantConnect rejected 44.6% and 40.9% of the orders; at 0.025, 3.10% and 0.03%. v4 uses 0.025.
- `checks/data/`: `market_cap` is a monthly snapshot (above); rolled forward with the adjusted price, it landed within 0.06% to 0.31% of the next snapshot in the cap probe.

## Backtest lists

`checks/backtest_lists.csv` lists every backtest QuantConnect holds in the five projects behind this repository: 36836415 (the strategy), 36924052 (the control re-run of the recorded v3 code), 36922759 (the reference runs), 36923739 (the `market_cap` probe), 36924577 (the cap probe). It comes from QuantConnect's `backtests/list` API with statistics, exported on 2026-09-25 and kept as `raw/backtest_lists.json.gz`. Columns: project id and name; backtest id, name and creation time (UTC); `completed` and `status` as QuantConnect reports them; the first line of any error; the parameters; QuantConnect's net profit, Sharpe ratio and drawdown (percent) as listed; `published_key`, the run's key in `runs.csv` or, for a data probe, in `checks/data/` (blank when the backtest is not published); and `note`, where the run's files are or why it is not published.

All 26 backtests completed and none records an error. The strategy's project 36836415 holds 17 backtests, and every one of them is a row of `runs.csv`: eight v4 windows, four superseded runs (v1, v2 and the two v3 chunks) and five checks. No strategy backtest is left out of `results/`. The list shows what QuantConnect held on the export date, so a backtest deleted before then would not appear in it. Of the nine backtests in the other four projects, five are published (the control, the SPY reference and the three data probes). The three discarded ones are the first versions of the two probes, and "basket 2023" in the reference project belongs to the DCF repository. For every published backtest the listed creation time, net profit, Sharpe ratio and drawdown equal those of its export; `build_results.py` stops if they differ, or if a listed backtest is neither published nor given a reason.

## Layout

```
results/
  README.md                      this file (generated)
  runs.csv                       one row per strategy, check and reference backtest
  raw/                           the QuantConnect exports, gzip-compressed, plus MANIFEST.csv
  provenance/code_hashes.json    SHA-256 of each exported code file, as run and as published
  v4/                            the current version
    summary.csv                  one row per window
    timing.csv                   when each window acted and when its orders filled
    calendar_years.csv           the paper weights per calendar year, against the paper's Table 1
    2011_2012/                   2011 window
    2013_2014/                   2013 window
    2015_2016/                   2015 window
    2017_2018/                   2017 window
    2018_2019/                   2018 window
    2020_2021/                   2020 window
    2022_2023/                   2022 window
    2024/                        2024 window
  superseded/                    v1 to v3, kept as a record
    v3_2011_2017/  v3_2018_2024/  v2_2018_2024/  v1_2010_2024/
  checks/
    reproduction/                recorded v3 against re-runs, a control and the v4 code
    margin/                      v3 at half the leg weight
    data/                        what Fundamental.market_cap does, and the rolled-forward cap
    backtest_lists.csv           every backtest in the projects involved, published or not
  reference/spy_2015_2019/       SPY buy and hold over the window of the 2024 backtest
```

## Files

| File | Content |
|---|---|
| `statistics.json` | QuantConnect's statistics, runtime, trade and portfolio statistics, the parameters, the backtest metadata and QuantConnect's analysis warnings, plus a `derived` block (order counts by status, first and last date traded, date the order cap was hit, LEAN build, SHA-256 of each code file as run on QuantConnect and as published) |
| `equity.csv` | The equity curve as QuantConnect sampled it (every few calendar days) |
| `rank_vs_name.csv` | v2 to v4: the paper's weights before costs against the realised book after costs, cumulative, every fifth trading day |
| `orders.csv` | Every order, including rejected ones (none for the SPY reference, whose export has no order list) |
| `trades.csv` | Every closed round trip (none for the SPY reference) |
| `yearly.csv` | v3 only: equity at the last sample of each year, the year's return and the paper weights' cumulative P&L at the same point |
| `code/main.py` | Superseded runs and the SPY reference: the code QuantConnect ran, as published in the raw export (Provenance below) |
| `qc_report.html` | v3 only: QuantConnect's own generated backtest report |

## Provenance

The backtests ran on QuantConnect's free tier in Danyil Nepyivoda's account and were exported through QuantConnect's web API on 2026-09-25: one JSON file per backtest (metadata, statistics, orders, closed trades, analysis, chart data, logs where the backtest wrote any, and the code of the project snapshot). The chart data of v1 to v3 was exported again in one file, because some of their chart series are empty in the per-backtest export; the later exports carry complete charts. `raw/` keeps the per-backtest files and the stat-arb slice of the chart file, gzip-compressed, plus `engines__original_runs.json.gz`, the server statistics (LEAN build) of the original runs, whose own exports do not record it, and `backtest_lists.json.gz`, the slice of QuantConnect's backtest lists (exported on 2026-09-25) for the five projects of this repository, re-serialised. The per-backtest files are as QuantConnect returned them except that, in the exports whose embedded code carried it, one docstring paragraph was rewritten to leave out the other team members' names; `provenance/code_hashes.json`, which is not a QuantConnect export, records the SHA-256 of each code file as run on QuantConnect and as published. `raw/MANIFEST.csv` records the SHA-256 of each uncompressed file and of its source file, the provenance file included; `build_results.py --check` verifies them, and the build stops if a published hash differs from the code in `raw/`.

LEAN builds (`lean_version` in `runs.csv`): v2.5.0.0.18116: `sa__v3_2011`, `sa__v3_2018`, `sa__v2`, `sa__v1`; v2.5.0.0.18126: `sa__v4_2011`, `sa__v4_2013`, `sa__v4_2015`, `sa__v4_2017`, `sa__v4_2018`, `sa__v4_2020`, `sa__v4_2022`, `sa__v4_2024`, `rerun__sa_v3_2018`, `control__sa_v3_2018_recorded_code`, `check__v3_via_params_2018`, `rerun__sa_v3_2011`, `sa__half_leg_2011`, `sa__half_leg_2018`, `audit__spy_2015_2019`.

The SPY reference ran in a separate project (`audit_benchmarks_main.py`, copied to `reference/spy_2015_2019/code/main.py`). It covers 1 January 2015 to 31 December 2019, the window of the 2024 backtest described in the main README, with $100,000.

## The order cap

QuantConnect's free tier stops a backtest at 10,000 orders: the order log ends at order 10,001, and QuantConnect's analysis records "You have exceeded maximum number of orders (10000)" on the date in `order_cap_hit`. All statistics, including the compounding annual return, cover only the period up to that stop. Rejected and cancelled orders count toward the cap. The v3 date chunks and the v4 windows exist because of it.

## Columns

`runs.csv` has one row per strategy, check and reference backtest. The three data probes (`probe2__2012`, `probe2__2019`, `capprobe2__2019`), which place no orders, are listed with their ids and LEAN build in `checks/data/README.md` instead. Percentages are in percent, money in US dollars:

| Column | Meaning |
|---|---|
| `key`, `label`, `folder` | Run key used in `raw/`, a readable label, the folder that holds the run's files |
| `version` | `v1` to `v4`; for checks, what was run (`v3 re-run`, `v3 control`, `v3 via v4 code`, `v3 half legs`); `reference` for SPY |
| `role` | `current` (v4), `superseded` (v1 to v3), `check` or `reference` |
| `project_id`, `backtest_id`, `created` | QuantConnect identifiers and the backtest's creation time (UTC) |
| `lean_version` | LEAN build the backtest ran on |
| `configured_start`, `configured_end` | The backtest window set in the code or parameters |
| `first_date_traded`, `last_date_traded` | New York dates of the first and last filled order |
| `order_cap_hit` | Date of QuantConnect's order-limit message; blank when the run did not reach it |
| `parameters` | QuantConnect project parameters for the run; `code defaults` when none were set |
| `net_profit`, `cagr`, `sharpe`, `psr`, `max_drawdown`, `beta` | QuantConnect statistics: net profit, compounding annual return, Sharpe ratio, probabilistic Sharpe ratio, maximum drawdown, beta to SPY |
| `orders` | QuantConnect's total order count |
| `orders_filled`, `orders_invalid`, `orders_canceled`, `orders_open_at_stop` | Orders by final status: filled; rejected by QuantConnect before reaching the market; cancelled; still submitted when the run stopped |
| `closed_trades`, `win_rate` | Closed round trips and the share of them with positive P&L |
| `total_fees`, `fees_pct_of_start` | Fees paid, and fees as a percentage of starting equity |
| `portfolio_turnover` | QuantConnect's average daily portfolio turnover |
| `start_equity`, `end_equity` | Equity at the start and when the run stopped |
| `paper_weights_before_costs` | Last value of the "Rank vs name" rank-space series, percent; blank where the run had no such chart |
| `code_sha256_as_run`, `rank_space_sha256_as_run` | SHA-256 of the UTF-8 text of `main.py` and `rank_space.py` as QuantConnect ran them, from `provenance/code_hashes.json`; blank where the run had no `rank_space.py` |
| `code_sha256_published`, `rank_space_sha256_published` | SHA-256 of the same files as published under `code` in the raw export; they differ from the `_as_run` column where one docstring paragraph was rewritten to leave out the other team members' names |

`v4/summary.csv`: `window`, `key`, `backtest_id`; `configured_start` and `configured_end`; `first_fill` and `last_fill` (New York dates of the first and last filled order); `months_covered` (days from first to last fill over 30.44); `net_profit_pct`, `cagr_pct`, `sharpe`, `psr_pct`, `max_drawdown_pct`, `beta`, `total_fees`, `turnover_per_day_pct` (QuantConnect statistics); `fees_pct_of_start`; `orders` and the counts by status; `closed_trades`; `last_sample` (date of the last "Rank vs name" point); `paper_weights_before_costs_pct` and `realised_after_costs_pct` at that sample; `paper_weights_annualised_pct` ((1 + p)^(365.25 / days) - 1 over the days from `first_fill` to `last_sample`); `order_cap_hit` (`yes` or `no`) and `order_cap_date`.

`v4/timing.csv`: `window`; `first_fill` and `last_fill`; `trading_days` (NYSE sessions from the first to the last fill); `passes` (distinct order submission times, New York), split into `passes_midnight` (00:00) and `passes_close` (16:00, or 13:00 on an early-close day), with `passes_close_pct`; `passes_on_closed_days` (passes dated on a day the exchange was closed); `passes_repeating_a_close` (passes with no trading day between them and the pass before, so no new universe selection); `opens_with_fills`, `opens_without_fills` and `opens_with_two_passes` (trading days on which orders of at least one, of no and of two passes filled); `orders_filled`, `filled_from_close_passes` and `filled_from_close_passes_pct`; `orders`, `orders_canceled` and `orders_canceled_pct`; `canceled_from_close_passes`; `canceled_replaced_at_next_pass` (cancelled orders for whose company the next pass sent a new order).

`v4/calendar_years.csv`: `window`, `year`; `part` (`whole` when the year's last sample is in December, else `part`); `from_date` and `to_date` (the span, see Calendar years); `trading_days` (NYSE sessions in the span, the first fill counted, a starting sample not); `paper_weights_cumulative_pct` and `paper_weights_annualised_pct` ((1 + p)^(252 / trading_days) - 1); `table1_pct` (blank for years outside the paper's 2007 to 2022); `difference_pts` (annualised minus Table 1, percentage points).

`equity.csv`: `date` (New York date of the sample), `equity` (close of QuantConnect's equity candle), `spy_benchmark` (QuantConnect's benchmark series: SPY price adjusted for splits and dividends), `drawdown_pct` (percent below the running peak), `exposure_long` and `exposure_short` (long and short holdings as a fraction of equity, the short side negative), `portfolio_turnover` (the turnover sample QuantConnect stamps one day after the equity sample, as a fraction of equity; a point sample, zero on days without trading). Columns a run's export does not have are left out.

`rank_vs_name.csv`: `rank_space_paper_weights_before_costs_pct` is the cumulative before-cost P&L of the paper's L1-normalised weights on rank-space returns, computed inside the algorithm; `name_space_realised_after_costs_pct` is the book's equity change since the first trading day, after fees. Both in percent, sampled every fifth trading day.

`orders.csv`: `submitted_utc`, `filled_utc` (blank if never filled), `type` (all MarketOnOpen), `fill_price`, `value` (signed, US dollars), `fee`, `status` (Filled, Invalid = rejected, Canceled, Submitted), `tag` (`closed` marks an exit; a few orders carry `left universe`, v1's `Liquidated` or a QuantConnect message).

`trades.csv`: one closed round trip per row with entry and exit times (UTC) and prices, `profit_loss` before fees, `total_fees`, maximum adverse and favourable excursion (`mae`, `mfe`), `duration_days` and the ids of the orders involved.

`yearly.csv`: `equity_date` is the last equity sample of the year (the last year is partial, up to the stop); `year_return_pct` is measured from the previous row, the first from starting equity; the paper-weights and name-space columns are the last "Rank vs name" values of the same year.

## Rebuild

Python 3.11 with the package versions pinned in `requirements-dev.txt`, the versions that built the committed files (`--check` compares text byte for byte, so another pandas or numpy release could format a number differently):

```
python analysis/build_results.py           # rebuild everything here from raw/
python analysis/build_results.py --check   # verify raw/ and compare with a fresh rebuild
python analysis/make_figures.py            # redraw figures/ from the CSV files
```
