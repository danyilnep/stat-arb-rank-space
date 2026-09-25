# Received material from the 2024 project

This folder is a record of the 2024 attempt at the rank-space paper by the Mercury Capital
Management quant team, led by Danyil Nepyivoda, November 2024. It is kept so that the audit in [docs/audit-2024-cnn.md](../docs/audit-2024-cnn.md) can be checked
against the original material. Nothing in this folder is used by the 2026 implementation.

## Files

| File | Written by | What it is | How it arrived |
|---|---|---|---|
| `01_data.py` | A member of the 2024 team | Research notebook 1: data gathering, 1-minute market capitalisations, the risk-free adjustment and the PCA residuals. Written for QuantConnect's research environment (`QuantBook`) | Sent to Danyil Nepyivoda on WhatsApp on 28 November 2024 as the cells of a QuantConnect research notebook; reconstructed on 22 September 2026 (see below) |
| `02_cnn.py` | A member of the 2024 team | Research notebook 2: the convolutional network, its custom loss, the test evaluation and the save to QuantConnect's ObjectStore. Reads the files written by notebook 1 | As `01_data.py` |
| `deck.pptx` | The quant team | The team's 12-slide presentation "Statistical Arbitrage in Rank Space" | Received as a file named `Eldorado_Gold_Pitch.pptx`; the file name does not match the content. Renamed `deck.pptx` here; the other team members' names were removed from the title slide, the package parts that held personal data and the thumbnail were removed, and the other slides are unchanged (see below). The channel it arrived through is not recorded |
| `backtest-2015-2020.png` | Screenshot of a QuantConnect backtest run in the account of a member of the 2024 team | The results image on slide 11 of the deck: January 2015 to about January 2020, return 86.45%, PSR 23.624% | Extracted from the deck; byte-identical to `ppt/media/image9.png` inside `deck.pptx` |
| `notebook-test-curve.png` | Output of the plotting cell of `02_cnn.py` | The notebook's test-set chart, "Cumulative Returns: Predicted vs. Benchmark", on slide 9 of the deck | Extracted from the deck; byte-identical to `ppt/media/image3.png` inside `deck.pptx` |

## How the notebooks were reconstructed

The WhatsApp export lost every line break, so the code arrived as run-on text. On 22 September
2026 the line breaks, the indentation and the boundaries between cells were restored, and each
cell was marked with a `# %%` line so the files open as notebooks in editors that understand
that marker. A short provenance header was added at the top of each file (the
`# %% [markdown]` cell, lines 1 to 9 of `01_data.py` and lines 1 to 8 of `02_cnn.py`).

Apart from the restored line breaks and indentation, the cell markers and that header, the code
is verbatim as received, bugs included. No statement was added, removed, reordered or corrected. The notebooks
have not been run since; they need a QuantConnect research node, and their outputs other than
the chart in `notebook-test-curve.png` were never received.

## Personal data and names removed from the deck

On 25 September 2026 the parts of the `deck.pptx` package that held personal data were removed:
the comment authors (`ppt/authors.xml`), the one slide comment, the revision records
(`ppt/changesInfos/`, `ppt/revisionInfo.xml`), `customXml/` and `docProps/custom.xml` where
present, together with their relationships and content-type entries.

On the same date the names of the other team members were removed from the title slide, which now reads
"Quant Team: Danyil (Head)", and the package thumbnail (`docProps/thumbnail.jpeg`, a picture of
that slide) was dropped with its relationship. Slides 2 to 12, their text and media and the core
properties (title, creator, dates) are unchanged, and the cleaned file passes the Office package
validator.

## What was never received

- **The trading algorithm:** the QuantConnect algorithm behind the 86.45% backtest is in the
  QuantConnect account of a member of the 2024 team. Its code, orders, trades and full statistics were never
  received, so the screenshot is the only evidence of that backtest.
- **The trained model:** the notebook saved only the network's configuration to the ObjectStore,
  not its weights (see finding 10 of the audit), and no weights file exists.
- **Notebook outputs:** no printed results (total return, Sharpe ratio) and no data files
  (`adjusted_returns.pkl`, `phi_t.npy`) were received.
- **The source of the deck's other figures:** the deck's "Win rate on trades: 89%", "Sharpe ratio:
  0.7" and "Compound returns: 14%" (slide 11) are not computed in either notebook.
- **Any code for the parametric model:** slides 4 to 6 describe the parametric OU model; no code
  for it was received.

## Checksums

SHA-256 of each file as published here, computed on 25 September 2026 after the header edits
and the removals described above:

| File | SHA-256 |
|---|---|
| `01_data.py` | `16076c241cc25f17ea7b5b1c73289494ac7220f885f4590d483ab0d417ef7eb8` |
| `02_cnn.py` | `7d8ab2ff0e3513875d6757fa22f2885ba5ba673363a9708335f09d992012f413` |
| `deck.pptx` | `a597d3c75de25c73bd06f69fad1d5dc07bdc490d2ecd45a00b13f589e05fe30b` |
| `backtest-2015-2020.png` | `233fb6fa886714dd012eeab99d3f05b6d15b01f27705d5e762d91b060342b0e7` |
| `notebook-test-curve.png` | `652be65b89cc0629bf824d99de97017555fba4545ad2af807af34d50a8e6b1d9` |

## Licence

The files in this folder are **not** covered by the MIT licence in [LICENSE](../LICENSE). They
are the work of the 2024 Mercury Capital Management quant team, reproduced here as a record,
and are not relicensed. The MIT licence covers the rest of the repository.
