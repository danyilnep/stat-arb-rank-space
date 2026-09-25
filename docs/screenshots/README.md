# Screenshots to add

Three QuantConnect screenshots belong in the main README. They are not generated here: Danyil
Nepyivoda takes them from his QuantConnect account and saves them in this folder under the exact
filenames below. Until a file exists, the README line that shows it stays commented out, so no
broken image appears on GitHub.

All three come from v4 backtests in project **36836415, "Rank Space Stat Arb Alg 1-2"**. Open the
project in QuantConnect, go to its backtest list and pick the backtest by name or id.

## Checklist

- [ ] **`qc-v4-2018-overview.png`**
  - Backtest: "v4 daily caps 2018-2024", id `13c6fd60817d82bd142f2d9e56a540af` (the 2018 to
    2019 window, code defaults).
  - Capture: the backtest results page with the headline statistics row at the top and the
    custom chart **"Rank vs name"** visible, both series showing ("rank space, paper weights,
    before costs" and "name space, realised, after costs"). If the page opens on "Strategy
    Equity", select "Rank vs name" in the chart list first.
- [ ] **`qc-v4-2011-overview.png`**
  - Backtest: "v4 daily caps 2011-2017", id `ce4bc7c34bd41a5dba61822863beffdf` (the 2011 to
    2012 window).
  - Capture: the same view as above, with "Rank vs name" visible.
- [ ] **`qc-v4-2018-report.png`**
  - Backtest: "v4 daily caps 2018-2024", id `13c6fd60817d82bd142f2d9e56a540af`.
  - Capture: the first page of its QuantConnect report (the report tab of the backtest). The
    repository keeps QuantConnect's reports only for the superseded v3 runs
    ([`results/superseded/v3_2011_2017/qc_report.html`](../../results/superseded/v3_2011_2017/qc_report.html)),
    so this one has to come from QuantConnect.

## How to take them

- PNG, about 1,600 pixels wide, light theme.
- Crop to the QuantConnect page content: leave out the browser bar, the account name and avatar,
  and any organisation or billing banner.
- Check that the statistics in the image match the run: net profit +8.920% for the 2018 to 2019
  window and −8.460% for the 2011 to 2012 window
  ([results/v4/summary.csv](../../results/v4/summary.csv)).
- Keep each file under 1 MB if possible, so the repository stays small.

## Switching the images on in the README

The main [README](../../README.md) carries one commented-out line per screenshot, in the form

```html
<!-- ![Rank vs name, v4 2018 to 2019 window](docs/screenshots/qc-v4-2018-overview.png) -->
```

After adding a file here, open `README.md`, find the line that names that file, and delete the
opening `<!-- ` and the closing ` -->` so that only the `![...](...)` part remains. Search the
README for `docs/screenshots/qc-` to find all three lines. Once all three are in, also change the
sentence at the top of the README's Screenshots section, which says that none has been added
yet. Then commit the images and the README change together, run `python analysis/check_docs.py`
(it checks that every image the README shows exists), and check the rendered README on GitHub.
