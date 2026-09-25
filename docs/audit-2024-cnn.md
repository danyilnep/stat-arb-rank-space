# Audit of the 2024 CNN attempt

In November 2024 the Mercury Capital Management quant team, led by Danyil Nepyivoda, attempted
the deep-learning variant of the rank-space paper inside QuantConnect's free research node. Two
research notebooks by a member of the 2024 team survive, reconstructed in
[`received/01_data.py`](../received/01_data.py) and [`received/02_cnn.py`](../received/02_cnn.py),
together with the team's deck and a QuantConnect backtest screenshot. Their provenance is in
[received/README.md](../received/README.md).

This audit was first written on 22 September 2026 and every point was re-checked against the
code on 25 September 2026; finding 11 was added on that date, after the data checks of this
repository. Line links point into the files in `received/`. The notebooks were
read, not run: they need a QuantConnect research node with `QuantBook`, and the algorithm that
traded the model was never received. Nothing below depends on running them.

## What the notebooks do

1. Take every stock that was among the 40 largest by market capitalisation on any day of 2015,
   pull daily market capitalisations and 1-minute closes for 2015, and turn them into a
   1-minute market capitalisation per stock:
   close × (daily market capitalisation ÷ first close of the day)
   ([01_data.py#L20-L42](../received/01_data.py#L20-L42),
   [#L124-L132](../received/01_data.py#L124-L132)).
2. Convert those to 1-minute percentage changes from 2 February 2015 to the end of 2015, subtract
   a per-minute rate built from the 10-year Treasury yield, remove one principal component and
   call the result residual returns
   ([01_data.py#L137-L158](../received/01_data.py#L137-L158),
   [#L163-L274](../received/01_data.py#L163-L274)).
3. Train a small 1D convolutional network whose input is one minute's cross-section of residuals
   and whose output is a softmax over the stocks, with a custom loss meant to be variance minus
   return ([02_cnn.py#L20-L66](../received/02_cnn.py#L20-L66)).
4. Evaluate on a random 30% of the minutes, compound the residual returns, print a total return
   and a Sharpe ratio, and save the model to QuantConnect's ObjectStore
   ([02_cnn.py#L68-L112](../received/02_cnn.py#L68-L112)).

## Findings

### 1. The train/test split shuffles minutes, and the test set is also the validation set

`train_test_split(X, r_t, test_size=0.3, random_state=42)`
([02_cnn.py#L26](../received/02_cnn.py#L26)) shuffles by default, so the 30% of minutes held
out for testing are scattered through the same eleven months as the training minutes. Adjacent
minutes are close to identical inputs, so the test set is not out of sample in time. The same
test arrays are then passed as `validation_data` during training
([02_cnn.py#L66](../received/02_cnn.py#L66)), so any choice made while watching the validation
loss was made on the test set.

### 2. The imputer and the PCA are fitted on the whole year

`SimpleImputer(strategy='mean').fit_transform` and `PCA(n_components=1).fit` run once over all
minutes of the year ([01_data.py#L252-L257](../received/01_data.py#L252-L257)), test minutes
included. The residual for a minute in February therefore uses a factor and column means
estimated with data from December. The paper refits on trailing 252-day and 60-day windows
every day.

### 3. The transformation matrix is not a projection

The code takes the first PCA eigenvector as `beta_t` and the explained-variance ratio as
`omega_t` ([01_data.py#L260-L261](../received/01_data.py#L260-L261)), then builds
`phi_t = I - np.outer(beta_t, omega_t)`
([01_data.py#L264-L266](../received/01_data.py#L264-L266)). `omega_t` has one element, so the
outer product is an $n \times 1$ column that NumPy broadcasts across the identity. With
$v$ the unit eigenvector and $\rho$ the explained-variance ratio, the residual computed at
[01_data.py#L269](../received/01_data.py#L269) is

$$
\epsilon_i = r_i - \rho \, v_i \sum_{j=1}^{n} r_j .
$$

That subtracts a fraction $\rho$ of an equal-weighted market move, scaled by each stock's
eigenvector entry. It does not remove the factor: $\Phi v = v \left( 1 - \rho \sum_j v_j \right)$,
which is zero only by coincidence, and $\Phi^2 \ne \Phi$ in general. In the paper's appendix
(Eq. 5.1.2) the loading and the factor weights come from the same SVD, $\beta = u_1 \sigma_1$ and
$\omega = u_1^\top / \sigma_1$ with $u_1$ the first eigenvector over the stocks (the $v$ above),
so $\beta \omega = v v^\top$ and

$$
\Phi = I - v v^\top ,
$$

the orthogonal projection that removes the first principal component. Under the paper's
Algorithm 1, which fits $\beta$ by regression on a 60-day window and $\omega$ on a 252-day window,
$\Phi$ is an oblique projection instead ([methodology.md](methodology.md#algorithm-1-market-decomposition)).
Either way $\Phi \beta = 0$, which the notebook's matrix does not satisfy.

### 4. There is no rank space

Market capitalisations are used twice: to choose the tickers
([01_data.py#L32](../received/01_data.py#L32)) and to build 1-minute capitalisations
([01_data.py#L128-L132](../received/01_data.py#L128-L132)). No step ever sorts the stocks by
capitalisation at each time to form rank columns. The table is pivoted with one column per
ticker ([01_data.py#L150](../received/01_data.py#L150)) and the returns are percentage changes
per ticker ([01_data.py#L158](../received/01_data.py#L158)). Everything downstream is in name
space. Since the 1-minute capitalisation is the close times a share count fixed for the day,
its within-day percentage change is the stock's price return.

### 5. The convolution runs over alphabetically adjacent tickers, with no time window

The network input is one row of the residual table with a channel axis added, shape
(number of stocks, 1) ([02_cnn.py#L28-L32](../received/02_cnn.py#L28-L32)). The two `Conv1D`
layers with kernel 3 ([02_cnn.py#L33-L35](../received/02_cnn.py#L33-L35)) therefore slide
across stocks, not across time. The column order comes from `pivot`, which sorts tickers
alphabetically ([01_data.py#L150](../received/01_data.py#L150)), and is kept when the residual
columns are built ([01_data.py#L220-L223](../received/01_data.py#L220-L223),
[#L270-L274](../received/01_data.py#L270-L274)). Neighbouring inputs to each filter are
neighbours in the alphabet, which carries no financial meaning. The network sees one minute at a
time, so no path of past residuals ever reaches it; the paper's network reads a 60-day path per
rank.

### 6. The output is long-only

The last layer is `Dense(n, activation='softmax')`
([02_cnn.py#L37](../received/02_cnn.py#L37)), so every weight is positive and the weights sum
to one; the division at [02_cnn.py#L70](../received/02_cnn.py#L70) normalises them again. The
book cannot go short. A statistical arbitrage book in the paper's sense is long-short with zero
factor exposure.

### 7. The loss's covariance is a rank-one outer product

In `maximise_residual_return_loss`
([02_cnn.py#L41-L63](../received/02_cnn.py#L41-L63)), `mean_returns` is the average across stocks
within one minute ([02_cnn.py#L50](../received/02_cnn.py#L50)). The "covariance matrix" is the
outer product of that one minute's demeaned return vector $d$ with itself, divided by the
number of stocks $n$ ([02_cnn.py#L53-L55](../received/02_cnn.py#L53-L55)). The variance term is
then

$$
w^\top \frac{d d^\top}{n} w = \frac{(w^\top d)^2}{n} ,
$$

a squared cross-sectional return, not a variance over time. The loss is
$\text{mean}\left[ (w^\top d)^2 / n - w^\top r \right]$
([02_cnn.py#L62](../received/02_cnn.py#L62)). If minute residuals are of order $10^{-4}$ (an
assumption; the notebook was not run here), the first term is of order $10^{-8} / n$ against a
second term of order $10^{-4}$, so the loss is in effect minus the mean return, with no
risk-aversion parameter. The paper's objective is a mean-variance target over 24-day windows
with $\gamma = 2$.

### 8. The evaluation is not a P&L, and the Sharpe ratio is per minute

The test weights are applied to the next minute's residual returns and compounded
([02_cnn.py#L77-L79](../received/02_cnn.py#L77-L79)). Residual returns cannot be earned without
holding the factor hedge, and with the matrix of finding 3 they are not even residuals. The test
rows are in shuffled order, so the horizontal axis of the chart
([02_cnn.py#L85-L93](../received/02_cnn.py#L85-L93),
[received/notebook-test-curve.png](../received/notebook-test-curve.png)) counts shuffled minutes,
not time; it runs to about 27,000 points, which fits 30% of the roughly 90,000 trading minutes
from February to December 2015. Each vertical jump in the curve is a single row. The blue curve
ends near 0.7, a 70% cumulative figure, which is not the 86% presented in the deck. The printed
Sharpe ratio is `np.mean(portfolio_returns) / np.std(portfolio_returns)`
([02_cnn.py#L97](../received/02_cnn.py#L97)): per minute, not annualised, and on shuffled rows.

### 9. The risk-free rate is in percent

The rate comes from QuantConnect's US Treasury yield curve dataset, column `tenyear`
([01_data.py#L167-L170](../received/01_data.py#L167-L170)), which is quoted in percent. It is
divided by $365 \times 24 \times 60 = 525{,}600$
([01_data.py#L189](../received/01_data.py#L189)), spread over 1,440 minutes per calendar day
([01_data.py#L198](../received/01_data.py#L198)) and subtracted from each stock's 1-minute
return, which is a fraction ([01_data.py#L223](../received/01_data.py#L223)). For a yield $y$ in
percent the code subtracts $y / 525{,}600$ per minute. A per-trading-minute rate would be
$y / 100 / (252 \times 390) = y / 9{,}828{,}000$, so the amount subtracted is about 18.7 times too
large: a factor of 100 from the missing percent conversion, partly offset by spreading over
calendar minutes rather than trading minutes. It is also a 10-year yield, where the paper uses
the one-month bill. The amount is the same for every stock at a given minute, so the effect on
the residuals is small, but the units are wrong. Slide 12 of the deck says the yield could not be
tracked in QuantConnect and a constant rate was used; the code does track it.

### 10. The model is saved without its weights

`serialize_keras_object(model)` ([02_cnn.py#L110](../received/02_cnn.py#L110)) returns the
model's configuration: its class, layers and hyper-parameters. It does not contain the trained
weights. That JSON string is what goes into the ObjectStore under the key `"model"`
([02_cnn.py#L111-L112](../received/02_cnn.py#L111-L112)). A trading algorithm that rebuilt the
network from it would get the architecture with freshly initialised weights, not the trained
model.

### 11. The share count is a month-old capitalisation divided by the day's first price

The daily capitalisations are QuantConnect's fundamental `marketcap` for each stock
([01_data.py#L61](../received/01_data.py#L61), [#L70](../received/01_data.py#L70)). The notebook
keeps one close per stock and day, the first row of each day
([01_data.py#L124](../received/01_data.py#L124)), which is the first minute's close when the
minute rows are in time order within each stock, as QuantConnect's history returns them. It
merges that close onto the daily capitalisation ([#L126](../received/01_data.py#L126)), divides
to get `shares_outstanding = marketcap / close` ([#L128](../received/01_data.py#L128)), and
multiplies every minute's close by that ratio
([#L130-L132](../received/01_data.py#L130-L132)).

The probes of this repository found that QuantConnect's `market_cap` is a month-end snapshot,
one value held for a whole month ([data-checks.md](data-checks.md)). They read the field in a
backtest's universe selection in 2012 and 2019; the notebook reads it through the research
history for 2015, which was not probed. If the field behaves the same way there, the notebook's
"share count" is a month-old capitalisation divided by the day's first price, and it moves
against the price from one day to the next. The 1-minute capitalisation at each day's first
minute is then the month-end value, the same number every morning within a month. The
percentage change from one day's last minute to the next day's first minute
([01_data.py#L158](../received/01_data.py#L158)) is the previous day's first close over its last
close, minus one: it reverses the previous day's intraday move instead of recording the
overnight return. Compounded over whole days, each stock's series returns to the same level
every morning within a month and jumps when the snapshot changes. Within a day the series is the
price return (finding 4); from one day to the next within a month it carries none of the
capitalisation's movement.

### Smaller points

- **Universe chosen with the whole year:** the ticker list is every stock that made the daily
  top 40 at any point in 2015 ([01_data.py#L27-L42](../received/01_data.py#L27-L42)), which is
  only known at the end of the year. For mega caps the effect is small.
- **Forward fill across stocks:** `minute_data.fillna(method='ffill')`
  ([01_data.py#L131](../received/01_data.py#L131)) runs on a long table ordered stock by stock,
  so a stock with missing values at the start of its block inherits the previous stock's last
  share count.
- **The target is the next minute's residual**, not a tradable return
  ([02_cnn.py#L20-L24](../received/02_cnn.py#L20-L24)).
- **Loaded and unused:** `phi_t` is saved ([01_data.py#L281](../received/01_data.py#L281)) and
  loaded ([02_cnn.py#L12](../received/02_cnn.py#L12)) but never used; `tensorflow` is imported in
  the data notebook and not used ([01_data.py#L14](../received/01_data.py#L14)); the
  `batch_data` directory is created and never written to
  ([01_data.py#L90-L91](../received/01_data.py#L90-L91)); `del batch_df`
  ([01_data.py#L80](../received/01_data.py#L80)) raises an error if no batch returned data.
- **Deprecated calls:** `fillna(method=...)` ([01_data.py#L131](../received/01_data.py#L131))
  and the `'T'` frequency alias ([01_data.py#L188](../received/01_data.py#L188),
  [#L198](../received/01_data.py#L198)) are deprecated in pandas 2, and
  `InputLayer(input_shape=...)` ([02_cnn.py#L32](../received/02_cnn.py#L32)) in Keras 3.
- **Sample size:** eleven months of one year, on a ticker list built from the daily top 40
  ([01_data.py#L17-L18](../received/01_data.py#L17-L18),
  [#L137](../received/01_data.py#L137)). The deck gives 30 stocks and one year of data on
  slide 12, and the top 50 stocks on slides 3 and 11.

## The backtest screenshot

The deck's results slide (slide 11) shows a QuantConnect backtest screenshot, kept as
[received/backtest-2015-2020.png](../received/backtest-2015-2020.png). The algorithm that
produced it lives in the QuantConnect account of a member of the 2024 team and was never
received, so the code behind this backtest is unknown. What the screenshot shows:

| Item | Value in the screenshot |
|---|---|
| Period on the chart axis | January 2015 to about January 2020 |
| Starting capital | 100,000 USD (equity 186,450.29 USD at a return of 86.45%) |
| Return | 86.45% |
| Net profit (realised) | 32,515.01 USD |
| Unrealised | 53,777.81 USD |
| Holdings | 240,927.45 USD against equity of 186,450.29 USD, about 1.3 times |
| Fees | 943.82 USD over five years |
| Probabilistic Sharpe ratio (PSR) | 23.624% |
| Portfolio turnover panel (partly visible) | one spike near the start, one smaller spike later, otherwise close to zero |
| Assets sales volume panel | about 50 large US companies (AMZN, AAPL, INTC, FB, BAC and others) |

The deck adds "Win rate on trades: 89%", "Sharpe ratio: 0.7" and "Compound returns: 14%"
(slide 11). None of these is computed anywhere in the notebooks, and the screenshot does not show
a win rate.

**Reference run.** To put the 86.45% in context, SPY was bought and held on QuantConnect over
the same window: 1 January 2015 to 31 December 2019, 100,000 USD, QuantConnect's default split-
and dividend-adjusted prices (backtest `59188fbb663a9156f0a91ef329d1a6e0`, project 36922759,
run 24 September 2026; code and statistics in
[results/reference/spy_2015_2019/](../results/reference/spy_2015_2019/statistics.json)).
Result: net +73.298%, compounding annual return 11.620%, maximum drawdown 19.2%, Sharpe ratio
0.618, and a PSR of 13.577%.

**What the screenshot is consistent with.** Holdings of 1.3 times equity with near-zero
turnover after the start, more than half of the gain still unrealised at the end, and an equity
curve whose dips fall in the same months as the reference SPY run's drawdowns (August 2015,
January to February 2016, February 2018, October to December 2018, from `drawdown_pct` in
[equity.csv](../results/reference/spy_2015_2019/equity.csv)) are what a mostly static, long,
levered basket of large US stocks would produce. Over a window in which SPY returned 73.3%, such
a basket at about 1.3 times gross would be expected to return more than SPY before financing
costs, and 86.45% is 13 points more. QuantConnect computes the probabilistic Sharpe ratio
against a benchmark Sharpe ratio of 1, not 0. The screenshot's 23.6% and SPY's own 13.6% over
the window are both below 50%, which means only that neither run's observed Sharpe ratio was
above 1. The screenshot is also consistent with the code received: the network's softmax output
is long-only (finding 6), and a network rebuilt from the saved configuration would carry
untrained weights (finding 10), which through a softmax tend to give weights that are close to
uniform and change little from day to day.

**What it does not show.** Without the algorithm it is not possible to say whether the backtest
used the model at all, how the weights were set, or why gross exposure was 1.3 times. Nothing in
the screenshot demonstrates a market-neutral residual return, and nothing rules out that the
86.45% is market exposure. The screenshot does not support attributing the result to statistical
arbitrage in rank space.

## Outcome

This repository replaces the 2024 attempt with the paper's parametric strategy, implemented from
the paper and reported with whatever result it gives; see the [README](../README.md) and
[methodology.md](methodology.md).
