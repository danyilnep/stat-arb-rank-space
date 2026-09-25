# Methodology

This document describes what the algorithm in [`main.py`](../main.py) does, in the order it
does it at each daily decision pass. It describes behaviour, not code layout, so it stays valid if the numerical
steps move into a helper module. Equation and algorithm numbers refer to Li and Papanicolaou,
*Statistical Arbitrage in Rank Space*, [arXiv:2410.06568v1](https://arxiv.org/html/2410.06568v1).
Where this implementation departs from the paper, the reason is in
[paper-mapping.md](paper-mapping.md).

## Daily timeline

The algorithm subscribes to daily data and acts on the first data event of each calendar date
(New York time), ignoring later events on the same date. Each such decision pass does four
things:

1. Rank the 100 largest companies by daily market capitalisation, the monthly Morningstar
   value rolled forward with each company's adjusted price, as computed by the latest universe
   selection.
2. Append the new rank returns to a rolling 252-day buffer and book the previous pass's paper
   weights against them.
3. Once the warm-up is over and the buffer is full, run Algorithm 1 and Algorithm 2.
4. Send orders. The market is closed when this runs, so QuantConnect submits them as
   market-on-open orders (`MarketOnOpen` in the exported order lists), filled at the next
   session's opening price.

**When a pass runs, and what it sees.** QuantConnect runs the universe selection at midnight
after each trading day, on that day's close: the cap probe's log, written from the selection,
shows on a line dated D the close of the trading day before D
([data-checks.md](data-checks.md#fundamentalmarket_cap-is-a-month-end-snapshot)). The first data
event of a date comes either at 00:00 or at the 16:00 close (13:00 on the six early-close days
in the windows: 3 July of 2013, 2014, 2018 and 2023, 23 November 2018 and 24 December 2024).
The order lists of the v4 windows, counted in
[results/v4/timing.csv](../results/v4/timing.csv), show both:

| | Midnight pass | 16:00 pass |
|---|---|---|
| Share of passes per window | 66.4% to 74.5% | 25.5% to 33.6% |
| Close the signal uses | the trading day before D | the trading day before D, although D's close is already in |
| Orders fill at | the open of D | the open of the next trading day |
| Lag from the signal's close to the fill | the overnight gap | the overnight gap, the session of D and a second overnight gap |

So the execution lag is not uniform. A 16:00 pass on D moves its orders to the next open: if the
pass before it ran at midnight, the open of D gets no orders, and if the pass after it runs at
midnight, the next open gets the orders of both passes. In each window 16.8% to 20.9% of the
trading days had no fill at the open and 17.2% to 20.9% received the orders of two passes, and
20.1% to 28.6% of the filled orders came from a 16:00 pass. An exit sent by a 16:00 pass has not filled yet when a midnight pass follows; if
that pass still wants the position closed, `liquidate` cancels the open order and sends a new
one. That is why 5.9% to 7.3% of each window's orders were cancelled, all but five of them sent
by a 16:00 pass ([Backtest windows](#backtest-windows-and-the-order-cap)).

The before-cost series of the paper's weights has no such lag. The weights formed at one pass
are booked against the rank returns of the next pass, that is from one close to the next.

A pass on a date when the exchange was closed happened twice, on Saturday 4 April 2020 and on
Saturday 24 September 2022, each at midnight after the Friday's selection. The pass on the
following Monday had no new selection before it, so it ranked on the same capitalisations and
appended a row of zero rank returns to the buffer. Every other pair of consecutive passes in the
order lists has a trading day between them, so each of those passes saw a new close. Two
limits: the order lists show only passes that sent orders, and that a midnight pass sees the
selection of the same midnight follows from LEAN's order of events (the selection before
`on_data` at the same time step); the algorithm does not log the close behind each pass.

## Universe and ranks

**Selection.** At midnight after each trading day, on that day's close, QuantConnect's
fundamental universe (point-in-time Morningstar data, delisted companies included) is filtered
to securities with fundamental data, a positive market capitalisation, a price above 1 USD and
the primary share class.

**Daily capitalisation.** Morningstar's `Fundamental.market_cap` is a month-end snapshot: it
holds the previous month-end close times the shares then outstanding for a whole month
([data-checks.md](data-checks.md)). For every company that passes the filter, `DailyCaps` in
`rank_space.py` rolls that value forward with the company's split- and dividend-adjusted price,

$$
c_t = C_a \, \frac{P_t}{P_a} ,
$$

where $C_a$ is the last reported value and $P_a$ the adjusted price on the day it was first
seen. When the reported value changes, normally on the first trading day of a month, the company
is re-anchored at the new value. The 130 largest companies by $c_t$ are subscribed: the 100
ranks plus a buffer of 30, so that a company just below rank 100 already has data on the day it
moves up. This is the default, `cap_source = "rolled"` (v4). With `cap_source = "reported"` the
raw monthly field is used instead, as in the superseded runs v1 to v3.

**Ranking.** Among the subscribed companies that have data and a positive daily capitalisation
from that day's selection, the 100 largest are sorted in descending order. Rank 1 is the largest
company that day. If fewer than 100 qualify, the day is skipped and the next valid day's return
spans both days.

**Rank returns.** With $c_{(k),t}$ the capitalisation at rank $k$ on day $t$, whichever company
holds it (Eq. 2.1.9):

$$
\tilde r_{k,t} = \frac{c_{(k),t}}{c_{(k),t-1}} - 1, \qquad k = 1, \dots, 100 .
$$

In the paper this is a change in capitalisation, which moves with the share count as well as
the price and excludes dividends. The rolled daily value departs from that in two ways: share
counts change only when a new monthly snapshot arrives, and a dividend counts as return from its
ex-date until that snapshot, when the capitalisation steps back down. Each re-anchor therefore
moves a company's capitalisation by the anchoring error, which was 0.06% to 0.31% in the check
in [data-checks.md](data-checks.md#the-rolled-forward-daily-capitalisation-v4).

Returns are stored from the first day data arrives, warm-up included. The warm-up is 403
calendar days ($1.6 \times 252$), which fills the 252-day buffer before the start date, so
trading starts on the first trading day of the start year.

## Algorithm 1: market decomposition

Let $R$ be the $252 \times 100$ matrix of stored rank returns, oldest row first, and $r_f$ the
annual rate from QuantConnect's risk-free interest-rate model on the day. Excess returns are

$$
Z = R - \frac{r_f}{252}, \qquad \text{with missing values set to } 0 ,
$$

with today's rate subtracted from every row of the window.

**Factor.** The single factor is the first principal component of the 252-day window. With the
column-demeaned matrix decomposed as $Z - \bar Z = U \Sigma V^\top$, the factor weights are the
first right singular vector:

$$
\omega = v_1^\top \in \mathbb{R}^{1 \times 100}, \qquad \lVert \omega \rVert_2 = 1 .
$$

The demeaning is this implementation's choice: Algorithm 1 and the paper's Eq. 5.1.1 decompose
the excess returns themselves, uncentred. Its effect on $\omega$ was not measured.

**Loadings.** On the last 60 rows $Z_L$ (a $60 \times 100$ matrix, rows $z_s$), the factor return
is $F_s = \omega z_s$, and each rank is regressed on it with an intercept by ordinary least
squares:

$$
z_{k,s} = \alpha_k + \beta_k F_s + e_{k,s}, \qquad s = t-59, \dots, t .
$$

**Transformation matrix and residuals** (Eq. 2.1.11 and 2.1.12):

$$
\Phi = I - \beta \omega \in \mathbb{R}^{100 \times 100}, \qquad
\epsilon_s = \Phi z_s = z_s - \beta F_s .
$$

The residual keeps the regression intercept: $\epsilon_{k,s} = \alpha_k + e_{k,s}$.

Two properties follow from fitting $\beta$ on $F = \omega z$ over the same 60 days. First,
$\omega \beta = \mathrm{Cov}(\omega z, F) / \mathrm{Var}(F) = 1$ exactly, so

$$
\Phi \beta = 0, \qquad \omega \Phi = 0, \qquad \Phi^2 = \Phi ,
$$

which makes $\Phi$ an oblique projection that removes the factor, and any equity weights of the
form $\Phi^\top w$ have zero loading on $\beta$ (Eq. 2.1.14). Second, the scale and sign of
$\omega$ do not matter: multiplying $\omega$ by $c$ multiplies $F$ by $c$ and $\beta$ by $1/c$,
leaving $\beta \omega$ unchanged. The paper's appendix scales $\omega$ by $1/\sigma_1$; the
resulting $\Phi$ is the same.

## Algorithm 2: Ornstein-Uhlenbeck signal

**Cumulative residuals.** For each rank, the 60 daily residuals are summed into a path
(Eq. 2.2.3, the rank-space form of Eq. 2.2.2):

$$
x_{k,j} = \sum_{i=1}^{j} \epsilon_{k,\,t-60+i}, \qquad j = 1, \dots, 60 .
$$

**AR(1) fit.** Each path is fitted by ordinary least squares on its 59 consecutive pairs, the
regression of Appendix 5.2 (Eq. 5.2.1) without its first pair: as printed, Eq. 5.2.1 runs over
$\alpha = 1, \dots, 60$, and its first pair starts from $x_{k,0} = 0$, the empty sum:

$$
x_{k,j+1} = a_k + b_k x_{k,j} + \xi_{k,j+1}, \qquad j = 1, \dots, 59 ,
$$

$$
b_k = \frac{\sum_j (x_{k,j} - \bar x^{-}_k)(x_{k,j+1} - \bar x^{+}_k)}{\sum_j (x_{k,j} - \bar x^{-}_k)^2},
\qquad a_k = \bar x^{+}_k - b_k \bar x^{-}_k ,
$$

where $\bar x^{-}_k$ and $\bar x^{+}_k$ are the means of the first 59 and the last 59 points.
The residual variance $\hat\sigma^2_{\xi,k}$ is the sample variance of the fitted $\xi$ with two
degrees of freedom removed (divided by 57).

**OU parameters.** With a time step of one trading day, the AR(1) coefficients map to the OU
process $dX = \frac{1}{\tau}(\mu - X)\,dt + \sigma\,dB$ (Eq. 2.2.4) as in Eq. 5.2.2:

$$
\tau_k = -\frac{1}{\ln b_k} \ \text{trading days}, \qquad
\mu_k = \frac{a_k}{1 - b_k}, \qquad
\sigma_{\mathrm{eq},k} = \sqrt{\frac{\hat\sigma^2_{\xi,k}}{1 - b_k^2}} .
$$

The paper writes the speed as $\kappa = -252 \ln b$ per year; $\tau = 252 / \kappa$ trading days
is the same quantity. $\sigma_{\mathrm{eq}}$ is the equilibrium standard deviation of the path,
the $\sigma$ of the right-hand block of the paper's Eq. 5.2.2. That equation defines $\sigma$ two
ways that disagree. Its left-hand block,
$\mathrm{Var}(\xi) = \sigma^2 (1 - e^{-2\kappa \Delta t}) / (2\kappa)$, makes $\sigma$ the
diffusion coefficient of Eq. 2.2.4; its right-hand block,
$\sigma = \sqrt{\mathrm{Var}(\xi) / (1 - b^2)}$, makes it the equilibrium standard deviation,
which is that coefficient divided by $\sqrt{2\kappa}$. This implementation uses the right-hand
block, as Avellaneda and Lee do. The choice sets the scale of every s-score against the 1.25 and
0.5 thresholds.

**s-score** (Eq. 2.2.5):

$$
s_k = \frac{x_{k,60} - \mu_k}{\sigma_{\mathrm{eq},k}} .
$$

A fit counts as valid only when $0 \lt b_k \lt 1$ and $\hat\sigma^2_{\xi,k} \gt 0$. Otherwise the
rank has no s-score that day.

## State machine

Each rank carries a residual-space position $w^\epsilon_k \in \lbrace -1, 0, +1 \rbrace$ from
one day to the next. The update, applied to every rank every day:

| Current position | Condition | New position |
|---|---|---|
| any | fit not valid | 0 (a held position is closed) |
| 0 | $\tau_k \lt 30$ and $s_k \lt -1.25$ | +1, long the residual |
| 0 | $\tau_k \lt 30$ and $s_k \gt 1.25$ | −1, short the residual |
| +1 or −1 | $\lvert s_k \rvert \lt 0.5$ | 0 |
| anything else | | unchanged |

Three consequences matter when reading the results. The 30-day filter on $\tau$
applies only at entry; a held position is not closed because $\tau$ has grown. A position never
flips directly from long to short. And because the close test uses $\lvert s \rvert$, a long
whose s-score jumps above +0.5 in one day stays open until the score comes back inside the band.
The paper's printed rule is compared with this one in [paper-mapping.md](paper-mapping.md).

Positions belong to ranks, not to companies. A long on rank 17 stays on rank 17 while companies
move through it.

## The paper's weights (computed, not traded)

The paper's equity weights (Algorithm 2, Eq. 2.2.10) are computed every day:

$$
w^{R}_t = \frac{\Phi_t^\top w^\epsilon_t}{\lVert \Phi_t^\top w^\epsilon_t \rVert_1} .
$$

They are held from one pass to the next, against the rank returns from one close to the next,
with no costs, no interest on cash and no mapping to companies:

$$
P_{t+1} = P_t \left( 1 + (w^{R}_t)^\top \tilde r_{t+1} \right), \qquad P = 1 \text{ before the first trading day.}
$$

Gross exposure is 1 by construction, the paper's $\Lambda = 1$. $P - 1$ is plotted every five
trading days as the series "rank space, paper weights, before costs" on the custom chart
"Rank vs name", next to the realised return of the account, "name space, realised, after
costs". The first series measures the signal; the second measures what the traded book earned.

## Traded weights and the SPY hedge

The traded book is not $w^R$ (see [paper-mapping.md](paper-mapping.md) for why).

**Legs.** The company holding rank $k$ today gets a target weight of
$\lambda \, w^\epsilon_k$ of equity, with the leg weight $\lambda = 0.025$: 2.5% long, 2.5% short
or nothing. The superseded v3 used $\lambda = 0.05$; why it was halved is under
[Buying power](#execution) below.

**Hedge.** The legs carry an exposure of $\lambda \, \beta^\top w^\epsilon$ to the factor return
$F$. If every rank moved by the same market return $m$, the factor would move by
$m \sum_k \omega_k$. Treating SPY as that market return, the hedge weight is

$$
h = \operatorname{clip}\left( -\lambda \, (\beta^\top w^\epsilon) \sum_{k=1}^{100} \omega_k ,\ -0.5,\ 0.5 \right) .
$$

The product $(\beta^\top w^\epsilon) \sum_k \omega_k$ does not depend on the sign or scale of
$\omega$. The hedge treats the rank factor as the market; no company's own beta to SPY is
estimated.

The target gross exposure of the traded book is $\lambda$ times the number of open ranks plus
$\lvert h \rvert$. Nothing in the code caps the number of open ranks, so the target can exceed
what the account's margin allows (next section).

## Execution

At each decision pass the targets are the legs, plus SPY at weight $h$ when
$\lvert h \rvert \gt 0.02$. Then:

1. Every holding that is not a target is liquidated. This covers a rank that closed, a company
   that no longer holds an open rank because the rank changed hands, and SPY when the hedge is
   2% or smaller.
2. Every target is traded to its weight with QuantConnect's `set_holdings` when the gap between
   target and current weight (holdings value over total portfolio value) is above 1.5% for a
   company or 2% for SPY. Smaller drifts are left alone.

A company that leaves the 130-name subscription while held is liquidated at once. The setting
`minimum_order_margin_portfolio_percentage = 0` stops QuantConnect from dropping small orders.

**Buying power.** The account uses QuantConnect's default margin model, under which an order
needs about half its value as initial margin (the order errors of v3 quote, for example, 25,881
USD of initial margin for a 51,741 USD order). Gross exposure therefore tops out near twice
equity, and when the target book is larger the orders beyond that are rejected with status
Invalid. The code does not check for this: a rejected leg keeps its target and is sent again the
next day, and rejected orders count towards the 10,000-order cap
([results/README.md](../results/README.md#the-order-cap)).

At v3's 5% legs this happened on a large scale. In the exported order lists, 4,473 of the 10,001
orders of the 2011 chunk (backtest `52a7a3c0`) and 4,093 of the 10,001 orders of the 2018 chunk
(backtest `34bc2a26`) are Invalid, including 311 and 251 SPY hedge orders
([superseded/v3_2011_2017/orders.csv](../results/superseded/v3_2011_2017/orders.csv),
[superseded/v3_2018_2024/orders.csv](../results/superseded/v3_2018_2024/orders.csv), column
`status`), so the book v3 held was the state machine's book cut down to the margin limit, with
the hedge sometimes missing. The same v3 code at 2.5% legs had 3.10% and 0.03% of its orders
rejected ([data-checks.md](data-checks.md#margin-check)), and v4 uses 2.5%. The eight v4 windows
had 0 to 35 rejected orders each ([results/v4/summary.csv](../results/v4/summary.csv), column
`orders_invalid`), with a median gross exposure of 1.08 to 1.36 times equity.

Rank hand-overs generate orders even on days when no signal changes: when two companies swap
ranks, the leg moves from one to the other. That is the mechanism the paper calls rank
switching. On daily capitalisations the ranking can change order on any day, and the v4 windows
turned over 38.68% to 45.74% of equity per day. The v3 chunks, whose ranking could change order
only when a monthly snapshot changed, turned over 12.68% and 13.81%
([results/runs.csv](../results/runs.csv), column `portfolio_turnover`).

## Costs

Every fill, companies and SPY alike, pays a proportional fee of
$\text{price} \times \lvert \text{quantity} \rvert \times 2 \times 10^{-4}$, the paper's
$\eta = 2$ basis points. No slippage model and no borrow-fee model are set in the code, so fills
use QuantConnect's default fill model (the opening price for these market-on-open orders).

Two other costs are not charged as separate items; both are already inside the realised P&L,
because the book earns the returns of the companies it holds from one fill to the next, not the
rank returns $\tilde r$:

- Execution lag: orders fill at the open after the signal's close, or a session later after a
  16:00 pass ([Daily timeline](#daily-timeline)), while the paper's series books close to close.
  The paper's own P&L (Algorithm 4) starts from weights set at the end of day $t$ and has no such
  lag.
- Latency cost in the paper's sense, the first term of Eq. 2.3.6: the divergence between rank
  and name returns when ranks switch between two rebalancing points. The paper rebalances every
  225 minutes; here a leg moves to the new holder of its rank only at the next fill, a day or
  more later.

The gap between the two series on "Rank vs name" is fees plus these two plus the difference
between the traded book and $w^R$.

In the v4 windows the fees came to 2.96% to 5.46% of starting capital, and the trading P&L
before fees (end equity minus start plus fees) to −5.96% to +14.38% of starting capital
([results/runs.csv](../results/runs.csv)), while the paper's weights made +40.40% to +123.34%
before costs over the same windows. Fees are therefore a small part of the gap. The rest is the
execution lag, the latency and the difference between the traded book and $w^R$ together; the
algorithm does not record the traded book's own rank-space P&L, so they cannot be separated.

## Backtest windows and the order cap

QuantConnect's free tier stops a backtest at 10,000 orders
([results/README.md](../results/README.md#the-order-cap)). At about 40% turnover a day the v4
book sends 21.5 to 25.3 orders per trading day on average, and 5.9% to 7.3% of each window's
orders were cancelled before they filled, almost all of them exits from a 16:00 pass replaced by
the next pass ([Daily timeline](#daily-timeline)); cancelled and rejected orders count toward
the cap like filled ones ([results/v4/timing.csv](../results/v4/timing.csv)). A run therefore
reaches the cap after about 20 months. v4 was run in eight windows, each starting on 1 January
of `start_year` with its own warm-up and $1,000,000:

| Window | Configured end | First fill | Last fill | Months covered | Stopped by |
|---|---|---|---|---|---|
| 2011 to 2012 | 2017-12-31 | 2011-01-03 | 2012-09-13 | 20.3 | order cap, 2012-09-14 |
| 2013 to 2014 | 2014-12-31 | 2013-01-02 | 2014-10-30 | 21.9 | order cap, 2014-10-31 |
| 2015 to 2016 | 2016-12-31 | 2015-01-02 | 2016-11-03 | 22.0 | order cap, 2016-11-04 |
| 2017 to 2018 | 2018-12-31 | 2017-01-03 | 2018-10-09 | 21.2 | order cap, 2018-10-10 |
| 2018 to 2019 | 2024-12-31 | 2018-01-03 | 2019-09-06 | 20.1 | order cap, 2019-09-09 |
| 2020 to 2021 | 2021-12-31 | 2020-01-02 | 2021-07-27 | 18.8 | order cap, 2021-07-28 |
| 2022 to 2023 | 2023-12-31 | 2022-01-04 | 2023-09-19 | 20.5 | order cap, 2023-09-20 |
| 2024 | 2024-12-31 | 2024-01-03 | 2024-12-31 | 11.9 | configured end |

First and last fill are New York dates of the first and last filled order; months covered is the
days between them over 30.44 ([results/v4/summary.csv](../results/v4/summary.csv)). The 2011 and
2018 windows kept the configured ends of the v3 chunks and stopped at the cap like the others.
No window trades the rest of the year after each of these last fills: 13 September 2012,
30 October 2014, 3 November 2016, 6 September 2019, 27 July 2021 and 19 September 2023.
The 2017 to 2018 window overlaps the 2018 to 2019 window from 3 January to 9 October 2018. Each
window has its own statistics; there is none over the whole period.

## Parameters

Names in the last column are QuantConnect project parameters read by `main.py`; "fixed" means
the value is set in the code.

| Parameter | Paper | This implementation | Parameter name |
|---|---|---|---|
| Universe | Top 500 US stocks by capitalisation, re-selected daily (§3.1) | Top 100 by daily capitalisation, re-ranked daily; 130 subscribed | `n_ranks` = 100; buffer 30, fixed |
| Data | CRSP daily 1990 to 2022; Polygon.io 1-minute prices 2005 to 2022 (§3.1) | QuantConnect daily bars; point-in-time Morningstar `market_cap`, a month-end snapshot, rolled forward daily with the adjusted price | `cap_source` = rolled |
| Backtest period | January 2006 to December 2022; tables report 2007 to 2022 (§3.1, Tables 1 and 2) | Eight windows starting in January 2011, 2013, 2015, 2017, 2018, 2020, 2022 and 2024; the first seven ended by the order cap after 18.8 to 22.0 months, the 2024 window ran the full year | `start_year`, `end_year` |
| Risk-free rate | One-month Treasury bill, Kenneth French Data Library (§3.1) | QuantConnect's risk-free interest-rate model, divided by 252 | none |
| Factors in rank space | 1 (§3.1, Algorithm 1) | 1 | fixed |
| Factor (PCA) window | 252 days (Algorithm 1) | 252 days | `factor_window` = 252 |
| Loading window | 60 days (Algorithm 1) | 60 days | `loading_window` = 60 |
| Cumulative residual window $L$ | 60 days, same as the loadings (§3.1) | 60 days, same window | `loading_window` |
| OU estimation | AR(1) regression (Appendix 5.2) | AR(1) regression | none |
| Open threshold | 1.25 (Eq. 2.2.8) | 1.25 | `open_threshold` = 1.25 |
| Close threshold | 0.5 (Eq. 2.2.8) | 0.5, applied as $\lvert s \rvert \lt 0.5$ | `close_threshold` = 0.5 |
| Mean-reversion filter | $\hat\tau \lt 30$ days (Eq. 2.2.7) | $\tau \lt 30$ trading days, at entry | `max_tau_days` = 30 |
| Equity weights | $\Phi^\top w^\epsilon$, L1-normalised, $\Lambda = 1$ (Algorithm 2, Eq. 2.4.3) | Computed daily for the before-cost series only | none |
| Traded weights | same as above | 2.5% per open rank plus one SPY hedge capped at 50% (v3: 5%) | `leg_weight` = 0.025; cap 0.5, fixed |
| Rebalancing | Rank to name every 225 minutes intraday (§2.3, Algorithm 4, Fig. 13) | One decision pass per date on the previous close, filled at the next open or a session later ([Daily timeline](#daily-timeline)), with drift bands | `order_threshold` = 0.015, `hedge_threshold` = 0.02 |
| Transaction cost | $\eta$ = 2 bp of traded value, plus latency cost (Eq. 2.3.6) | 2 bp of traded value as a fee model; latency and execution lag inside realised P&L | `fee_bps` = 2 |
| Starting capital | $V_0 = 1$ (Algorithm 4) | 1,000,000 USD | fixed |
| Warm-up | not stated | 403 calendar days | fixed ($1.6 \times$ `factor_window`) |
