"""
Export the bank order by cluster for the matrix (Q3).

Input : data/processed/network_data.json
Output: data/processed/cluster_order.json   (schema: docs/schema.md, section 4)

Method
    1. Take the windows in which all 19 banks have data (61 windows,
       2021-12-02 -> 2026-09-30), so every pair is measured over the same period.
    2. Average the RESIDUAL correlation of each pair over those windows.
       Residual, not raw: raw correlations are dominated by VN-Index (almost
       every pair is high), so raw clusters mostly reflect "beta to the market".
    3. Distance d = sqrt(2 * (1 - corr))  (Mantegna, 1999).
    4. Hierarchical clustering, average linkage, optimal leaf ordering, so that
       similar banks sit next to each other on the matrix.
    5. Number of clusters k = the one with the largest silhouette score, k = 2..6.
    6. Stability: re-cluster every single window (same k) and measure the
       Adjusted Rand Index (ARI) against the overall result. Stored in meta.

Run from the repo root:
    python src/export_clusters.py
"""
import argparse
import json
import os

import numpy as np
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage, optimal_leaf_ordering
from scipy.spatial.distance import squareform

K_RANGE = range(2, 7)
MODE = "residual"


def silhouette_score(dist, labels):
    """Mean silhouette for a precomputed distance matrix (single-member cluster: s = 0)."""
    labels = np.asarray(labels)
    s = np.zeros(len(labels))
    for i in range(len(labels)):
        same = labels == labels[i]
        if same.sum() == 1:
            continue
        a = dist[i, same & (np.arange(len(labels)) != i)].mean()
        b = min(dist[i, labels == c].mean() for c in set(labels) if c != labels[i])
        s[i] = (b - a) / max(a, b)
    return float(s.mean())


def adjusted_rand_score(x, y):
    """Adjusted Rand Index (Hubert & Arabie, 1985)."""
    x, y = np.asarray(x), np.asarray(y)
    cx, cy = np.unique(x), np.unique(y)
    table = np.array([[np.sum((x == a) & (y == b)) for b in cy] for a in cx])
    comb = lambda v: v * (v - 1) / 2.0
    sum_ij = comb(table).sum()
    sum_a, sum_b = comb(table.sum(1)).sum(), comb(table.sum(0)).sum()
    expected = sum_a * sum_b / comb(len(x))
    max_idx = (sum_a + sum_b) / 2.0
    return 1.0 if max_idx == expected else float((sum_ij - expected) / (max_idx - expected))


def corr_matrix(window, pairs, n, mode):
    m = np.full((n, n), np.nan)
    np.fill_diagonal(m, 1.0)
    for p, (i, j) in enumerate(pairs):
        v = window[mode][p]
        if v is not None:
            m[i, j] = m[j, i] = v
    return m


def to_distance(c):
    d = np.sqrt(np.clip(2.0 * (1.0 - c), 0.0, None))
    np.fill_diagonal(d, 0.0)
    return d


def cluster(dist, k):
    z = linkage(squareform(dist, checks=False), method="average")
    z = optimal_leaf_ordering(z, squareform(dist, checks=False))
    labels = fcluster(z, k, criterion="maxclust")
    return z, labels


