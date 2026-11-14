"""
Xuất các chỉ số trung tâm (centrality) cho web.

Đầu vào: data/processed/network_data.json   (do build_dataset.py tạo)
Đầu ra : data/processed/centrality.json

Với mỗi cửa sổ x ngưỡng x chế độ, file lưu cho từng ngân hàng:
    pagerank  có trọng số theo correlation, damping 0.85, chỉ tính trên các
              ngân hàng active trong cửa sổ (cùng quy tắc với js/data.js, D2)
    degree    số cạnh của ngân hàng
    strength  tổng correlation trên các cạnh đó
kèm ngưỡng thực sự được dùng và số cạnh của mạng.

Các chế độ (mode)
    raw               có cạnh nếu corr raw >= ngưỡng
    residual          có cạnh nếu corr residual >= ngưỡng
    residual_matched  ngưỡng residual được chọn sao cho số cạnh bằng mạng raw
                      ở cùng cửa sổ (mặc định của web), không bao giờ thấp hơn
                      sàn 0.05 (cùng quy tắc với js/data.js, D1)

Correlation được đọc từ network_data.json (3 chữ số thập phân), tức là đúng
các số mà trình duyệt dùng, nên các cạnh nằm sát ngưỡng giống hệt nhau.

Lưới ngưỡng: 0.30 đến 0.70, bước 0.05 (phạm vi đã chốt của nhóm).

Chạy từ thư mục gốc của repo:
    python src/export_centrality.py
"""
import argparse
import json
import os

import networkx as nx

DAMPING = 0.85
NO_EDGE_THRESHOLD = 1.01  # cùng quy ước với web: không cạnh nào vượt qua được
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]  # phạm vi đã chốt
DEFAULT_THRESHOLD = 0.50  # ngưỡng mặc định của web
FLOOR = 0.05              # D1 trong js/data.js: ngưỡng residual tự khớp không thấp hơn mức này


def active_banks(window, pairs, n):
    """Ngân hàng là active trong cửa sổ nếu có ít nhất một correlation khác null."""
    act = [False] * n
    for k, c in enumerate(window["raw"]):
        if c is not None:
            act[pairs[k][0]] = act[pairs[k][1]] = True
    return act


def matched_threshold(window, thr):
    """Ngưỡng residual cho số cạnh bằng mạng raw tại ngưỡng `thr`.

    matched = correlation residual lớn thứ n, với n = số cạnh raw (các giá trị
    trùng nhau có thể thêm vài cạnh). Khi mạng raw dày, giá trị này có thể gần
    0 hoặc âm, và những cạnh như vậy làm PageRank vô nghĩa, nên ngưỡng được
    dùng là max(matched, FLOOR). Khi đó mạng residual ít cạnh hơn raw và
    floor_hit là True.

    Trả về (ngưỡng được dùng, giá trị matched trước khi áp sàn, floor_hit).
    """
    n = sum(1 for c in window["raw"] if c is not None and c >= thr)
    s = sorted((c for c in window["residual"] if c is not None), reverse=True)
    matched = s[min(n, len(s)) - 1] if (n > 0 and s) else NO_EDGE_THRESHOLD
    return max(matched, FLOOR), matched, matched < FLOOR


def build_edges(values, pairs, thr):
    """Danh sách cạnh (i, j, corr) với corr khác null và >= ngưỡng."""
    return [(pairs[k][0], pairs[k][1], c)
            for k, c in enumerate(values) if c is not None and c >= thr]


