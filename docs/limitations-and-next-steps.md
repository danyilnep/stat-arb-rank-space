# Limitations and next steps

What the eight v4 backtest windows in this repository can and cannot say about the paper's
claim, and the work that would test it properly. The method is in
[methodology.md](methodology.md), the differences from the paper, with reasons, are in
[paper-mapping.md](paper-mapping.md), and the data and reproduction checks are in
[data-checks.md](data-checks.md).

## What this implementation cannot say

**It trades late, and not equally late every day.** A rank-space position is held on whichever
company occupies the rank when the orders fill, and kept until the next fill. When two companies
swap ranks, the book earns the old holder's return until then instead of the rank's; the paper
calls that divergence the latency cost (Eq. 2.3.6) and limits it by rebalancing every 225
minutes. Here it builds up over a day or more on every hand-over. On top of it the book has an
execution lag that the paper's scheme does not: each decision pass uses the previous trading
day's close, and its orders fill at the next open after a midnight pass or a session later after
a 16:00 pass, which is a quarter to a third of the passes in each window
([methodology.md](methodology.md#daily-timeline), [results/v4/timing.csv](../results/v4/timing.csv)).
The paper's weights, as booked here, earn from one close to the next with no lag. Across the
windows they made +40.40% to +123.34% before costs, and the traded book −9.96% to +9.10% after
costs at the same samples ([results/v4/summary.csv](../results/v4/summary.csv)). Fees were
2.96% to 5.46% of starting capital and the trading P&L before fees −5.96% to +14.38%
([results/runs.csv](../results/runs.csv)), so most of the gap is not fees. The algorithm does not
record the traded book's own rank-space P&L or the close behind each pass, so the remainder
cannot yet be split between the execution lag, the latency and the difference between the
traded book and the paper's weights.

**Turnover drives the cost.** On daily capitalisations the ranking can change order on any day,
and every hand-over of an open rank moves a leg from one company to another: two orders, each
paying 2 basis points of its value, and a move made after the rank changed. The v4 book turned
over 38.68% to 45.74% of its value a day, against 12.68% and 13.81% for the superseded v3
chunks, whose monthly capitalisations could reorder the ranking only when a snapshot changed.
The book's median gross exposure was 1.08 to 1.36 times equity, close to the paper's
$\Lambda = 1$, so the gap does not come from holding a smaller book.

**The order cap leaves each window about 20 months long, with gaps.** The free QuantConnect node
stops a backtest at 10,000 orders, and at this turnover the book sends 21.5 to 25.3 orders a
trading day, of which 5.9% to 7.3% were cancelled and re-sent (exits from a 16:00 pass replaced
by the next pass; they count toward the cap). Seven of the eight windows stopped at the cap
after 18.8 to 22.0 months; the 2024 window ran the full year
([methodology.md](methodology.md#backtest-windows-and-the-order-cap)). No window trades the rest
of the year after 13 September 2012, 30 October 2014, 3 November 2016, 6 September 2019,
27 July 2021 or 19 September 2023, and the 2017 to 2018 window overlaps the 2018 to 2019 window
from 3 January to 9 October 2018. There is no statistic over the whole period: each window has
its own Sharpe ratio and probabilistic Sharpe ratio over about 20 months.

**QuantConnect's Sharpe ratio and PSR need reading with care.** The Sharpe ratio subtracts the
average rate of QuantConnect's risk-free model, while the account earned no interest on its
cash, so for this nearly self-financing book it charges the rate without crediting it: with
annual volatility of 2.3% to 4.9%, each percentage point of rate lowers the ratio by 0.20 to
0.43. The probabilistic Sharpe ratio is the probability that the Sharpe ratio exceeds 1, not 0.
The exports do not give the rate, so neither was recomputed without it
([README](../README.md#v4-windows-coverage-and-gaps)).

**The daily capitalisation is rolled, not observed.** QuantConnect's Morningstar `market_cap` is
a month-end snapshot, so v4 rolls it forward with the adjusted price. That value counts a
dividend as return from its ex-date until the next snapshot, then steps back down; each monthly
re-anchor moves a company's capitalisation by the anchoring error, 0.06% to 0.31% for three
companies at one month-end; and a company seen for the first time mid-month enters at a value up
to a month old ([data-checks.md](data-checks.md#the-rolled-forward-daily-capitalisation-v4)).
These artefacts enter the rank returns, and their effect on the before-cost series was not
measured. The rolled value was not compared with an independent daily source such as CRSP.

**It trades 100 ranks, not 500.** The paper's universe is the top 500. The top 100 are the
largest companies, and how often ranks change hands, and how strongly residuals mean-revert, may
differ lower down. The before-cost series here annualises to 31.08% to 60.17% a year over each
window, the same order of magnitude as the paper's Table 1, but calendar year by calendar year
it runs 26.04 to 35.82 points above Table 1 in the first years of the 2018, 2020 and 2022 windows
and 11.39 to 28.57 points below it in the part years 2012, 2014 and 2016
([paper-mapping.md](paper-mapping.md#what-the-paper-reports-and-what-this-repository-finds)).
Whether the universe, the data or something else accounts for that is not known.

**It has no intraday data, and its daily timing is uneven.** Signals use the previous trading
day's close; orders fill at the next open, or a session later when the pass runs at 16:00. The
paper's weights are set at a close and held from it, so the overnight gap and, after a 16:00
pass, a whole session fall into the execution lag. In two passes, each on the Monday after a
pass dated on a Saturday, no new universe selection had run, so a row of zero rank returns
entered the 252-day window ([methodology.md](methodology.md#daily-timeline)). The algorithm does
not log the close behind each pass, so this was established from the order timestamps and the
selection's schedule rather than observed directly.

**It has no neural network.** The paper's positive after-cost result, 35.68% a year with a Sharpe
ratio of 3.28, is for its convolutional and transformer network in rank space. The paper's
parametric strategy, which is what this repository implements, loses money after costs in every
year of the paper's own Table 2. Nothing here tests the network.

**It runs a single cost level.** Every run charges 2 basis points of traded value, with no
slippage and no borrow fee, and there is one run per window. There is no sensitivity analysis on
the cost, the leg size, the thresholds or the windows. The paper reports that its network stops
being profitable at 5 basis points (§3.7); this repository has not measured where its own book
breaks even, if anywhere.

**Other gaps.** The SPY hedge stands in for the rank factor without estimating each company's
beta to SPY. The state machine does not cap the number of open ranks; at 2.5% legs the margin
limit rarely binds (0 to 35 rejected orders per window), but nothing prevents it.

## Next steps

**One decision per session, logged.** Schedule one decision a session (for example before the
open, after the universe selection) instead of acting at the first data event of each calendar
date, and log the close behind each decision's rank returns. That makes the execution lag the
same every day, removes the cancelled and re-sent exits, and shows directly whether any zero or
two-day row of rank returns entered the window.

**Intraday rebalancing on a paid node.** Run Algorithm 4 as the paper writes it: build 1-minute
capitalisations for the ranked names, and every 225 minutes move each rank's weight to the
company that holds the rank. This needs minute data for about 530 names over several years,
which means a paid QuantConnect node or a local LEAN run with licensed data; either one also
removes the 10,000-order cap and with it the coverage gaps. Record the latency cost and the
spread cost separately, as in Eq. 2.3.6.

**500 ranks.** Set `n_ranks` to 500 and keep everything else fixed, then compare the before-cost
series with the 100-rank run year by year. Splitting the P&L into rank buckets (1 to 100 and 101
to 500) would show where the paper's before-cost return comes from, and whether the gap between
this repository and Table 1 from 2018 on is a universe effect.

**CRSP-quality daily capitalisations.** Replace the rolled Morningstar value with daily
capitalisations from daily share counts, such as CRSP's, or at least compare the two on a sample
of dates and measure what the dividend and re-anchor steps contribute to the before-cost series,
for example by rolling with a price adjusted for splits only, or by zeroing the rank returns on
re-anchor days, and reporting the series both ways.

**The CNN plus transformer policy with walk-forward training.** Implement the paper's network
(two convolutional layers with 8 channels and kernel 2, one transformer encoder layer with 4
heads and dropout 0.25) on the 60-day cumulative residual path of each rank, with the
mean-variance objective ($\gamma = 2$, 24-day windows). Train it offline and walk forward:
hyper-parameters once a year on days $t-1000$ to $t-60$ with validation on $t-59$ to $t-1$, then
quarterly retraining on days $t-500$ to $t-1$, never touching the evaluation period. Save the
trained weights, not only the configuration, and load them into the algorithm for each quarter.

**A turnover-aware mapping from ranks to names.** Log the traded book's own rank-space P&L next
to the paper-weights series, and attribute the realised P&L to fees, execution lag, latency and
the hedge. Then
test mappings that trade less: move a leg only when a rank has changed hands for more than a
day, or hold a rank's weight across a small band of neighbouring companies. Run each at 2 and 5
basis points, with one sensitivity grid on leg size, open and close thresholds and the $\tau$
filter.
