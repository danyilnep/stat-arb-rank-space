"""Draw the PNG figures in figures/ from the derived CSV files in results/.

    python analysis/make_figures.py

Reads only CSV files written by analysis/build_results.py: results/runs.csv,
results/v4/summary.csv, each v4 window's rank_vs_name.csv, equity.csv and
orders.csv, and results/checks/data/*.csv. Every number printed on a figure is
computed from those files. The figures have an opaque light background with a
hairline frame so they read the same on GitHub's light and dark themes. Figures
this script no longer draws are deleted from figures/.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
FIGURES = REPO / "figures"
DPI = 150

# Palette: validated categorical slots (blue, orange, violet) plus neutral chart ink.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BAND = "#efeee9"
FRAME = "#d6d5ce"
BEFORE_COSTS = "#2a78d6"  # blue: rank space, gross trading P&L, the rolled daily cap, v4
AFTER_COSTS = "#eb6834"  # orange: the traded book after fees, rejected orders
FEES = "#4a3aa7"  # violet: fees
NEUTRAL = "#52514e"

MINUS = "−"
WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
FIGURE_NAMES = ("rank_vs_name.png", "v4_windows.png", "costs.png", "data_check.png", "runs_overview.png")
OVERLAP_DASH = (0, (4, 2.2))


def style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.labelcolor": INK_2,
        "axes.labelsize": 10.5,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
        "axes.titlelocation": "left",
        "axes.titlepad": 8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.7,
        "grid.linestyle": "-",
        "xtick.color": AXIS,
        "ytick.color": AXIS,
        "xtick.labelcolor": INK_2,
        "ytick.labelcolor": INK_2,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "lines.linewidth": 2.0,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "legend.frameon": False,
        "legend.fontsize": 10.5,
        "axes.unicode_minus": True,
        "text.parse_math": False,  # dollar signs in labels are text, not mathtext
    })


# --------------------------------------------------------------------------- data
def runs() -> pd.DataFrame:
    return pd.read_csv(RESULTS / "runs.csv", keep_default_na=False, na_values=[""]).set_index("key")


def summary() -> pd.DataFrame:
    frame = pd.read_csv(RESULTS / "v4" / "summary.csv", dtype={"window": str}, keep_default_na=False,
                        na_values=[""])
    for column in ("configured_start", "configured_end", "first_fill", "last_fill", "last_sample"):
        frame[column] = pd.to_datetime(frame[column])
    return frame.sort_values("configured_start").reset_index(drop=True)


def read(folder: str, name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS / folder / name, parse_dates=["date"])


def cumulative_fees(folder: str, dates: pd.Series) -> pd.Series:
    """Fees paid up to and including each date, from orders.csv (filled orders, New York fill date)."""
    orders = pd.read_csv(RESULTS / folder / "orders.csv", usecols=["filled_utc", "fee"],
                         keep_default_na=False, na_values=[""])
    orders = orders.dropna(subset=["filled_utc"])
    filled = pd.to_datetime(orders["filled_utc"], utc=True).dt.tz_convert("America/New_York")
    daily = orders.assign(day=filled.dt.tz_localize(None).dt.normalize()).groupby("day")["fee"].sum().cumsum()
    positions = daily.index.searchsorted(dates, side="right")
    values = [0.0 if position == 0 else float(daily.iloc[position - 1]) for position in positions]
    return pd.Series(values, index=dates.index)


def window_label(window: str) -> str:
    return " to ".join(window.split("_"))


def overlapping(table: pd.DataFrame) -> set[str]:
    """Windows whose traded span runs into the next window's configured span (drawn dashed)."""
    marked = set()
    for current, following in zip(table.itertuples(), table.iloc[1:].itertuples()):
        if current.last_fill >= following.configured_start:
            marked.add(current.window)
    return marked


