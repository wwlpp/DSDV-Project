# Data Schema v1


## 1. Files

| File | Written by | Read by | Notes |
|---|---|---|---|
| `data/raw/prices.csv` | manual download (vnstock) | `build_dataset.py` | Never edit by hand |
| `data/raw/vnindex.csv` | manual download (vnstock) | `build_dataset.py` | Never edit by hand |
| `data/processed/returns.csv` | `build_dataset.py` | `verify.py`, analysis | Daily log returns |
| `data/processed/correlations_long.csv` | `build_dataset.py` | `verify.py` | One row per window, mode, pair |
| `data/processed/summary.csv` | `build_dataset.py` | `timeline.js` | Average correlation per window and mode |
| `data/processed/network_data.json` | `build_dataset.py` | **the web** | Main file, schema below |
| `data/processed/centrality.json` | `src/export_centrality.py` (Lợi) | `js/data.js` (ranking, Analysis) | Schema in section 3. Pre-computed, 9 thresholds |
| `data/processed/cluster_order.json` | Lợi | `matrix.js` | Schema in section 4 (due 26/11) |
| `js/data_bundle.js` | `src/make_bundle.py` | `index.html` (file:// mode) | Generated. Re-run after any change in `data/processed/` |

Rule: `data/raw/` is immutable. Every processing step writes to `data/processed/`.

---

## 2. `network_data.json`

```json
{
  "meta": {
    "description": "Rolling correlation of daily log returns among listed Vietnamese banks (proxy co-movement network).",
    "source": "vnstock (VCI), community edition",
    "window_days": 250,
    "step_days": 20,
    "residual_note": "residual = bank return minus beta * VN-Index return, beta estimated within each window",
    "n_windows": 88,
    "first_window_end": "2019-10-09",
    "last_window_end": "2026-09-30"
  },
  "banks":   [ { "id": "VCB", "group": "state" }, ... ],
  "pairs":   [ [0, 1], [0, 2], ... ],
  "windows": [ { "end": "2019-10-09", "raw": [ ... ], "residual": [ ... ] }, ... ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `meta.window_days` | int | Rolling window length in trading days (250) |
| `meta.step_days` | int | Step between windows in trading days (20) |
| `meta.n_windows` | int | Number of windows (88) |
| `banks` | array of 19 objects | Fixed order. Index in this array is the **bank index** used everywhere else |
| `banks[i].id` | string | Ticker, for example `"VCB"` |
| `banks[i].group` | string | `"state"` or `"private"` (see section 5) |
| `pairs` | array of 171 `[i, j]` | Bank indices with `i < j`, in lexicographic order. 171 = 19 × 18 / 2 |
| `windows[k].end` | string `YYYY-MM-DD` | Last trading day of window `k`. Windows are in time order |
| `windows[k].raw` | array of 171 | Correlation of each pair, **same order as `pairs`**, raw returns |
| `windows[k].residual` | array of 171 | Same, after removing the VN-Index effect |

How to read one value: the correlation between `banks[a]` and `banks[b]` in window `k`, raw mode, is `windows[k].raw[p]` where `pairs[p] = [a, b]` and `a < b`.

Values are rounded to 3 decimals and lie in `[-1, 1]`.

### Null rule

A value is `null` when either bank has too little data in that window (less than 80% of the window's days). Every view must handle it:

- Network: the node is grey, has no edges, and is not counted in averages.
- Matrix: the cell is grey.
- Averages and rankings: skip `null`, never treat it as 0.

Number of banks with data per window (from `summary.csv`, column `n_banks`):

| Banks with data | Windows | Window end dates |
|---|---|---|
| 15 | 23 | 2019-10-09 to 2021-07-13 |
| 16 | 3 | 2021-08-10 to 2021-10-07 |
| 18 | 1 | 2021-11-04 |
| 19 | 61 | 2021-12-02 to 2026-09-30 |

The late-listed banks are NAB (10/2020), MSB (12/2020), ABB (12/2020), OCB (01/2021). SSB is excluded from the data set because it has only about 69% of trading days.

---

## 3. `centrality.json` (`src/export_centrality.py`)

Pre-computed centrality for every window, on a fixed grid of thresholds. About 916 KB. Bank arrays follow the order of `banks`. Windows follow the order of `network_data.json`.

```json
{
  "meta": {
    "window_days": 250, "step_days": 20, "n_windows": 88,
    "thresholds": ["0.30", "0.35", "...", "0.70"],
    "default_threshold": "0.50",
    "floor": 0.05,
    "modes": { "raw": "...", "residual": "...", "residual_matched": "..." },
    "pagerank": "weighted by corr, damping 0.85, active banks only ...",
    "null_note": "null = bank has no data in that window"
  },
  "banks": ["VCB", "BID", "..."],
  "windows": [
    {
      "end": "2019-10-09",
      "n_active": 15,
      "active": [1, 1, 0, "..."],
      "metrics": {
        "0.50": {
          "raw":              { "threshold": 0.5, "n_edges": 64, "pagerank": [], "degree": [], "strength": [] },
          "residual":         { "threshold": 0.5, "n_edges": 6,  "pagerank": [], "degree": [], "strength": [] },
          "residual_matched": { "threshold": 0.225, "n_edges": 64, "matched_threshold": 0.225,
                                "floor_hit": false, "pagerank": [], "degree": [], "strength": [] }
        }
      }
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `windows[k].active` | 1 if the bank has data in window `k`, else 0 |
| `windows[k].n_active` | Number of active banks |
| `metrics["0.50"]` | Key is the **raw** threshold on the grid (0.30 to 0.70, step 0.05), written with 2 decimals |
| `raw` | Edge if raw correlation is at or above the key threshold |
| `residual` | Edge if residual correlation is at or above the key threshold |
| `residual_matched` | Web default for residual. Threshold = n-th largest residual correlation, n = number of raw edges at the key threshold, then `max(matched, 0.05)` |
| `threshold` | Threshold actually used. `1.01` means no edge can pass |
| `floor_hit` | `true` when the 0.05 floor replaced a lower matched value (residual network has fewer edges than raw) |
| `pagerank` | Weights = correlations, damping 0.85, **active banks only**. Isolated active banks share rank equally. 5 decimals. `null` for inactive banks |
| `degree`, `strength` | Edge count and sum of correlations. `strength` has 3 decimals. `null` for inactive banks |

How the web uses it (`DSDV.data.metrics()` in `js/data.js`):

| UI setting | Variant read |
|---|---|
| `mode = raw` | `raw` |
| `mode = residual`, `matchRawEdges = true` | `residual_matched` |
| `mode = residual`, `matchRawEdges = false` | `residual` |

- If `threshold` is one of the 9 grid values and the window `end` matches, the web reads the file (badge: "Source: centrality.json (verified)").
- Otherwise (for example threshold 0.42) the web computes the same measures in the browser with the same rules (floor 0.05, active banks only, damping 0.85). Both sources agree to within 0.000005 (checked on all 2376 window, threshold and mode combinations).
- Analysis tab (Q1, Q4): reads the 9-threshold grid directly.

**Regenerate order.** `centrality.json` does not update by itself. After any change in `network_data.json` (new data, changed ownership group), run in this order and commit all outputs:

```
python src/build_dataset.py
python src/export_centrality.py
python src/make_bundle.py
```

Then run `python src/make_bundle.py --check`; it must print `OK: bundle matches sources`.

---

## 4. `cluster_order.json` (Lợi, due 26/11)

```json
{
  "meta": { "method": "describe how the clusters were found" },
  "order": ["VCB", "BID", "CTG", "..."],
  "cluster": { "VCB": 0, "BID": 0, "TCB": 1 }
}
```

`order` lists all 19 bank ids in the order the matrix should draw them. `cluster` maps a bank id to a cluster number.

---

## 5. Ownership group

Two values only: `"state"` and `"private"`. Assigned by hand from public sources.

| Group | Banks | Source |
|---|---|---|
| state | VCB, BID, CTG | To be recorded by Phương (due 19/11) |
| private | the other 16 | To be recorded by Phương (due 19/11) |

Current state of the code: `build_dataset.py` sets `VCB`, `BID`, `CTG` to `state` and everything else to `private` by default. The assignment must be checked and the source written in the table above before 19/11. If any group changes, update `GROUPS` in `src/build_dataset.py`, re-run the script and tell the team.

---

## 6. CSV files

| File | Columns |
|---|---|
| `prices.csv` | `time`, then one closing-price column per ticker (20 tickers incl. SSB). Empty cell = not listed yet. Never fill with 0 |
| `vnindex.csv` | `time`, `VNINDEX` |
| `returns.csv` | `time`, then 19 ticker columns of daily log return `ln(P_t / P_t-1)`. Empty cell = no data |
| `correlations_long.csv` | `window_end`, `mode` (`raw` or `residual`), `bank_a`, `bank_b`, `corr`. Rows with `null` correlation are not written |
| `summary.csv` | `window_end`, `mode`, `avg_corr` (mean of non-null pair correlations), `n_banks` |

Check values: latest window (2026-09-30), `avg_corr` raw 0.4365, residual 0.2026. These must match the proposal (0.436 and 0.203).

---

## 7. Shared UI state (Tín, Đạt)

Names are frozen and match `js/state.js`. All views read and write the same state through `DSDV.state.get()`, `DSDV.state.set(patch, source)` and `DSDV.state.on(fn)`. Do not add fields without telling the whole team.

| Name | Type | Values |
|---|---|---|
| `mode` | string | `"raw"` or `"residual"`. Default `"raw"` |
| `windowIndex` | int | `0` to `87`, index into `windows`. Default `87` (window ending 2026-09-30) |
| `threshold` | float | Correlation cutoff for an edge, range 0.05 to 0.90. Default `0.50` |
| `matchRawEdges` | bool | In residual mode, match the raw edge count with floor 0.05. Default `true` |
| `selectedBank` | string or `null` | Bank id such as `"MBB"`, never an index |
| `selectedPair` | string or `null` | Sorted key such as `"MBB|TCB"` |
| `playing` | bool | Auto-play over time |
| `activeTab` | string | `"network"`, `"matrix"`, `"analysis"` or `"about"` |

Rule: selecting a bank in any view sets `selectedBank`, and every view must highlight it. Views register themselves as `DSDV.views.<name>` (for example `DSDV.views.network` mounts into `#view-network`). Do not edit `index.html`, `main.js` or `state.js` outside a pull request.


