"""
Verify the numbers shown on the web against an independent Python recomputation. Tolerance: 0.001.

Checks
    1. returns.csv           == log returns recomputed from data/raw/prices.csv
    2. network_data.json     == rolling correlations recomputed from returns
                                (raw and residual, all windows, all pairs)
    3. summary.csv           == mean of the correlations in network_data.json
    4. centrality.json       == PageRank / degree / strength recomputed with a
                                plain power iteration (no networkx), incl. the
                                floor rule and nulls for inactive banks
    5. web                   == Python, using docs/web_snapshot.json (values
                                computed by js/data.js at slider values
                                0.05, 0.30, 0.50, 0.70, 0.90 in 6 windows)

Shared rules with js/data.js (must stay identical on both sides):
    D1  residual matched threshold = max(n-th largest residual corr, 0.05)
    D2  PageRank over the active banks of the window only, damping 0.85

The recomputation deliberately uses other code paths than the pipeline:
OLS with intercept (np.polyfit) for the residuals, np.corrcoef for the
correlations, and a hand-written PageRank.

Run from the repo root:
    python src/verify.py
Writes docs/verify_log.txt and exits with code 1 if any check fails.

To refresh docs/web_snapshot.json after the web code changes: open index.html,
press F12, paste this in the Console, then paste the clipboard into the file
(keep the "note" line if you like; only "cases" is read):

copy((() => { const d = DSDV.data, ids = d.bankIds(), cases = [], r = (v, k) => v == null ? null : +v.toFixed(k);
  for (const wi of [0, 22, 33, 44, 66, 87]) for (const thr of [0.05, 0.3, 0.5, 0.7, 0.9])
    for (const [mode, match, name] of [['raw', true, 'raw'], ['residual', true, 'residual_matched'], ['residual', false, 'residual']]) {
      const er = d.edges(wi, { mode, threshold: thr, matchRawEdges: match }), act = d.activeBanks(wi);
      const pr = d.pagerank(er.edges, act), ds = d.degreeStrength(er.edges, act);
      cases.push({ end: d.window(wi).end, mode: name, threshold: thr.toFixed(2), t: er.threshold, floor_hit: er.floorHit,
        n_edges: er.edges.length, pagerank: ids.map(i => r(pr[i], 6)), degree: ids.map(i => ds.degree[i]), strength: ids.map(i => r(ds.strength[i], 3)) }); }
  return JSON.stringify({ cases }); })())
"""
import argparse
import datetime
import json
import os
import sys

import numpy as np
import pandas as pd

TOL = 0.001
DAMPING = 0.85
FLOOR = 0.05                                      # D1
SAMPLE_WINDOWS = [0, 22, 33, 44, 66, -1]          # windows printed in detail
SAMPLE_PAIRS = [("VCB", "BID"), ("CTG", "MBB"), ("TCB", "VPB"),
                ("ACB", "STB"), ("TPB", "VIB"), ("MSB", "OCB")]

lines, failures = [], []


def log(msg=""):
    print(msg)
    lines.append(msg)