def metrics(edges, n, active):
    """Tính pagerank, degree, strength; mảng trả về theo thứ tự ngân hàng."""
    ids = [i for i in range(n) if active[i]]
    g = nx.Graph()
    g.add_nodes_from(ids)                    # chỉ ngân hàng active, kể cả node cô lập
    g.add_weighted_edges_from(edges)
    pr = nx.pagerank(g, alpha=DAMPING, weight="weight", tol=1e-10, max_iter=1000) if ids else {}
    deg = dict(g.degree())
    stg = dict(g.degree(weight="weight"))
    # ngân hàng không có dữ liệu trong cửa sổ -> null (không bao giờ là 0)
    return {
        "pagerank": [round(pr[i], 5) if active[i] else None for i in range(n)],
        "degree": [int(deg[i]) if active[i] else None for i in range(n)],
        "strength": [round(float(stg[i]), 3) if active[i] else None for i in range(n)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-file", default="data/processed/network_data.json")
    ap.add_argument("--out-file", default="data/processed/centrality.json")
    args = ap.parse_args()

    # ---- 1. Đọc dữ liệu ----
    with open(args.in_file, encoding="utf-8") as f:
        data = json.load(f)
    banks = [b["id"] for b in data["banks"]]
    pairs, windows, n = data["pairs"], data["windows"], len(banks)
    thresholds = THRESHOLDS

    # ---- 2. Tính chỉ số cho từng cửa sổ x ngưỡng x chế độ ----
    out_windows, n_floored = [], 0
    for w in windows:
        act = active_banks(w, pairs, n)
        by_thr = {}
        for thr in thresholds:
            entry = {}
            t_match, matched, floor_hit = matched_threshold(w, thr)
            n_floored += floor_hit
            for mode, values, t in (
                ("raw", w["raw"], thr),
                ("residual", w["residual"], thr),
                ("residual_matched", w["residual"], t_match),
            ):
                edges = build_edges(values, pairs, t)
                entry[mode] = {"threshold": t, "n_edges": len(edges), **metrics(edges, n, act)}
            entry["residual_matched"]["matched_threshold"] = matched
            entry["residual_matched"]["floor_hit"] = floor_hit
            by_thr[f"{thr:.2f}"] = entry
        out_windows.append({"end": w["end"], "n_active": sum(act),
                            "active": [int(a) for a in act], "metrics": by_thr})

    # ---- 3. Ghi JSON cho web ----
    out = {
        "meta": {
            "description": "Centrality of each bank per window, threshold and mode. "
                           "Arrays follow the order of 'banks'.",
            "source_file": os.path.basename(args.in_file),
            "window_days": data["meta"]["window_days"],
            "step_days": data["meta"]["step_days"],
            "n_windows": len(out_windows),
            "thresholds": [f"{t:.2f}" for t in thresholds],
            "default_threshold": f"{DEFAULT_THRESHOLD:.2f}",
            "modes": {
                "raw": "edge if raw corr >= threshold",
                "residual": "edge if residual corr >= threshold",
                "residual_matched": "residual threshold = n-th largest residual corr, "
                                    "n = raw edge count at the same threshold (web default); "
                                    "threshold = max(matched_threshold, floor); "
                                    "floor_hit = true means the floor was applied "
                                    "(fewer edges than raw); 1.01 means no edges",
            },
            "floor": FLOOR,
            "pagerank": f"weighted by corr, damping {DAMPING}, computed over the active banks "
                        "of the window only; isolated active banks spread their rank evenly "
                        "among the active banks",
            "null_note": "null = bank has no data in that window (active = 0)",
        },
        "banks": banks,
        "windows": out_windows,
    }
    os.makedirs(os.path.dirname(args.out_file) or ".", exist_ok=True)
    with open(args.out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # ---- 4. In tóm tắt để kiểm tra nhanh ----
    last = out_windows[-1]["metrics"][f"{DEFAULT_THRESHOLD:.2f}"]
    print(f"{len(out_windows)} windows x {len(thresholds)} thresholds x 3 modes")
    for mode in ("raw", "residual_matched"):
        m = last[mode]
        top = sorted(range(n), key=lambda i: -(m["pagerank"][i] or 0))[:5]
        print(f"last window, {mode}: threshold {m['threshold']}, {m['n_edges']} edges, "
              f"top 5 = {[banks[i] for i in top]}")
    print(f"residual_matched: floor {FLOOR} applied in {n_floored} "
          f"of {len(out_windows) * len(thresholds)} window x threshold cases")
    print(f"{args.out_file}: {os.path.getsize(args.out_file) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
