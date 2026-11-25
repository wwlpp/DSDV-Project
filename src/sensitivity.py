"""
Sensitivity of the results (Q4): window length and threshold.

Input : data/raw/prices.csv, data/raw/vnindex.csv,
        data/processed/network_data.json, data/processed/centrality.json
Output: data/processed/sensitivity.json   
        docs/sensitivity/                  

Part A - window length (fixed scope: 120 / 250 / 500 trading days, step 20)
    Re-runs exactly the pipeline of build_dataset.py (same residual_returns
    function, same 80% data rule, same window ends counted back from the last
    day) for each window length. Because every length counts back from the
    same last day with step 20, the lengths share window end dates and can be
    compared window by window.
    Per window: avg corr raw / residual, number of banks, PageRank at
    threshold 0.50 (raw and residual_matched, same rules as export_centrality.py).
    Self-check: the 250-day run must reproduce network_data.json.

Part B - threshold (fixed scope: 0.30 -> 0.70, step 0.05; 250-day windows)
    Reads centrality.json: edge counts, density, and how well the ranking at
    each threshold agrees with the default 0.50 (Spearman of PageRank, share
    of banks that keep the same tier).

Part C - Q4 tables and figures (docs/sensitivity/)
    threshold_sensitivity.csv, window_length_sensitivity.csv, last_window_tiers.csv,
    edges_vs_threshold.png, ranking_vs_threshold.png, avg_corr_by_window_length.png,
    README.md. Figures need matplotlib; without it the script still writes the
    JSON and the CSV files.

Tier (same as the About tab of the web): baseline = 1/N_active;
    core      PageRank >= 1.5 * baseline
    periphery PageRank <= 0.5 * baseline
    middle    otherwise

Run from the repo root:
    python src/sensitivity.py
    python src/sensitivity.py --docs-dir docs/sensitivity
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_dataset import residual_returns, upper_values          # noqa: E402
from export_centrality import (active_banks, build_edges,          # noqa: E402
                               matched_threshold, metrics)

LENGTHS = [120, 250, 500]
STEP = 20
MIN_OBS = 0.8
PR_THRESHOLD = 0.50
DEFAULT_KEY = "0.50"
CENTRAL_MODES = ("raw", "residual_matched")

# helpers
def tier(pr, n_active):
    if pr is None:
        return None
    base = 1.0 / n_active
    if pr >= 1.5 * base:
        return "core"
    if pr <= 0.5 * base:
        return "periphery"
    return "middle"


def spearman_active(a, b):
    """Spearman between two PageRank arrays, over the banks that have a value in both."""
    x = [u for u, v in zip(a, b) if u is not None and v is not None]
    y = [v for u, v in zip(a, b) if u is not None and v is not None]
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(spearmanr(x, y)[0])


def r4(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4)


def load_returns(raw_dir):
    """Identical to steps 1-2 of build_dataset.py."""
    prices = pd.read_csv(os.path.join(raw_dir, "prices.csv"), index_col=0, parse_dates=True)
    prices.index = prices.index.normalize()
    prices = prices[~prices.index.duplicated()].sort_index()
    vn = pd.read_csv(os.path.join(raw_dir, "vnindex.csv"), index_col=0, parse_dates=True).iloc[:, 0]
    vn.index = vn.index.normalize()
    vn = vn[~vn.index.duplicated()].sort_index()
    ret = np.log(prices).diff().dropna(how="all")
    ret = ret.dropna(axis=1, thresh=int(len(ret) * 0.7))
    mkt = np.log(vn).diff().dropna()
    idx = ret.index.intersection(mkt.index)
    return ret.loc[idx], mkt.loc[idx]


def run_length(ret, mkt, length, pairs):
    """The build_dataset.py pipeline with window length `length`; returns a list of windows."""
    banks = list(ret.columns)
    n = len(banks)
    ends = list(range(len(ret), length - 1, -STEP))[::-1]
    out = []
    for e in ends:
        w = ret.iloc[e - length:e]
        keep = [c for c in banks if w[c].notna().mean() >= MIN_OBS]
        wk = w[keep]
        raw = upper_values(wk.corr(), banks, pairs)
        res = upper_values(residual_returns(wk, mkt).corr(), banks, pairs)
        win = {"end": ret.index[e - 1].strftime("%Y-%m-%d"), "raw": raw, "residual": res}
        act = active_banks(win, pairs, n)
        pr = {}
        pr["raw"] = metrics(build_edges(raw, pairs, PR_THRESHOLD), n, act)["pagerank"]
        t_match, _, _ = matched_threshold(win, PR_THRESHOLD)
        pr["residual_matched"] = metrics(build_edges(res, pairs, t_match), n, act)["pagerank"]
        out.append({
            **win,
            "n_banks": len(keep),
            "avg_raw": np.mean([v for v in raw if v is not None]),
            "avg_res": np.mean([v for v in res if v is not None]),
            "pagerank": pr,
            "n_active": sum(act),
        })
    return out


# main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--network", default="data/processed/network_data.json")
    ap.add_argument("--centrality", default="data/processed/centrality.json")
    ap.add_argument("--out-file", default="data/processed/sensitivity.json")
    ap.add_argument("--docs-dir", default="docs/sensitivity")
    args = ap.parse_args()

    with open(args.network, encoding="utf-8") as f:
        net = json.load(f)
    with open(args.centrality, encoding="utf-8") as f:
        cen = json.load(f)
    banks = [b["id"] for b in net["banks"]]
    pairs = [tuple(p) for p in net["pairs"]]

    # ================= A. window length =================
    ret, mkt = load_returns(args.raw_dir)
    assert list(ret.columns) == banks, "bank order differs from network_data.json"
    runs = {L: run_length(ret, mkt, L, pairs) for L in LENGTHS}

    # self-check: 250 days == network_data.json
    ref = net["windows"]
    r250 = runs[250]
    assert [w["end"] for w in r250] == [w["end"] for w in ref], "250-day window dates differ"
    max_diff = 0.0
    for a, b in zip(r250, ref):
        for mode in ("raw", "residual"):
            for u, v in zip(a[mode], b[mode]):
                if (u is None) != (v is None):
                    raise SystemExit("null pattern differs from network_data.json")
                if u is not None:
                    max_diff = max(max_diff, abs(u - v))
    print(f"self-check 250 days vs network_data.json: max abs diff {max_diff:.4f}")
    assert max_diff < 0.001

    series = {}
    for L, ws in runs.items():
        series[str(L)] = {
            "end": [w["end"] for w in ws],
            "raw": [r4(w["avg_raw"]) for w in ws],
            "residual": [r4(w["avg_res"]) for w in ws],
            "n_banks": [w["n_banks"] for w in ws],
        }

    by_date = {L: {w["end"]: w for w in ws} for L, ws in runs.items()}
    agreement = {}
    for L in (120, 500):
        common = sorted(set(by_date[L]) & set(by_date[250]))
        entry = {"n_common_windows": len(common), "first_common": common[0]}
        for key, name in (("avg_raw", "raw"), ("avg_res", "residual")):
            x = [by_date[L][d][key] for d in common]
            y = [by_date[250][d][key] for d in common]
            entry[f"avg_corr_pearson_{name}"] = r4(pearsonr(x, y)[0])
            entry[f"avg_corr_mean_diff_{name}"] = r4(np.mean(np.array(x) - np.array(y)))
        for mode in CENTRAL_MODES:
            rho, agree = [], []
            for d in common:
                a = by_date[L][d]["pagerank"][mode]
                b = by_date[250][d]["pagerank"][mode]
                s = spearman_active(a, b)
                if s is not None:
                    rho.append(s)
                na = by_date[250][d]["n_active"]
                ta = [tier(v, na) for v in a]
                tb = [tier(v, na) for v in b]
                pairs_t = [(u, v) for u, v in zip(ta, tb) if u is not None and v is not None]
                agree.append(np.mean([u == v for u, v in pairs_t]))
            entry[f"pagerank_spearman_median_{mode}"] = r4(np.median(rho))
            entry[f"pagerank_spearman_p25_{mode}"] = r4(np.percentile(rho, 25))
            entry[f"tier_agreement_mean_{mode}"] = r4(np.mean(agree))
        agreement[f"{L}_vs_250"] = entry

    peaks = {}
    for L, ws in runs.items():
        k_res = int(np.nanargmax([w["avg_res"] for w in ws]))
        k_raw = int(np.nanargmax([w["avg_raw"] for w in ws]))
        peaks[str(L)] = {"residual_peak_end": ws[k_res]["end"], "residual_peak": r4(ws[k_res]["avg_res"]),
                         "raw_peak_end": ws[k_raw]["end"], "raw_peak": r4(ws[k_raw]["avg_raw"])}

    last_pr = {str(L): {m: runs[L][-1]["pagerank"][m] for m in CENTRAL_MODES} for L in LENGTHS}
    last_tiers = {}
    for L in LENGTHS:
        na = runs[L][-1]["n_active"]
        last_tiers[str(L)] = {m: [tier(v, na) for v in runs[L][-1]["pagerank"][m]] for m in CENTRAL_MODES}

    # ================= B. threshold =================
    thr_keys = cen["meta"]["thresholds"]
    cw = cen["windows"]
    n_edges = {m: [] for m in ("raw", "residual", "residual_matched")}
    density = {m: [] for m in ("raw", "residual", "residual_matched")}
    floor_hit = []
    spear = {m: [] for m in CENTRAL_MODES}
    spear_p25 = {m: [] for m in CENTRAL_MODES}
    tier_agree = {m: [] for m in CENTRAL_MODES}
    for key in thr_keys:
        for m in n_edges:
            ne = [w["metrics"][key][m]["n_edges"] for w in cw]
            n_edges[m].append(ne)
            density[m].append([r4(e / (w["n_active"] * (w["n_active"] - 1) / 2)) for e, w in zip(ne, cw)])
        floor_hit.append([bool(w["metrics"][key]["residual_matched"]["floor_hit"]) for w in cw])
        for m in CENTRAL_MODES:
            rho, agree = [], []
            for w in cw:
                a = w["metrics"][key][m]["pagerank"]
                b = w["metrics"][DEFAULT_KEY][m]["pagerank"]
                s = spearman_active(a, b)
                if s is not None:
                    rho.append(s)
                ta = [tier(v, w["n_active"]) for v in a]
                tb = [tier(v, w["n_active"]) for v in b]
                pt = [(u, v) for u, v in zip(ta, tb) if u is not None]
                agree.append(np.mean([u == v for u, v in pt]))
            spear[m].append(r4(np.median(rho)) if rho else None)
            spear_p25[m].append(r4(np.percentile(rho, 25)) if rho else None)
            tier_agree[m].append(r4(np.mean(agree)))

    out = {
        "meta": {
            "description": "Sensitivity of the results to window length (Part A) and edge threshold "
                           "(Part B). Q4 of the project. Bank arrays follow 'banks'.",
            "generated_by": "src/sensitivity.py",
            "step_days": STEP,
            "pagerank_rule": "same as centrality.json: weighted by corr, damping 0.85, active banks "
                             "only; residual_matched uses floor 0.05",
            "tier_rule": "baseline = 1/N_active; core >= 1.5*baseline, periphery <= 0.5*baseline, "
                         "middle otherwise",
            "self_check_250_vs_network_data_max_abs_diff": round(max_diff, 4),
        },
        "banks": banks,
        "window_length": {
            "lengths": LENGTHS,
            "pagerank_threshold": DEFAULT_KEY,
            "series": series,
            "agreement_vs_250": agreement,
            "peaks": peaks,
            "last_window": {
                "end": runs[250][-1]["end"],
                "pagerank": last_pr,
                "tier": last_tiers,
            },
        },
        "threshold": {
            "thresholds": thr_keys,
            "default": DEFAULT_KEY,
            "window_days": 250,
            "end": [w["end"] for w in cw],
            "n_active": [w["n_active"] for w in cw],
            "n_edges": n_edges,
            "density": density,
            "floor_hit": floor_hit,
            "pagerank_spearman_vs_default_median": spear,
            "pagerank_spearman_vs_default_p25": spear_p25,
            "tier_agreement_vs_default_mean": tier_agree,
        },
    }
    os.makedirs(os.path.dirname(args.out_file) or ".", exist_ok=True)
    with open(args.out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # ---- summary ----
    for L in LENGTHS:
        s = series[str(L)]
        print(f"{L:>3} days: {len(s['end'])} windows {s['end'][0]} -> {s['end'][-1]}, "
              f"last avg raw {s['raw'][-1]}, residual {s['residual'][-1]}; peaks {peaks[str(L)]}")
    for k, v in agreement.items():
        print(k, v)
    print("threshold  mean raw edges  mean res_matched edges  floor%  spearman(raw,res_m)  tier_agree(raw,res_m)")
    for i, key in enumerate(thr_keys):
        print(f"  {key}   {np.mean(n_edges['raw'][i]):6.1f}   {np.mean(n_edges['residual_matched'][i]):6.1f}"
              f"   {100*np.mean(floor_hit[i]):5.1f}%   {spear['raw'][i]} {spear['residual_matched'][i]}"
              f"   {tier_agree['raw'][i]} {tier_agree['residual_matched'][i]}")
    print(f"{args.out_file}: {os.path.getsize(args.out_file) / 1024:.0f} KB")
    write_docs(out, args.docs_dir)


# C. docs/sensitivity
def write_docs(out, d):
    os.makedirs(d, exist_ok=True)
    banks, th, wl = out["banks"], out["threshold"], out["window_length"]

    # ---- table 1: by threshold ----
    rows = []
    for i, t in enumerate(th["thresholds"]):
        rows.append({
            "threshold": t,
            "mean_edges_raw": round(float(np.mean(th["n_edges"]["raw"][i])), 1),
            "mean_edges_residual": round(float(np.mean(th["n_edges"]["residual"][i])), 1),
            "mean_edges_residual_matched": round(float(np.mean(th["n_edges"]["residual_matched"][i])), 1),
            "mean_density_raw": round(float(np.mean(th["density"]["raw"][i])), 3),
            "floor_hit_pct": round(100 * float(np.mean(th["floor_hit"][i])), 1),
            "pagerank_spearman_vs_050_raw": th["pagerank_spearman_vs_default_median"]["raw"][i],
            "pagerank_spearman_vs_050_residual": th["pagerank_spearman_vs_default_median"]["residual_matched"][i],
            "same_tier_pct_raw": round(100 * th["tier_agreement_vs_default_mean"]["raw"][i], 1),
            "same_tier_pct_residual": round(100 * th["tier_agreement_vs_default_mean"]["residual_matched"][i], 1),
        })
    pd.DataFrame(rows).to_csv(os.path.join(d, "threshold_sensitivity.csv"), index=False)

    # ---- table 2: by window length ----
    rows = []
    for L in map(str, wl["lengths"]):
        s, pk = wl["series"][L], wl["peaks"][L]
        a = wl["agreement_vs_250"].get(f"{L}_vs_250", {})
        rows.append({
            "window_days": int(L), "n_windows": len(s["end"]), "first_end": s["end"][0],
            "last_avg_raw": s["raw"][-1], "last_avg_residual": s["residual"][-1],
            "residual_peak": pk["residual_peak"], "residual_peak_end": pk["residual_peak_end"],
            "raw_peak": pk["raw_peak"], "raw_peak_end": pk["raw_peak_end"],
            "avg_corr_pearson_vs_250_raw": a.get("avg_corr_pearson_raw"),
            "avg_corr_pearson_vs_250_residual": a.get("avg_corr_pearson_residual"),
            "pagerank_spearman_vs_250_raw": a.get("pagerank_spearman_median_raw"),
            "pagerank_spearman_vs_250_residual": a.get("pagerank_spearman_median_residual_matched"),
            "same_tier_pct_vs_250_raw": None if not a else round(100 * a["tier_agreement_mean_raw"], 1),
            "same_tier_pct_vs_250_residual": None if not a else round(100 * a["tier_agreement_mean_residual_matched"], 1),
        })
    pd.DataFrame(rows).to_csv(os.path.join(d, "window_length_sensitivity.csv"), index=False)

    # ---- table 3: tiers in the last window, by window length ----
    lw = wl["last_window"]
    t3 = {"bank": banks}
    for L in map(str, wl["lengths"]):
        for m in CENTRAL_MODES:
            t3[f"pagerank_{L}d_{m}"] = lw["pagerank"][L][m]
            t3[f"tier_{L}d_{m}"] = lw["tier"][L][m]
    pd.DataFrame(t3).to_csv(os.path.join(d, "last_window_tiers.csv"), index=False)

    # ---- figures ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed: tables written, figures skipped")
        figs = False
    else:
        figs = True
        c_raw, c_res = "#1f3a68", "#c2410c"
        plt.rcParams.update({"figure.dpi": 150, "font.size": 9, "axes.spines.top": False,
                             "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25})
        thr = [float(t) for t in th["thresholds"]]

        fig, ax = plt.subplots(figsize=(6, 3.8))
        for m, c, lab in (("raw", c_raw, "raw"), ("residual", c_res, "residual (same threshold)")):
            e = np.array(th["n_edges"][m], dtype=float)
            ax.plot(thr, e.mean(1), color=c, lw=1.8, marker="o", ms=3, label=lab)
            ax.fill_between(thr, np.percentile(e, 10, 1), np.percentile(e, 90, 1), color=c, alpha=0.12)
        ax.axvline(0.5, color="black", lw=0.6, ls=":")
        ax.set_xlabel("Threshold")
        ax.set_ylabel("Edges (of up to 171)")
        ax.set_title("Edges vs threshold, 250-day windows\n(line = mean, band = 10–90% of windows)")
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(d, "edges_vs_threshold.png"), bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(6, 3.8))
        for m, c, lab in (("raw", c_raw, "raw"), ("residual_matched", c_res, "residual (matched)")):
            ax.plot(thr, th["pagerank_spearman_vs_default_median"][m], color=c, marker="o", ms=3, lw=1.6,
                    label=f"PageRank Spearman, {lab}")
            ax.plot(thr, th["tier_agreement_vs_default_mean"][m], color=c, marker="s", ms=3, lw=1, ls="--",
                    label=f"share in same tier, {lab}")
        ax.axvline(0.5, color="black", lw=0.6, ls=":")
        ax.set_ylim(0.4, 1.02)
        ax.set_xlabel("Threshold")
        ax.set_title("Agreement of the ranking with threshold 0.50\n(median / mean over 88 windows)")
        ax.legend(frameon=False, fontsize=7.5)
        fig.tight_layout()
        fig.savefig(os.path.join(d, "ranking_vs_threshold.png"), bbox_inches="tight")
        plt.close(fig)

        fig, axes = plt.subplots(2, 1, figsize=(8, 5.5), sharex=True)
        styles = {"120": (":", 1.3), "250": ("-", 1.9), "500": ("--", 1.3)}
        for ax, key, c, title in ((axes[0], "raw", c_raw, "Raw"), (axes[1], "residual", c_res, "Residual (VN-Index removed)")):
            for L in map(str, wl["lengths"]):
                s = wl["series"][L]
                ls, lw_ = styles[L]
                ax.plot(pd.to_datetime(s["end"]), s[key], color=c, ls=ls, lw=lw_, label=f"{L} days")
            ax.set_title(title, fontsize=9, loc="left")
            ax.set_ylabel("Avg pair corr")
            ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
        axes[0].set_ylim(0.15, 0.7)
        axes[1].set_ylim(0, 0.45)
        fig.suptitle("Average correlation by window length (x = window end date)", fontsize=10)
        fig.tight_layout()
        fig.savefig(os.path.join(d, "avg_corr_by_window_length.png"), bbox_inches="tight")
        plt.close(fig)

    # ---- README ----
    t = pd.read_csv(os.path.join(d, "threshold_sensitivity.csv"))
    w = pd.read_csv(os.path.join(d, "window_length_sensitivity.csv"))
    lines = [
        "# Q4 – Sensitivity tables and figures",
        "",
        "Generated by `src/sensitivity.py` (do not edit by hand). Data: `data/processed/sensitivity.json`.",
        "Descriptive only. Tier: baseline 1/N_active; core >= 1.5x, periphery <= 0.5x.",
        "",
        "| File | Content |",
        "|---|---|",
        "| `threshold_sensitivity.csv` | per threshold 0.30–0.70: mean edges, density, floor hits, PageRank Spearman and same-tier share vs 0.50 |",
        "| `window_length_sensitivity.csv` | per window length 120 / 250 / 500: windows, last values, peaks, agreement with 250 days |",
        "| `last_window_tiers.csv` | PageRank and tier of every bank in the last window, per window length and mode |",
    ]
    if figs:
        lines += [
            "| `edges_vs_threshold.png` | edges vs threshold, raw and residual |",
            "| `ranking_vs_threshold.png` | ranking agreement with threshold 0.50 |",
            "| `avg_corr_by_window_length.png` | average correlation over time for 120 / 250 / 500 days |",
        ]
    lines += ["", "## Threshold (250-day windows)", "", md_table(t),
              "", "## Window length", "", md_table(w), ""]
    with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{d}/: {len(os.listdir(d))} files")


def md_table(df):
    """Markdown table without extra packages (pandas.to_markdown needs tabulate)."""
    cells = [[("" if pd.isna(v) else str(v)) for v in row] for row in df.itertuples(index=False)]
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(r) + " |" for r in cells])


if __name__ == "__main__":
    main()