def check(name, ok, detail):
    log(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        failures.append(name)


# ---------- independent recomputation ----------
def corr_pair(x, y):
    ok = ~(np.isnan(x) | np.isnan(y))
    return float(np.corrcoef(x[ok], y[ok])[0, 1])


def residual(y, m):
    """Residual of an OLS regression y = a + b*m (with intercept)."""
    ok = ~(np.isnan(y) | np.isnan(m))
    b, a = np.polyfit(m[ok], y[ok], 1)
    out = np.full_like(y, np.nan)
    out[ok] = y[ok] - (a + b * m[ok])
    return out


def window_corr(win, mkt, banks, pairs, min_obs):
    """Return (raw, residual) lists in the order of `pairs`; None = no data."""
    keep = {b for b in banks if win[b].notna().mean() >= min_obs}
    x = {b: win[b].to_numpy() for b in keep}
    r = {b: residual(x[b], mkt) for b in keep}
    raw, res = [], []
    for i, j in pairs:
        a, b = banks[i], banks[j]
        if a in keep and b in keep:
            raw.append(corr_pair(x[a], x[b]))
            res.append(corr_pair(r[a], r[b]))
        else:
            raw.append(None)
            res.append(None)
    return raw, res


def pagerank(edges, n, active, iters=300):
    """Plain power iteration over the active banks only (D2).

    Weighted by correlation, damping 0.85, rank of isolated active banks is
    spread evenly among the active banks. Inactive banks get None.
    """
    ids = [i for i in range(n) if active[i]]
    pos = {b: k for k, b in enumerate(ids)}
    m = len(ids)
    s = [0.0] * m
    out = [[] for _ in range(m)]
    for a, b, c in edges:
        i, j = pos[a], pos[b]
        out[i].append((j, c))
        out[j].append((i, c))
        s[i] += c
        s[j] += c
    r = [1.0 / m] * m
    for _ in range(iters):
        new = [(1 - DAMPING) / m] * m
        dangling = 0.0
        for i in range(m):
            if s[i] == 0:
                dangling += r[i]
            else:
                for j, c in out[i]:
                    new[j] += DAMPING * r[i] * c / s[i]
        r = [v + DAMPING * dangling / m for v in new]
    full = lambda vals: [vals[pos[i]] if active[i] else None for i in range(n)]
    return full(r), full([len(o) for o in out]), full(s)


def matched_threshold(w, thr):
    """D1: (threshold used, floor_hit) for the residual network matching raw edge count."""
    n_raw = sum(1 for v in w["raw"] if v is not None and v >= thr)
    srt = sorted((v for v in w["residual"] if v is not None), reverse=True)
    matched = srt[min(n_raw, len(srt)) - 1] if (n_raw and srt) else 1.01
    return max(matched, FLOOR), matched < FLOOR


def max_diff(a, b):
    """Largest |a-b| over positions where both are not None; also count None mismatches."""
    d, mismatch = 0.0, 0
    for u, v in zip(a, b):
        if (u is None) != (v is None):
            mismatch += 1
        elif u is not None:
            d = max(d, abs(u - v))
    return d, mismatch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--processed-dir", default="data/processed")
    ap.add_argument("--web-snapshot", default="docs/web_snapshot.json")
    ap.add_argument("--log-file", default="docs/verify_log.txt")
    ap.add_argument("--min-obs", type=float, default=0.8)
    args = ap.parse_args()
    P = args.processed_dir

    log("VERIFY LOG - Risk Co-movement Network (DSDV project)")
    log(f"Run: {datetime.datetime.now():%Y-%m-%d %H:%M}   tolerance: {TOL}")
    log()

    with open(os.path.join(P, "network_data.json"), encoding="utf-8") as f:
        net = json.load(f)
    banks = [b["id"] for b in net["banks"]]
    pairs, windows, n = net["pairs"], net["windows"], len(banks)
    window, step = net["meta"]["window_days"], net["meta"]["step_days"]
    pair_index = {(banks[i], banks[j]): k for k, (i, j) in enumerate(pairs)}

    # ---- 1. returns ----
    log("1. Log returns (returns.csv vs prices.csv)")
    prices = pd.read_csv(os.path.join(args.raw_dir, "prices.csv"), index_col=0, parse_dates=True)
    prices = prices[~prices.index.duplicated()].sort_index()
    vn = pd.read_csv(os.path.join(args.raw_dir, "vnindex.csv"), index_col=0, parse_dates=True).iloc[:, 0]
    vn = vn[~vn.index.duplicated()].sort_index()
    ret_file = pd.read_csv(os.path.join(P, "returns.csv"), index_col=0, parse_dates=True)
    my_ret = np.log(prices[banks] / prices[banks].shift(1)).reindex(ret_file.index)
    d = float((my_ret - ret_file[banks]).abs().max().max())
    same_nan = bool((my_ret.isna() == ret_file[banks].isna()).all().all())
    check("returns", d < 1e-5 and same_nan and list(ret_file.columns) == banks,
          f"{len(ret_file)} days x {n} banks, max abs diff {d:.2e}, same empty cells: {same_nan}")
    mkt_all = np.log(vn / vn.shift(1)).reindex(ret_file.index)
    log()

    # ---- 2. correlations ----
    log("2. Rolling correlations (network_data.json vs recomputation from returns.csv)")
    ends = list(range(len(ret_file), window - 1, -step))[::-1]
    check("window dates", len(ends) == len(windows) and all(
        ret_file.index[e - 1].strftime("%Y-%m-%d") == w["end"] for e, w in zip(ends, windows)),
        f"{len(windows)} windows of {window} days, step {step}, "
        f"{windows[0]['end']} to {windows[-1]['end']}")
    worst = {"raw": 0.0, "residual": 0.0}
    mism = 0
    recomputed = []
    for e, w in zip(ends, windows):
        win = ret_file[banks].iloc[e - window:e]
        raw, res = window_corr(win, mkt_all.iloc[e - window:e].to_numpy(), banks, pairs, args.min_obs)
        recomputed.append({"raw": raw, "residual": res})
        for mode, mine in (("raw", raw), ("residual", res)):
            dd, mm = max_diff(mine, w[mode])
            worst[mode] = max(worst[mode], dd)
            mism += mm
    n_values = sum(1 for w in windows for m in ("raw", "residual") for c in w[m] if c is not None)
    check("correlations raw", worst["raw"] < TOL, f"max abs diff {worst['raw']:.5f} over all windows")
    check("correlations residual", worst["residual"] < TOL,
          f"max abs diff {worst['residual']:.5f} over all windows")
    check("null pattern", mism == 0, f"{n_values} values compared, {mism} null mismatches")
    log()
    log("   Sample (python = recomputed, json = network_data.json)")
    log(f"   {'window_end':<11}{'mode':<9}{'pair':<9}{'python':>9}{'json':>8}{'diff':>9}")
    for k in SAMPLE_WINDOWS:
        w = windows[k]
        for a, b in SAMPLE_PAIRS:
            idx = pair_index[(a, b)]
            for mode in ("raw", "residual"):
                mine, js = recomputed[k][mode][idx], w[mode][idx]
                if js is None:
                    log(f"   {w['end']:<11}{mode:<9}{a + '-' + b:<9}{'null':>9}{'null':>8}{'-':>9}")
                else:
                    log(f"   {w['end']:<11}{mode:<9}{a + '-' + b:<9}{mine:>9.4f}{js:>8.3f}{abs(mine - js):>9.5f}")
    log()

    # ---- 3. summary ----
    log("3. Average connectedness (summary.csv vs network_data.json)")
    summ = pd.read_csv(os.path.join(P, "summary.csv")).set_index(["window_end", "mode"])
    d, bad_n = 0.0, 0
    for w in windows:
        act = set()
        for kk, c in enumerate(w["raw"]):
            if c is not None:
                act.update(pairs[kk])
        for mode in ("raw", "residual"):
            v = [c for c in w[mode] if c is not None]
            row = summ.loc[(w["end"], mode)]
            d = max(d, abs(float(np.mean(v)) - row["avg_corr"]))
            bad_n += int(row["n_banks"] != len(act))
    check("summary avg_corr", d < TOL, f"max abs diff {d:.5f} over {len(summ)} rows")
    check("summary n_banks", bad_n == 0, f"{bad_n} rows with a different number of active banks")
    last = windows[-1]["end"]
    log(f"   last window {last}: raw {summ.loc[(last, 'raw'), 'avg_corr']:.4f}, "
        f"residual {summ.loc[(last, 'residual'), 'avg_corr']:.4f} (proposal: 0.436 and 0.203)")
    log()

    # ---- 4. centrality.json ----
    log("4. Centrality (centrality.json vs plain power-iteration recomputation)")
    with open(os.path.join(P, "centrality.json"), encoding="utf-8") as f:
        cen = json.load(f)
    check("centrality layout", cen["banks"] == banks and
          [w["end"] for w in cen["windows"]] == [w["end"] for w in windows],
          f"{len(cen['windows'])} windows, thresholds {', '.join(cen['meta']['thresholds'])}")
    worst = {"pagerank": 0.0, "degree": 0.0, "strength": 0.0}
    n_cases = bad = n_floor = 0
    for cw, w in zip(cen["windows"], windows):
        act = [bool(a) for a in cw["active"]]
        for thr, entry in cw["metrics"].items():
            for mode, m in entry.items():
                values = w["raw"] if mode == "raw" else w["residual"]
                t = float(thr)
                if mode == "residual_matched":
                    t, hit = matched_threshold(w, float(thr))
                    bad += int(hit != m["floor_hit"])
                    n_floor += hit
                bad += int(abs(t - m["threshold"]) > 1e-9)
                edges = [(pairs[k][0], pairs[k][1], c) for k, c in enumerate(values)
                         if c is not None and c >= t]
                bad += int(len(edges) != m["n_edges"])
                pr, deg, stg = pagerank(edges, n, act)
                for key, mine in (("pagerank", pr), ("degree", deg), ("strength", stg)):
                    dd, mm = max_diff(mine, m[key])
                    worst[key] = max(worst[key], dd)
                    bad += mm
                n_cases += 1
    check("pagerank", worst["pagerank"] < TOL, f"max abs diff {worst['pagerank']:.6f} over {n_cases} cases")
    check("degree", worst["degree"] == 0, f"max abs diff {worst['degree']:.0f}")
    check("strength", worst["strength"] < TOL, f"max abs diff {worst['strength']:.5f}")
    check("thresholds, edge counts, nulls", bad == 0,
          f"{bad} inconsistencies; floor {FLOOR} applied in {n_floor} residual_matched cases")
    log()

    # ---- 5. web ----
    log("5. Web code (js/data.js) vs Python recomputation (docs/web_snapshot.json)")
    log("   Recomputed directly from network_data.json, so slider values that are")
    log("   not on the centrality.json grid are checked too.")
    if not os.path.exists(args.web_snapshot):
        log("   SKIPPED: no web snapshot file found.")
    else:
        with open(args.web_snapshot, encoding="utf-8") as f:
            snap = json.load(f)
        by_end = {w["end"]: (w, cw) for w, cw in zip(windows, cen["windows"])}
        log(f"   {'window_end':<11}{'slider':>6}  {'mode':<17}{'edges web/py':>13}{'thr web/py':>16}"
            f"{'PR diff':>10}{'deg':>5}{'str diff':>10}  result")
        n_hit = 0
        for c in snap["cases"]:
            w, cw = by_end[c["end"]]
            act = [bool(a) for a in cw["active"]]
            thr = float(c["threshold"])
            values = w["raw"] if c["mode"] == "raw" else w["residual"]
            t, hit = (matched_threshold(w, thr) if c["mode"] == "residual_matched" else (thr, False))
            n_hit += hit
            edges = [(pairs[k][0], pairs[k][1], v) for k, v in enumerate(values)
                     if v is not None and v >= t]
            pr, deg, stg = pagerank(edges, n, act)
            dpr, m1 = max_diff(c["pagerank"], pr)
            ddeg, m2 = max_diff(c["degree"], deg)
            dstg, m3 = max_diff(c["strength"], stg)
            ok = (dpr < TOL and ddeg == 0 and dstg < TOL and m1 + m2 + m3 == 0
                  and c["n_edges"] == len(edges) and abs(c["t"] - t) < TOL
                  and bool(c.get("floor_hit", False)) == hit)
            # where centrality.json has this threshold, it must agree with the web too
            m = cw["metrics"].get(c["threshold"], {}).get(c["mode"])
            if m:
                ok = ok and max_diff(c["pagerank"], m["pagerank"])[0] < TOL \
                    and max_diff(c["degree"], m["degree"])[0] == 0 and c["n_edges"] == m["n_edges"]
            if not ok:
                failures.append(f"web {c['end']} {c['mode']} {c['threshold']}")
            log(f"   {c['end']:<11}{c['threshold']:>6}  {c['mode']:<17}"
                f"{str(c['n_edges']) + '/' + str(len(edges)):>13}"
                f"{c['t']:>9.3f}/{t:<6.3f}{dpr:>10.6f}{ddeg:>5.0f}{dstg:>10.5f}  "
                f"{'ok' if ok else 'FAIL'}{' (floor)' if hit else ''}")
        n_w = len({c["end"] for c in snap["cases"]})
        n_t = len({c["threshold"] for c in snap["cases"]})
        check("web vs python", not any(f.startswith("web") for f in failures),
              f"{len(snap['cases'])} cases ({n_w} windows x {n_t} slider values x 3 modes); "
              f"floor {FLOOR} applied in {n_hit} of them, same on both sides")
    log()

    log(f"RESULT: {'ALL CHECKS PASSED' if not failures else 'FAILED: ' + '; '.join(failures)}")
    os.makedirs(os.path.dirname(args.log_file) or ".", exist_ok=True)
    with open(args.log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