def untraded_spans(table: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    spans = []
    for current, following in zip(table.itertuples(), table.iloc[1:].itertuples()):
        if current.last_fill + pd.Timedelta(days=1) < following.configured_start:
            spans.append((current.last_fill + pd.Timedelta(days=1), following.configured_start))
    return spans


# --------------------------------------------------------------------------- text helpers
def pct(value: float, decimals: int = 1) -> str:
    """Signed percentage; a value that would round to zero keeps one significant digit instead."""
    if round(value, decimals) == 0 and value != 0:
        decimals = max(decimals, 2)
    return f"{value:+.{decimals}f}%".replace("-", MINUS)


def signed(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace("-", MINUS)


def money_k(value: float, sign: bool = True) -> str:
    text = f"${abs(value) / 1000:,.1f}k"
    if not sign:
        return text
    return f"{'+' if value >= 0 else MINUS}{text}"


def money_axis(value: float, _: object) -> str:
    return f"{MINUS if value < 0 else ''}${abs(value) / 1000:,.0f}k"


def pct_axis(value: float, _: object) -> str:
    return f"{value:.0f}%".replace("-", MINUS)


def nice_date(value: str | pd.Timestamp) -> str:
    stamp = pd.Timestamp(value)
    return f"{stamp.day} {stamp:%b %Y}"


def header(fig: plt.Figure, title: str, subtitle: str, top: float = 0.975, gap: float = 0.055) -> float:
    """Title and a subtitle wrapped to the figure width (about 11.8 characters per inch at 10.5 pt).

    Returns the figure y just below the subtitle, where the legend goes."""
    width = int(fig.get_figwidth() * 11.8)
    wrapped = "\n".join(textwrap.fill(part, width) for part in subtitle.split("\n"))
    fig.text(0.012, top, title, ha="left", va="top", fontsize=14, fontweight="bold", color=INK)
    fig.text(0.012, top - gap, wrapped, ha="left", va="top", fontsize=10.5, color=INK_2, linespacing=1.45)
    line_height = 10.5 * 1.45 / 72.0 / fig.get_figheight()
    return top - gap - (wrapped.count("\n") + 1) * line_height - 0.012


def legend_row(fig: plt.Figure, below: float, handles: list | None = None, **options) -> float:
    """One legend row just under the subtitle; returns the figure y under the legend."""
    settings = {"loc": "upper left", "bbox_to_anchor": (0.006, below), "handlelength": 2.2, "columnspacing": 2.0}
    settings.update(options)
    if handles is None:
        fig.legend(**settings)
    else:
        fig.legend(handles=handles, **settings)
    return below - 0.34 / fig.get_figheight()


def plot_top(fig: plt.Figure, legend_bottom: float, headroom_in: float) -> float:
    """Top of the plotting area: under the legend, leaving headroom for axis or panel titles."""
    return legend_bottom - headroom_in / fig.get_figheight()


def panel_heading(ax: plt.Axes, title: str, detail: str) -> None:
    """Bold panel title with one line of plain detail between it and the plot."""
    ax.set_title(title, pad=22)
    ax.text(0, 1.03, detail, transform=ax.transAxes, ha="left", va="bottom", fontsize=10, color=INK_2)


def end_dot(ax: plt.Axes, x, y: float, color: str) -> None:
    ax.plot([x], [y], marker="o", markersize=7, color=color, markeredgecolor=SURFACE, markeredgewidth=2,
            zorder=6, clip_on=False)


def frame_figure(fig: plt.Figure) -> None:
    """A hairline border, so the light figure has an edge on a dark page."""
    fig.add_artist(Rectangle((0.0015, 0.0015), 0.997, 0.997, transform=fig.transFigure, fill=False,
                             edgecolor=FRAME, linewidth=1.0))


def save(fig: plt.Figure, name: str) -> Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    frame_figure(fig)
    path = FIGURES / name
    fig.savefig(path, dpi=DPI, metadata={"Software": None})
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- figures
def rank_vs_name(table: pd.DataFrame) -> Path:
    """The headline: the paper's before-cost rank-space P&L against the traded book after costs, per window."""
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(left=0.075, right=0.975, top=0.70, bottom=0.075)
    dashed = overlapping(table)
    for start, end in untraded_spans(table):
        ax.axvspan(start, end, color=BAND, linewidth=0, zorder=0)
    ax.axhline(0, color=AXIS, linewidth=1.0, zorder=1)
    for record in table.itertuples():
        data = read(f"v4/{record.window}", "rank_vs_name.csv")
        dates = pd.concat([pd.Series([record.first_fill]), data["date"]], ignore_index=True)
        paper = pd.concat([pd.Series([0.0]), data["rank_space_paper_weights_before_costs_pct"]], ignore_index=True)
        book = pd.concat([pd.Series([0.0]), data["name_space_realised_after_costs_pct"]], ignore_index=True)
        style_kw = {"linestyle": OVERLAP_DASH, "linewidth": 1.6} if record.window in dashed else {}
        ax.plot(dates, paper, color=BEFORE_COSTS, zorder=3, **style_kw)
        ax.plot(dates, book, color=AFTER_COSTS, zorder=4, **style_kw)
        end_dot(ax, dates.iloc[-1], paper.iloc[-1], BEFORE_COSTS)
        end_dot(ax, dates.iloc[-1], book.iloc[-1], AFTER_COSTS)
        ax.annotate(pct(paper.iloc[-1], 0), (dates.iloc[-1], paper.iloc[-1]), xytext=(0, 9),
                    textcoords="offset points", ha="center", va="bottom", fontsize=10, color=INK,
                    fontweight="bold")
        ax.annotate(pct(book.iloc[-1], 0), (dates.iloc[-1], book.iloc[-1]), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=10, color=INK,
                    bbox={"boxstyle": "round,pad=0.12", "facecolor": SURFACE, "edgecolor": "none"}, zorder=7)
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(pd.Timestamp("2010-11-01"), pd.Timestamp("2025-03-01"))
    low = min(-25.0, float(table["realised_after_costs_pct"].min()) - 15.0)
    ax.set_ylim(low, float(table["paper_weights_before_costs_pct"].max()) * 1.14)
    ax.yaxis.set_major_formatter(FuncFormatter(pct_axis))
    ax.set_ylabel("Cumulative P&L since the window's first fill")

    paper_lo, paper_hi = table["paper_weights_before_costs_pct"].min(), table["paper_weights_before_costs_pct"].max()
    book_lo, book_hi = table["realised_after_costs_pct"].min(), table["realised_after_costs_pct"].max()
    overlap_note = ""
    if dashed:
        name = sorted(dashed)[0]
        following = table.iloc[table.index[table["window"] == name][0] + 1]["window"]
        overlap_note = f" Dashed: the {window_label(name)} window, which overlaps {window_label(following)}."
    below = header(
        fig,
        f"Paper weights before costs: {pct(paper_lo, 0)} to {pct(paper_hi, 0)} per window. "
        f"Traded book after costs: {pct(book_lo, 0)} to {pct(book_hi, 0)}",
        f"v4 in {WORDS.get(len(table), len(table))} windows on daily capitalisations, each drawn from zero at "
        "its first fill. Blue: the paper's L1-normalised weights on rank-space returns, before costs. Orange: "
        "the book held on the companies at those ranks, traded at the open from daily signals at 2 bp, after "
        "fees. Shaded: months "
        f"no window traded (order cap).{overlap_note} From each window's rank_vs_name.csv, cumulative, every "
        "fifth trading day.",
        gap=0.06,
    )
    handles = [
        Line2D([], [], color=BEFORE_COSTS, linewidth=2.5, label="Rank space: the paper's weights, before costs"),
        Line2D([], [], color=AFTER_COSTS, linewidth=2.5, label="Name space: the traded book, after costs"),
        Patch(color=BAND, label="No window traded"),
    ]
    fig.subplots_adjust(top=plot_top(fig, legend_row(fig, below, handles, ncol=3), 0.3))
    return save(fig, "rank_vs_name.png")


def v4_windows(table: pd.DataFrame) -> Path:
    rows = table.iloc[::-1].reset_index(drop=True)  # first window at the top
    fig, ax = plt.subplots(figsize=(11, 7.6))
    fig.subplots_adjust(left=0.13, right=0.975, top=0.785, bottom=0.075)
    measures = (
        ("paper_weights_before_costs_pct", BEFORE_COSTS, "Paper weights, before costs"),
        ("realised_after_costs_pct", AFTER_COSTS, "Traded book, after costs"),
        ("fees_pct_of_start", FEES, "Fees paid, % of starting capital"),
    )
    bar, step = 0.24, 0.27
    span = float(table["paper_weights_before_costs_pct"].max())
    for offset, (column, color, label) in zip((step, 0.0, -step), measures):
        positions = rows.index + offset
        values = rows[column].astype(float)
        ax.barh(positions, values, height=bar, color=color, linewidth=0, label=label, zorder=3)
        for position, value in zip(positions, values):
            ax.text(value + (span * 0.012 if value >= 0 else -span * 0.012), position,
                    pct(value) if column != "fees_pct_of_start" else f"{value:.1f}%",
                    va="center", ha="left" if value >= 0 else "right", fontsize=9.5, color=INK)
    ax.axvline(0, color=AXIS, linewidth=1.0, zorder=2)
    ax.set_yticks(rows.index, [f"{window_label(w)}\n{m:.1f} months" for w, m in
                               zip(rows["window"], rows["months_covered"])])
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(min(-20.0, float(table["realised_after_costs_pct"].min()) - 17.0), span * 1.12)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.xaxis.set_major_formatter(FuncFormatter(pct_axis))
    ax.set_xlabel("Percent of starting capital ($1,000,000), cumulative over the window")

    fees = table["fees_pct_of_start"]
    turnover = table["turnover_per_day_pct"]
    annual = table["paper_weights_annualised_pct"]
    gap = table["paper_weights_before_costs_pct"] - table["realised_after_costs_pct"]
    title = (f"Fees of {fees.min():.1f}% to {fees.max():.1f}% of capital are a small part of the gap between "
             "paper and book")
    if not (fees < gap).all():
        title = f"Fees came to {fees.min():.1f}% to {fees.max():.1f}% of capital per window"
    below = header(
        fig,
        title,
        "Paper weights before costs and the traded book after costs at the last \"Rank vs name\" sample of each "
        f"v4 window ({gap.min():.0f} to {gap.max():.0f} percentage points apart); fees are QuantConnect's total "
        f"to the stop. Annualised, the paper's weights made {pct(annual.min(), 0)} to {pct(annual.max(), 0)} a "
        f"year. The book turned over {turnover.min():.0f}% to {turnover.max():.0f}% of its value a day. From "
        "v4/summary.csv.",
        gap=0.055,
    )
    fig.subplots_adjust(top=plot_top(fig, legend_row(fig, below, ncol=3, handlelength=1.4, columnspacing=1.8),
                                     0.2))
    return save(fig, "v4_windows.png")


def costs(table: pd.DataFrame, run_table: pd.DataFrame) -> Path:
    fig, axes = plt.subplots(2, 4, figsize=(12, 7.6), sharey=True)
    fig.subplots_adjust(left=0.085, right=0.985, top=0.70, bottom=0.06, wspace=0.08, hspace=0.62)
    finals = []
    for ax, record in zip(axes.flat, table.itertuples()):
        folder = f"v4/{record.window}"
        start_equity = float(run_table.loc[record.key, "start_equity"])
        data = read(folder, "equity.csv")
        fees = cumulative_fees(folder, data["date"])
        net = data["equity"] - start_equity
        gross = net + fees
        ax.axhline(0, color=AXIS, linewidth=1.0, zorder=1)
        ax.plot(data["date"], gross, color=BEFORE_COSTS, zorder=3)
        ax.plot(data["date"], fees, color=FEES, zorder=4)
        ax.plot(data["date"], net, color=AFTER_COSTS, zorder=3)
        run = run_table.loc[record.key]
        total_gross = float(run["end_equity"]) - start_equity + float(run["total_fees"])
        total_fees = float(run["total_fees"])
        panel_heading(ax, window_label(record.window),
                      f"gross {money_k(total_gross)}, fees {money_k(total_fees, False)}")
        first, last = data["date"].iloc[0], data["date"].iloc[-1]
        ax.set_xticks([first, last], [f"{first:%b %Y}", f"{last:%b %Y}"])
        ax.set_xlim(first - pd.Timedelta(days=25), last + pd.Timedelta(days=25))
        ax.tick_params(axis="x", labelsize=9)
        for tick, align in zip(ax.get_xticklabels(), ("left", "right")):
            tick.set_horizontalalignment(align)
        finals.append((total_gross / start_equity * 100.0, total_fees / start_equity * 100.0))
    for ax in axes[:, 0]:
        ax.yaxis.set_major_formatter(FuncFormatter(money_axis))
    axes[0, 0].set_ylabel("Cumulative, US dollars")
    axes[1, 0].set_ylabel("Cumulative, US dollars")
    gross_pcts = [g for g, _ in finals]
    fee_pcts = [f for _, f in finals]
    below = header(
        fig,
        f"Before fees the book made {pct(min(gross_pcts))} to {pct(max(gross_pcts))} of capital per "
        f"window; fees took another {min(fee_pcts):.1f}% to {max(fee_pcts):.1f}%",
        "Gross = net P&L + cumulative fees, on $1,000,000 per window. Gross is before fees but after holding "
        "each rank's position on the company at that rank, filled at an open after the signal's close and with "
        "fixed legs, so it is not the paper weights' before-cost P&L of the headline figure. Title and panel "
        "figures: QuantConnect's totals "
        "to the stop (runs.csv). Lines: fees from each window's orders.csv by fill date, net from its "
        "equity.csv.",
        gap=0.055,
    )
    handles = [Line2D([], [], color=BEFORE_COSTS, linewidth=2.5, label="Trading P&L gross of fees"),
               Line2D([], [], color=FEES, linewidth=2.5, label="Cumulative fees"),
               Line2D([], [], color=AFTER_COSTS, linewidth=2.5, label="Net P&L after fees")]
    fig.subplots_adjust(top=plot_top(fig, legend_row(fig, below, handles, ncol=3), 0.62))
    return save(fig, "costs.png")


def data_check() -> Path:
    caps = pd.read_csv(RESULTS / "checks" / "data" / "cap_probe_2019.csv", parse_dates=["date"])
    reanchor = pd.read_csv(RESULTS / "checks" / "data" / "cap_probe_reanchor.csv",
                           parse_dates=["anchor_date", "reanchor_date"])
    updates = pd.read_csv(RESULTS / "checks" / "data" / "market_cap_updates.csv")
    tickers = sorted(caps["ticker"].unique())
    fig = plt.figure(figsize=(11, 8.2))
    grid = fig.add_gridspec(2, len(tickers), height_ratios=[1.25, 1], left=0.075, right=0.975, top=0.72,
                            bottom=0.07, hspace=0.62, wspace=0.28)
    for index, ticker in enumerate(tickers):
        ax = fig.add_subplot(grid[0, index])
        data = caps[caps["ticker"] == ticker].sort_values("date")
        event = reanchor[reanchor["ticker"] == ticker].iloc[0]
        ax.step(data["date"], data["market_cap_bn"], where="post", color=NEUTRAL, linewidth=2.0, zorder=3)
        ax.plot(data["date"], data["rolled_cap_bn"], color=BEFORE_COSTS, zorder=4)
        ax.plot([event["reanchor_date"]], [event["rolled_estimate_bn"]], marker="o", markersize=7,
                markerfacecolor=SURFACE, markeredgecolor=BEFORE_COSTS, markeredgewidth=2, zorder=5)
        panel_heading(ax, f"{ticker}, re-anchor error {pct(event['error_pct'], 2)}",
                      f"reported {data['market_cap_bn'].iloc[0]:,.2f} then {data['market_cap_bn'].iloc[-1]:,.2f} bn")
        ax.set_xticks([data["date"].iloc[0], event["reanchor_date"], data["date"].iloc[-1]],
                      [f"{d.day} {d:%b}" for d in (data["date"].iloc[0], event["reanchor_date"],
                                                    data["date"].iloc[-1])])
        ax.tick_params(axis="x", labelsize=9.5)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
        if index == 0:
            ax.set_ylabel("Market cap, $ billion")

    bottom = fig.add_subplot(grid[1, :])
    markers = {0: ("o", NEUTRAL), 1: ("s", FEES)}
    for index, (year, group) in enumerate(updates.groupby("year", sort=True)):
        marker, color = markers[index % 2]
        bottom.plot(group["month"], group["cap_unchanged_share"] * 100.0, color=color, marker=marker,
                    markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5, label=str(year), zorder=3)
    bottom.set_xticks(range(1, 13), [f"{pd.Timestamp(2019, m, 1):%b}" for m in range(1, 13)])
    bottom.set_ylim(90, 100.8)
    bottom.set_yticks(range(90, 101, 2))
    bottom.yaxis.set_major_formatter(FuncFormatter(pct_axis))
    later = updates[updates["month"] > 1]
    moved = updates[updates["cap_moved_with_price_share"] > 0]
    panel_heading(bottom, "Top 100 by market cap: share of day-to-day comparisons with the cap unchanged",
                  f"February to December {later['cap_unchanged_share'].min() * 100:.1f}% to "
                  f"{later['cap_unchanged_share'].max() * 100:.1f}%; in {len(updates) - len(moved)} of "
                  f"{len(updates)} months the cap never moved in step with the price")
    bottom.legend(loc="lower right", ncol=2, handlelength=2.0)

    errors = reanchor["error_pct"]
    below = header(
        fig,
        "Fundamental.market_cap held one value through January 2019 while prices moved daily",
        "Top: the reported cap (grey steps) and the daily cap v4 rolls forward from it with the adjusted price "
        "(blue, rank_space.DailyCaps). At the 1 February re-anchor the rolled value (open circle) was "
        f"{pct(errors.min(), 2)} to {pct(errors.max(), 2)} from the new snapshot (cap_probe_2019.csv, "
        "cap_probe_reanchor.csv). Bottom: the 100 largest companies, per month (market_cap_updates.csv); "
        "January is 100% because the probe starts on 1 January.",
        gap=0.055,
    )
    handles = [Line2D([], [], color=NEUTRAL, linewidth=2.5, label="Reported market_cap"),
               Line2D([], [], color=BEFORE_COSTS, linewidth=2.5, label="Rolled forward daily (v4)")]
    grid.update(top=plot_top(fig, legend_row(fig, below, handles, ncol=2), 0.62))
    return save(fig, "data_check.png")


GROUPS = (
    ("current", "Current: v4 windows"),
    ("superseded", "Superseded: v1 to v3, monthly market cap"),
    ("check", "Checks: re-runs, control, v4 code with v3 settings, half legs"),
)
SHORT_LABEL = {
    "sa__v1": "v1, 2010 to 2024",
    "sa__v2": "v2, 2018 to 2024",
    "sa__v3_2011": "v3, 2011 to 2017",
    "sa__v3_2018": "v3, 2018 to 2024",
    "rerun__sa_v3_2018": "v3 re-run, 2018 to 2024",
    "control__sa_v3_2018_recorded_code": "v3 control, 2018 to 2024",
    "check__v3_via_params_2018": "v4 code, v3 settings",
    "rerun__sa_v3_2011": "v3 re-run, 2011 to 2017",
    "sa__half_leg_2011": "v3 half legs, 2011 to 2017",
    "sa__half_leg_2018": "v3 half legs, 2018 to 2024",
}
OVERVIEW_ORDER = ("sa__v1", "sa__v2", "sa__v3_2011", "sa__v3_2018", "rerun__sa_v3_2011", "rerun__sa_v3_2018",
                  "control__sa_v3_2018_recorded_code", "check__v3_via_params_2018", "sa__half_leg_2011",
                  "sa__half_leg_2018")


def runs_overview(run_table: pd.DataFrame) -> Path:
    strategy = run_table[run_table["role"] != "reference"]
    keys = []
    for role, _ in GROUPS:
        members = strategy[strategy["role"] == role]
        if role == "current":
            members = members.sort_values("configured_start")
            keys.append((role, list(members.index)))
        else:
            keys.append((role, [key for key in OVERVIEW_ORDER if key in members.index]))
    # Row positions, top to bottom, with a blank row for each group heading.
    positions, labels, row_keys, headings = [], [], [], []
    y = 0.0
    for (role, members), (_, heading) in zip(keys, GROUPS):
        headings.append((y, heading))
        y -= 1.0
        for key in members:
            row = strategy.loc[key]
            positions.append(y)
            labels.append(SHORT_LABEL.get(key, row["label"]))
            row_keys.append(key)
            y -= 1.0
        y -= 0.35
    rows = strategy.loc[row_keys]
    colors = [BEFORE_COSTS if role == "current" else NEUTRAL for role in rows["role"]]

    fig = plt.figure(figsize=(12, 10.4))
    grid = fig.add_gridspec(1, 4, width_ratios=[2.5, 1.05, 1.0, 1.3], left=0.17, right=0.985, top=0.80,
                            bottom=0.06, wspace=0.12)
    timeline, net_ax, fee_ax, order_ax = (fig.add_subplot(grid[0, index]) for index in range(4))
    height = 0.62
    for ax in (timeline, net_ax, fee_ax, order_ax):
        ax.set_ylim(y + 0.6, 0.7)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", length=0)
        ax.set_yticks(positions, labels if ax is timeline else [""] * len(positions))
    # Group headings start at the figure's left edge, on the blank row above each group.
    heading_transform = blended_transform_factory(fig.transFigure, timeline.transData)
    for heading_y, heading in headings:
        timeline.text(0.012, heading_y - 0.1, heading, transform=heading_transform, ha="left", va="center",
                      fontsize=10.5, fontweight="bold", color=INK)

    for position, color, (_, row) in zip(positions, colors, rows.iterrows()):
        start = mdates.date2num(pd.Timestamp(row["configured_start"]))
        stop = mdates.date2num(pd.Timestamp(row["last_date_traded"]))
        end = mdates.date2num(pd.Timestamp(row["configured_end"]) + pd.Timedelta(days=1))
        timeline.barh(position, stop - start, left=start, height=height, color=color, linewidth=0)
        if end - stop > 3:
            timeline.barh(position, end - stop, left=stop, height=height, color=BAND, linewidth=0)
    timeline.xaxis_date()
    timeline.xaxis.set_major_locator(mdates.YearLocator(2))
    timeline.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    timeline.set_xlim(mdates.date2num(pd.Timestamp("2009-10-01")), mdates.date2num(pd.Timestamp("2025-03-01")))
    timeline.set_title("Configured window", fontsize=11)

    net = rows["net_profit"].to_numpy(dtype=float)
    span = max(abs(net).max(), 1.0)
    net_ax.barh(positions, net, height=height, color=colors, linewidth=0)
    net_ax.axvline(0, color=AXIS, linewidth=1.0)
    net_ax.set_xlim(min(net.min(), 0) - span * 0.75, max(net.max(), 0) + span * 0.75)
    for position, value in zip(positions, net):
        offset = span * 0.05 if value >= 0 else -span * 0.05
        net_ax.text(value + offset, position, pct(value), va="center", ha="left" if value >= 0 else "right",
                    fontsize=9.5, color=INK)
    net_ax.set_title("Net return", fontsize=11)
    net_ax.xaxis.set_major_formatter(FuncFormatter(pct_axis))

    fees = rows["total_fees"].to_numpy(dtype=float)
    fee_ax.barh(positions, fees, height=height, color=colors, linewidth=0)
    fee_ax.set_xlim(0, fees.max() * 1.55)
    for position, value in zip(positions, fees):
        fee_ax.text(value + fees.max() * 0.04, position, money_k(value, False), va="center", fontsize=9.5,
                    color=INK)
    fee_ax.set_title("Fees paid", fontsize=11)
    fee_ax.xaxis.set_major_locator(plt.MaxNLocator(3))
    fee_ax.xaxis.set_major_formatter(FuncFormatter(money_axis))

    total = rows["orders"].to_numpy(dtype=float)
    filled = rows["orders_filled"].to_numpy(dtype=float)
    rejected = rows["orders_invalid"].to_numpy(dtype=float)
    other = total - filled - rejected
    order_ax.barh(positions, filled, height=height, color=colors, linewidth=0)
    order_ax.barh(positions, rejected, left=filled, height=height, color=AFTER_COSTS, linewidth=0)
    order_ax.barh(positions, other, left=filled + rejected, height=height, color=AXIS, linewidth=0)
    for position, value, count in zip(positions, rejected, total):
        if value / count >= 0.01:
            order_ax.text(count + 250, position, f"{value / count * 100:.0f}% rejected", va="center",
                          fontsize=9.5, color=INK)
    order_ax.axvline(10_001, color=MUTED, linewidth=1.0, zorder=1)
    order_ax.set_xlim(0, 16_500)
    order_ax.set_xticks([0, 5_000, 10_000])
    order_ax.set_title("Orders by final status", fontsize=11)
    order_ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:,.0f}k"))

    capped = rows["order_cap_hit"].notna().sum()
    share = rows["orders_invalid"] / rows["orders"] * 100.0
    heavy = share[share >= 10.0]
    light = share[share < 10.0]
    v4_count = int((rows["role"] == "current").sum())
    below = header(
        fig,
        f"{capped} of the {len(rows)} strategy backtests stopped at QuantConnect's 10,000-order cap before "
        "their configured end",
        f"Blue: v4, the current version, in {WORDS.get(v4_count, v4_count)} windows. Grey: superseded runs and "
        "checks. Each timeline bar is dark up to the last fill and light where the order cap left the "
        "configured window unrun. Net return, fees and orders are QuantConnect's figures to the stop, from "
        f"runs.csv; the hairline in the orders panel marks 10,001 orders. "
        f"{WORDS.get(len(heavy), str(len(heavy))).capitalize()} runs had {heavy.min():.0f}% to "
        f"{heavy.max():.0f}% of their orders rejected for margin, the others at most {light.max():.1f}%. The "
        "SPY reference is left out.",
        gap=0.042,
    )
    handles = [Patch(color=BEFORE_COSTS, label="v4 (current)"), Patch(color=NEUTRAL, label="superseded or check"),
               Patch(color=BAND, label="not run (order cap)"), Patch(color=AFTER_COSTS, label="rejected orders"),
               Patch(color=AXIS, label="cancelled or open orders")]
    legend_bottom = legend_row(fig, below, handles, ncol=5, handlelength=1.2, columnspacing=1.4,
                               handletextpad=0.5, fontsize=10)
    grid.update(top=plot_top(fig, legend_bottom, 0.4))
    return save(fig, "runs_overview.png")


def remove_stale() -> list[str]:
    removed = []
    for path in sorted(FIGURES.glob("*.png")):
        if path.name not in FIGURE_NAMES:
            path.unlink()
            removed.append(path.name)
    return removed


def main() -> None:
    style()
    run_table = runs()
    table = summary()
    written = (rank_vs_name(table), v4_windows(table), costs(table, run_table), data_check(),
               runs_overview(run_table))
    for path in written:
        print(f"wrote {path.relative_to(REPO).as_posix()}")
    for name in remove_stale():
        print(f"removed figures/{name}")


if __name__ == "__main__":
    main()
