# Paper to implementation mapping

What Li and Papanicolaou specify in *Statistical Arbitrage in Rank Space*
([arXiv:2410.06568v1](https://arxiv.org/html/2410.06568v1), Stanford, October 2024), what this
repository does, and why they differ. The method as implemented is described in
[methodology.md](methodology.md).

Every paper value below was checked against the arXiv HTML of version 1 on 25 September 2026.
Two limits on that check: figure contents were read from their captions only, and the HTML was
not compared with the PDF. Anything that could not be confirmed in the text is marked
**not verified**.

## Row by row

| Topic | Paper | This repository | Reason for the difference |
|---|---|---|---|
| Universe size | Top 500 US stocks by capitalisation, re-selected every day after the close, with valid return data the next day (§3.1) | Top 100 by capitalisation, re-ranked every day; 130 names subscribed | The free QuantConnect backtest node. With the same buffer, 500 ranks need about 530 daily subscriptions and a $500 \times 500$ transformation matrix every day. The ranks the paper trades beyond 100 are not tested here. |
| Capitalisation data | CRSP daily prices, shares outstanding and capitalisations, January 1990 to December 2022 (§3.1) | QuantConnect's point-in-time Morningstar `Fundamental.market_cap` on a universe that includes delisted companies. That field is a month-end snapshot (the previous month-end close times the shares then outstanding, held for a month), so v4 rolls it forward daily with each company's split- and dividend-adjusted price and re-anchors it when a new snapshot arrives (`rank_space.DailyCaps`, `cap_source = "rolled"`) | CRSP is not available inside QuantConnect. QuantConnect serves the Morningstar figure as point-in-time data: each snapshot arrives on the first trading day after a month-end and uses that month-end's close. Whether its share count was public by then was not tested in general. The share count appears to be dated at its as-of date: AAPL's `company_profile.shares_outstanding` changed in the selection after 18 January 2019, the as-of date on the cover of the quarterly report Apple filed on 30 January 2019, and the 1 February snapshot is the 31 January close times that count. Here the filing came before the month-end; where a count's as-of date falls before a month-end and its filing after it, the snapshot would carry a small look-ahead. A monthly value also gives rank returns that are zero on most days, which is why runs v1 to v3 are superseded. `company_profile.shares_outstanding` cannot replace it, because it is restated for later splits. Rolled forward over January 2019, the value landed within 0.06% to 0.31% of the next snapshot for AAPL, MSFT and XOM; it counts dividends as return until the next snapshot and steps by the anchoring error at each re-anchor ([data-checks.md](data-checks.md)). |
| Intraday data | 1-minute prices from Polygon.io, January 2005 to December 2022, combined with CRSP shares into 1-minute capitalisations (§3.1) | None; daily data only | Minute data for 130 names over multi-year periods does not fit the free tier. See the rebalancing row. |
| Backtest period | January 2006 to December 2022; the yearly tables cover 2007 to 2022 (§3.1, Tables 1 and 2) | Eight backtest windows starting in January 2011, 2013, 2015, 2017, 2018, 2020, 2022 and 2024. The first seven stopped at the order cap after 18.8 to 22.0 months; the 2024 window ran the full year | The free node stops a backtest at 10,000 orders, which the v4 book reaches after about 20 months ([results/README.md](../results/README.md#the-order-cap), [methodology.md](methodology.md#backtest-windows-and-the-order-cap)). The last two to five months of each two-year window are not covered. |
| Risk-free rate | One-month Treasury bill rate from the Kenneth French Data Library (§3.1) | QuantConnect's risk-free interest-rate model, divided by 252 per day | The French library is not a QuantConnect dataset. The rate shifts every rank's daily excess return by the same small, slowly moving amount, which the column demeaning in the PCA and the regression intercept largely absorb. |
| Number of factors | One in rank space, five in name space, from the eigenvalue spectrum (§3.2, Algorithm 1) | One | Same as the paper. Name space is not implemented. |
| Factor window | 252-day look-back for the PCA factors, updated daily (Algorithm 1) | 252 trading days, updated daily | Same. |
| PCA | SVD of the excess returns themselves, uncentred: $R_t - R_f = U \Sigma V^\top$ (Algorithm 1, Eq. 5.1.1) | SVD of the 252-day window with each rank's column demeaned first | A choice of this implementation, kept because the recorded runs used it. Its effect on the leading vector was not measured; the risk-free row above relies on it. |
| Loading window | 60-day look-back for the loadings $\beta$, updated daily (Algorithm 1, §3.1) | 60 trading days, regression with intercept, updated daily | Same. The paper does not say whether its regression has an intercept (**not verified**). |
| Cumulative residual window | The same 60-day window (§3.1, Eq. 2.2.1 to 2.2.3) | 60 trading days | Same. |
| OU estimation | AR(1) regression on the cumulative residuals over $\alpha = 1, \dots, L$, with $\kappa = -252 \ln b$, $m = a / (1 - b)$, $\sigma = \sqrt{\mathrm{Var}(\xi) / (1 - b^2)}$ (Appendix 5.2, Eq. 5.2.1 and 5.2.2) | The same regression on 59 pairs, without the first pair of Eq. 5.2.1, which starts from $x_{t-L} = 0$; $\tau = -1 / \ln b$ in trading days, which equals $252 / \kappa$; $\sigma$ from the right-hand block of Eq. 5.2.2 | Close to the paper; two choices. Eq. 5.2.2 defines $\sigma$ two ways that disagree: its left-hand block, $\mathrm{Var}(\xi) = \sigma^2 (1 - e^{-2\kappa\Delta t}) / (2\kappa)$, makes $\sigma$ the diffusion coefficient of Eq. 2.2.4, and its right-hand block the equilibrium standard deviation, smaller by a factor $\sqrt{2\kappa}$. This implementation uses the right-hand block, as Avellaneda and Lee do; the choice sets the scale of every s-score against the thresholds. The 60th pair is a numerical choice with a small effect. The paper's §2.2.1 also calls $\hat\mu$ and $\hat\sigma$ maximum likelihood estimators; the appendix gives the regression, which is what is implemented. |
| Signal | $s = (x_t - \hat\mu) / \hat\sigma$ (Eq. 2.2.5) | Same, with $\sigma$ the equilibrium standard deviation from the row above | Same. |
| Entry | Open short when $s \gt 1.25$, long when $s \lt -1.25$, only if $\hat\tau \lt 30$ days (Eq. 2.2.7, 2.2.8) | Same | Same. |
| Holding and exit | Eq. 2.2.7 as printed keeps a long while $s \gt c_{\text{close}}$ and a short while $s \gt c_{\text{close}}$, each only while $\hat\tau \lt 30$ days, with $c_{\text{close}} = 0.5$ | A position closes when $\lvert s \rvert \lt 0.5$ or when the OU fit is not valid; $\tau$ is checked at entry only | The printed rule cannot be applied literally: a long opened at $s \lt -1.25$ would fail $s \gt 0.5$ on the next day and close at once. The text says positions close "when the trading signals mean-revert close to zero", so the band $\lvert s \rvert \lt 0.5$ is used. Dropping the $\tau$ condition while holding is a choice of this implementation, not the paper's. |
| Residual weights | $w^\epsilon \in \lbrace -1, 0, 1 \rbrace$ per rank, uniform size (Eq. 2.2.7; Fig. 5 caption) | Same | Same. |
| Equity weights | $w^R = \Phi^\top w^\epsilon$, L1-normalised, gross exposure $\Lambda = 1$ (Eq. 2.2.10, Algorithm 2, Eq. 2.4.3) | Computed at every decision pass and booked against the rank returns to the next close as the before-cost series "rank space, paper weights, before costs"; not traded | Run v1 traded $\Phi^\top w$, which is dense (a weight on every rank), on the monthly market-cap field. It sent orders on 566 dates, a median of 6.5 and at most 99 on each, about 11 per trading day, and reached 10,001 orders on 16 August 2013, 3.6 years after it started trading on 4 January 2010, at a net loss of 11.2% ([results/runs.csv](../results/runs.csv), [orders.csv](../results/superseded/v1_2010_2024/orders.csv)). The fixed-leg book of the next row sends an order only when an event needs one. How often $\Phi^\top w$ would trade on daily capitalisations was not measured. |
| Traded weights | As above | A fixed 2.5% of equity on the company holding each open rank, and one SPY position sized to offset the legs' exposure to the factor | Keeps the number of orders to the events that need one: an open, a close, a rank changing hands, or a drift above 1.5%. Run v2 already used legs plus SPY but renormalised the legs every day, which resized every leg whenever any position opened or closed; it hit the cap in March 2023. v3 used 5% legs, which asked for more than QuantConnect's default margin allows and had about four orders in ten rejected; at 2.5% the rejections almost vanish ([data-checks.md](data-checks.md#margin-check)). The fixed-leg book is not the paper's portfolio, so its P&L is not a test of the paper's weights. That is why the paper's weights are still computed and plotted. |
| Rank to name mapping | Intraday rebalancing every $\mathcal{T} = 225$ minutes, moving each rank's weight to whichever company holds the rank (§2.3, Algorithm 4). 225 minutes is where the Sharpe ratio and terminal P&L of the neural network in rank space peak (Fig. 13 caption) | One decision pass per date on the previous trading day's close; orders fill at the next open, or one session later after a 16:00 pass ([methodology.md](methodology.md#daily-timeline)) | Minute data for the ranked names over several years does not fit the free tier. Two consequences. The paper's latency cost, the first term of Eq. 2.3.6 (the divergence when ranks switch between two rebalancing points), builds up over a day or more for every rank that changes hands instead of 225 minutes. Separately, the book carries an execution lag the paper's scheme does not have: the paper holds from the end of day $t$ the weights set on it (Eq. 2.3.3 counts rank returns from that close), while here the orders fill at the open after the signal's close or later. The paper's §2.3 itself says that assigning rank weights to names at the end of each day and holding them the next day (Eq. 2.3.1) does not keep the advantages of statistical arbitrage in rank space. |
| Transaction cost | $\eta = 2$ basis points of traded value for the bid-ask spread (§2.3.1, Eq. 2.4.2), plus the latency cost of Eq. 2.3.6. The neural network stops being profitable at 5 bp (§3.7) | 2 bp of traded value on every fill, as a QuantConnect fee model. The latency cost and the execution lag are not separate charges; both are inside the realised P&L | Same spread cost. |
| P&L accounting | Cash earns the risk-free rate; rank-space P&L is computed through Algorithm 4 on 1-minute capitalisations (Eq. 2.4.3) | QuantConnect's own account: cash, margin, fills at the open. Cash earns no interest (each window's equity change equals closed-trade P&L minus fees plus unrealised P&L to within 0.24% of starting capital), and the before-cost series of the paper's weights earns nothing on cash either | The engine. See [methodology.md](methodology.md#execution) on buying power: 0 to 35 orders per v4 window were rejected for insufficient margin, against about 41% to 45% of all orders in the superseded v3 chunks. |
| Reported metrics | Per calendar year: return compounded over the year's trading days, volatility and Sharpe ratio, then averaged over years (Eq. 2.4.4, Algorithm 5, Tables 1 and 2) | QuantConnect's statistics over each window, and the before-cost series compounded over each window and annualised over the days it covers ([results/v4/summary.csv](../results/v4/summary.csv)) | QuantConnect reports whole-run figures. The paper's averaged yearly Sharpe ratio and QuantConnect's Sharpe ratio are different statistics. QuantConnect's subtracts the average rate of its risk-free model, which the account never earned, and its probabilistic Sharpe ratio is the probability that the Sharpe ratio exceeds 1, not 0 ([README](../README.md#v4-windows-coverage-and-gaps)). The calendar-year split of the before-cost series in [results/v4/calendar_years.csv](../results/v4/calendar_years.csv) follows the paper's Algorithm 5. |
| Neural-network variant | Two convolutional layers ($D_{\text{channel}} = 8$, kernel 2) and one transformer encoder layer (4 heads, dropout 0.25) on the 60-day cumulative residual paths, trained on a mean-variance objective with $\gamma = 2$ over 24-day windows; hyper-parameters set annually on days $t-1000$ to $t-60$ with validation on $t-59$ to $t-1$, then retrained quarterly on days $t-500$ to $t-1$ (§2.2.2, §3.1) | Not implemented | This repository implements the parametric strategy (Algorithms 1 and 2) first. The neural network needs offline GPU training and minute-level rebalancing to test the paper's claim. The 2024 attempt at it is audited in [audit-2024-cnn.md](audit-2024-cnn.md). |

## What the paper reports, and what this repository finds

### The paper

The parametric model in rank space, year by year, from Tables 1 and 2 (column "rank space,
parametric model"). Each year's return is the portfolio's daily returns compounded over that
calendar year and scaled to 252 trading days (Eq. 2.4.4); Table 1 has no transaction costs,
Table 2 charges 2 basis points with the 225-minute intraday rebalancing.

| Year | Table 1, before costs | Table 2, after costs |
|---|---|---|
| 2011 | 40.14% | −32.45% |
| 2012 | 41.06% | −26.53% |
| 2013 | 27.92% | −25.14% |
| 2014 | 43.82% | −22.52% |
| 2015 | 41.78% | −20.12% |
| 2016 | 61.86% | −17.68% |
| 2017 | 30.58% | −21.38% |
| 2018 | 27.78% | −28.83% |
| 2019 | 41.42% | −21.49% |
| 2020 | 25.06% | −42.12% |
| 2021 | 37.60% | −36.82% |
| 2022 | 36.79% | −33.01% |
| Average, 2007 to 2022 | 34.33% (Sharpe ratio 6.14) | −29.37% (Sharpe ratio −9.95) |

Every year from 2007 to 2022 is positive in Table 1 and negative in Table 2. For comparison, the
paper's neural network in rank space reports an average of 35.68% a year with an average Sharpe
ratio of 3.28 after costs over 2007 to 2022 (Table 2), and the parametric model in name space
2.36% before costs and 1.14% after (Tables 1 and 2).

### This repository, v4

The same weights, $\Phi^\top w^\epsilon$ L1-normalised, computed inside the algorithm at every
decision pass and booked against the rank returns to the next close, with no costs
([methodology.md](methodology.md#the-papers-weights-computed-not-traded)). Over each window, from
its first fill to its last "Rank vs name" sample
([results/v4/summary.csv](../results/v4/summary.csv)):

| Window | Span of the series | Cumulative, before costs | Annualised over the span |
|---|---|---|---|
| 2011 to 2012 | 3 Jan 2011 to 14 Sep 2012 | +80.63% | +41.67% |
| 2013 to 2014 | 2 Jan 2013 to 28 Oct 2014 | +63.56% | +31.08% |
| 2015 to 2016 | 2 Jan 2015 to 3 Nov 2016 | +82.74% | +38.85% |
| 2017 to 2018 | 3 Jan 2017 to 8 Oct 2018 | +71.80% | +35.99% |
| 2018 to 2019 | 3 Jan 2018 to 3 Sep 2019 | +96.21% | +49.92% |
| 2020 to 2021 | 2 Jan 2020 to 27 Jul 2021 | +99.76% | +55.56% |
| 2022 to 2023 | 4 Jan 2022 to 19 Sep 2023 | +123.34% | +60.17% |
| 2024 | 3 Jan 2024 to 27 Dec 2024 | +40.40% | +41.23% |

"Annualised over the span" is $(1 + p)^{365.25 / d} - 1$ for a cumulative return $p$ over $d$
calendar days from the first fill to the last sample.

Table 1 is per calendar year, so the series is also split into calendar years
([results/v4/calendar_years.csv](../results/v4/calendar_years.csv)). Each year runs from the
first fill, or from the previous year's last sample, to the year's last sample, and is
annualised as the paper's Algorithm 5 does: the compounded return raised to $252 / N$, minus
one, with $N$ the trading sessions covered. In each two-year window the second year is a part
year, ending where the order cap stopped the window:

| Window | Year | Span | Sessions | Cumulative | Annualised | Table 1 | Difference, points |
|---|---|---|---|---|---|---|---|
| 2011 to 2012 | 2011 | 3 Jan to 28 Dec 2011 | 250 | +50.03% | +50.52% | 40.14% | +10.38 |
| 2011 to 2012 | 2012, part | 28 Dec 2011 to 14 Sep 2012 | 180 | +20.39% | +29.67% | 41.06% | −11.39 |
| 2013 to 2014 | 2013 | 2 Jan to 27 Dec 2013 | 250 | +30.82% | +31.10% | 27.92% | +3.18 |
| 2013 to 2014 | 2014, part | 27 Dec 2013 to 28 Oct 2014 | 210 | +25.03% | +30.74% | 43.82% | −13.08 |
| 2015 to 2016 | 2015 | 2 Jan to 29 Dec 2015 | 250 | +43.01% | +43.42% | 41.78% | +1.64 |
| 2015 to 2016 | 2016, part | 29 Dec 2015 to 3 Nov 2016 | 215 | +27.78% | +33.29% | 61.86% | −28.57 |
| 2017 to 2018 | 2017 | 3 Jan to 28 Dec 2017 | 250 | +27.09% | +27.33% | 30.58% | −3.25 |
| 2017 to 2018 | 2018, part | 28 Dec 2017 to 8 Oct 2018 | 195 | +35.19% | +47.64% | 27.78% | +19.86 |
| 2018 to 2019 | 2018 | 3 Jan to 28 Dec 2018 | 249 | +53.03% | +53.82% | 27.78% | +26.04 |
| 2018 to 2019 | 2019, part | 28 Dec 2018 to 3 Sep 2019 | 170 | +28.22% | +44.55% | 41.42% | +3.13 |
| 2020 to 2021 | 2020 | 2 Jan to 28 Dec 2020 | 250 | +60.27% | +60.88% | 25.06% | +35.82 |
| 2020 to 2021 | 2021, part | 28 Dec 2020 to 27 Jul 2021 | 145 | +24.64% | +46.63% | 37.60% | +9.03 |
| 2022 to 2023 | 2022 | 4 Jan to 29 Dec 2022 | 249 | +70.58% | +71.68% | 36.79% | +34.89 |
| 2022 to 2023 | 2023, part | 29 Dec 2022 to 19 Sep 2023 | 180 | +30.93% | +45.83% | not in the paper | |
| 2024 | 2024 | 3 Jan to 27 Dec 2024 | 249 | +40.40% | +40.97% | not in the paper | |

**Where they agree.** Before costs the paper's weights made money in every window and in every
calendar year of every window, as they do in every year of Table 1, and at the same order of
magnitude: 31.08% to 60.17% a year over each window's span here, against 25.06% to 61.86% for
each year from 2011 to 2022 in Table 1. The first calendar years of the four windows starting
from 2011 to 2017 are within −3.25 to +10.38 points of Table 1. The two windows that cover 2018
agree with each other: the 2017 to 2018 window's series rose 35.19% from its last 2017 sample to
8 October 2018, and the 2018 to 2019 window's 34.32% from its start to 2 October 2018.

**Where they differ.** Year by year the two do not match, and the differences go both ways. The
part years 2012, 2014 and 2016 of the first three windows run 11.39 to 28.57 points below
Table 1. From 2018 on the series runs above it: the first years of the 2018, 2020 and 2022
windows by 26.04 to 35.82 points, the part year 2018 of the 2017 to 2018 window by 19.86 points,
and the part years 2019 and 2021 by 3.13 and 9.03 points. Both windows that cover 2018 had passed
the paper's 27.78% for the whole of that year by early October. Of the 13 window-years with a
Table 1 figure, 9 are above it and 4 below. The part years cover 145 to 215 sessions, so their
annualised figures are noisier than the whole years'. Nothing in these runs isolates why the
series departs from Table 1.

**What this comparison is not.** It is not a replication of Table 1. The universe is the top 100
by capitalisation, not the top 500. The capitalisations are Morningstar's month-end snapshots
rolled forward daily, not CRSP's daily figures, and the rolled value counts dividends as return
until the next snapshot and steps at each re-anchor, effects on this series that were not
measured ([data-checks.md](data-checks.md#the-rolled-forward-daily-capitalisation-v4)). The years
are 2011 to 2024 with the end of most windows missing, not 2007 to 2022. The series earns nothing
on cash, where the paper's P&L (Eq. 2.4.3) credits cash with the risk-free rate. The finding is
narrower: on daily capitalisations, the paper's parametric weights in rank space earn a
before-cost return of the same order of magnitude as the paper reports, above it from 2018 on and
below it in 2012, 2014 and 2016.

**After costs.** Table 2 charges 2 basis points with 225-minute intraday rebalancing, and the
parametric strategy in rank space loses money in every year, −17.68% to −42.12% a year from 2011
to 2022. Here the traded book made −9.96% to +9.10% at the same last samples (net −9.963% to
+8.920% at each window's stop, from QuantConnect). That book is not the paper's portfolio: 2.5%
legs, a SPY hedge, drift bands, and fills at the open after the signal's close or a session
later. Its numbers are therefore not comparable with Table 2, and the result is consistent with
the paper's conclusion rather than a test of it: the before-cost return in rank space does not
survive being held on companies. The paper's §2.3 expects as much of a mapping from ranks to
names made at the end of each day (Eq. 2.3.1). Fees were 2.96% to 5.46% of starting capital per
window, a small part of the gap; the rest is the execution lag, the latency and the difference
between the traded book and the paper's weights together, which these runs cannot split
([methodology.md](methodology.md#costs)).

The superseded runs v1 to v3 reported far smaller before-cost figures (+39.18% over the 2011 to
2017 chunk, +5.41% over the 2018 to 2024 chunk). They were computed on the monthly field, whose
rank returns were zero on most days, and are not comparable with the paper
([data-checks.md](data-checks.md#fundamentalmarket_cap-is-a-month-end-snapshot)).

## Items that could not be verified

- Whether the loading regression in Algorithm 1 includes an intercept.
- Whether the share count behind each Morningstar snapshot was public by the snapshot's
  month-end; it was checked for AAPL at one month-end only (the capitalisation row).
- The paper's figures themselves (Fig. 9, 13, 14), beyond what their captions and the text say.
- The PDF version of arXiv:2410.06568v1, which was not compared with the HTML rendering used
  here, in particular for Eq. 2.2.7.