def relabel_by_order(labels, order):
    """Number the clusters 0, 1, 2... in the order they appear along the matrix axis."""
    mapping, nxt = {}, 0
    for i in order:
        if labels[i] not in mapping:
            mapping[labels[i]] = nxt
            nxt += 1
    return np.array([mapping[l] for l in labels])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-file", default="data/processed/network_data.json")
    ap.add_argument("--out-file", default="data/processed/cluster_order.json")
    args = ap.parse_args()

    with open(args.in_file, encoding="utf-8") as f:
        data = json.load(f)
    banks = [b["id"] for b in data["banks"]]
    groups = {b["id"]: b["group"] for b in data["banks"]}
    pairs, windows, n = data["pairs"], data["windows"], len(banks)

    full = [k for k, w in enumerate(windows) if all(v is not None for v in w[MODE])]
    mats = np.stack([corr_matrix(windows[k], pairs, n, MODE) for k in full])
    avg = mats.mean(axis=0)
    dist = to_distance(avg)

    # ---- choose k by silhouette ----
    sil = {}
    for k in K_RANGE:
        _, lab = cluster(dist, k)
        if len(set(lab)) < 2:
            continue
        sil[k] = silhouette_score(dist, lab)
    k_best = max(sil, key=sil.get)

    z, labels = cluster(dist, k_best)
    order = list(leaves_list(z))
    # Flip the axis (same tree) so the matrix starts at VCB, like the original bank order.
    if order.index(0) > len(order) // 2:
        order = order[::-1]
    labels = relabel_by_order(labels, order)

    # stability window by window 
    ari = []
    for t in range(len(full)):
        _, lab_t = cluster(to_distance(mats[t]), k_best)
        ari.append(adjusted_rand_score(labels, lab_t))
    ari = np.array(ari)

    # mean correlation within / between clusters 
    def mean_block(a_idx, b_idx, same):
        vals = [avg[i, j] for i in a_idx for j in b_idx if (i < j if same else True)]
        return round(float(np.mean(vals)), 4) if vals else None

    clusters = []
    for c in range(k_best):
        idx = [i for i in range(n) if labels[i] == c]
        clusters.append({
            "id": c,
            "banks": [banks[i] for i in order if labels[i] == c],
            "size": len(idx),
            "within_avg_corr": mean_block(idx, idx, True) if len(idx) > 1 else None,
            "groups": sorted({groups[banks[i]] for i in idx}),
        })
    within = [avg[i, j] for i in range(n) for j in range(i + 1, n) if labels[i] == labels[j]]
    between = [avg[i, j] for i in range(n) for j in range(i + 1, n) if labels[i] != labels[j]]

    out = {
        "meta": {
            "method": "Average-linkage hierarchical clustering with optimal leaf ordering on "
                      "d = sqrt(2*(1-corr)), corr = mean residual correlation over the windows "
                      "where all 19 banks have data; k chosen by the largest silhouette score "
                      "for k = 2..6.",
            "mode": MODE,
            "windows_used": len(full),
            "period": [windows[full[0]]["end"], windows[full[-1]]["end"]],
            "k": k_best,
            "silhouette": {str(k): round(v, 4) for k, v in sil.items()},
            "stability_ari": {
                "description": "Adjusted Rand Index between this clustering and the clustering "
                               "of each single window (same k). 1 = identical, 0 = chance.",
                "median": round(float(np.median(ari)), 3),
                "p25": round(float(np.percentile(ari, 25)), 3),
                "p75": round(float(np.percentile(ari, 75)), 3),
            },
            "within_cluster_avg_corr": round(float(np.mean(within)), 4),
            "between_cluster_avg_corr": round(float(np.mean(between)), 4),
            "clusters": clusters,
            "note": "Clusters describe co-movement of stock returns, not ownership, size or "
                    "lending links. Weak clusters: read together with the stability score.",
            "generated_by": "src/export_clusters.py",
        },
        "order": [banks[i] for i in order],
        "cluster": {banks[i]: int(labels[i]) for i in range(n)},
    }
    os.makedirs(os.path.dirname(args.out_file) or ".", exist_ok=True)
    with open(args.out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"{len(full)} full windows ({out['meta']['period'][0]} -> {out['meta']['period'][1]}), mode {MODE}")
    print("silhouette:", out["meta"]["silhouette"], "-> k =", k_best)
    for c in clusters:
        print(f"  cluster {c['id']}: {c['banks']}  within corr {c['within_avg_corr']}")
    print(f"within {out['meta']['within_cluster_avg_corr']}, between {out['meta']['between_cluster_avg_corr']}")
    print("stability ARI:", out["meta"]["stability_ari"])
    print("order:", out["order"])


if __name__ == "__main__":
    main()
