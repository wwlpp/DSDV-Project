"""
Tạo dataset cho dự án mạng đồng biến ngân hàng VN.

Đầu vào (data/raw/):
    prices.csv    giá đóng cửa các ngân hàng (do bank_network_test.py tạo)
    vnindex.csv   giá đóng cửa VN-Index (do bank_network_residual.py tạo)

Đầu ra (data/processed/):
    returns.csv            lợi suất log hằng ngày của các ngân hàng
    correlations_long.csv  bảng "dài": window_end, mode, bank_a, bank_b, corr
    summary.csv            mức kết nối trung bình theo thời gian (2 chế độ)
    network_data.json      file chính cho web (D3.js đọc trực tiếp)

Chạy:
    python build_dataset.py
    python build_dataset.py --raw-dir data/raw --out-dir data/processed --window 250 --step 20
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

# Nhóm sở hữu: ĐIỀN/KIỂM TRA LẠI cho đúng trước khi dùng trong báo cáo.
GROUPS = {"VCB": "state", "BID": "state", "CTG": "state"}
DEFAULT_GROUP = "private"


def residual_returns(win: pd.DataFrame, mkt: pd.Series) -> pd.DataFrame:
    """Với mỗi ngân hàng: y = a + b*mkt + phần dư. Trả về phần dư."""
    out = {}
    m_all = mkt.loc[win.index]
    for c in win.columns:
        y = win[c]
        ok = y.notna() & m_all.notna()
        if ok.sum() < 30:
            continue
        x, yy = m_all[ok], y[ok]
        beta = np.cov(yy, x)[0, 1] / np.var(x, ddof=1)
        out[c] = (yy - beta * x).reindex(win.index)
    return pd.DataFrame(out)


def upper_values(corr: pd.DataFrame, banks, pairs):
    vals = []
    for i, j in pairs:
        a, b = banks[i], banks[j]
        v = corr.loc[a, b] if (a in corr.index and b in corr.columns) else np.nan
        vals.append(None if pd.isna(v) else round(float(v), 3))
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--out-dir", default="data/processed")
    ap.add_argument("--window", type=int, default=250)
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--min-obs", type=float, default=0.8,
                    help="tỉ lệ dữ liệu tối thiểu của một mã trong cửa sổ")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # ---- 1. Đọc dữ liệu gốc ----
    prices = pd.read_csv(os.path.join(args.raw_dir, "prices.csv"), index_col=0, parse_dates=True)
    prices.index = prices.index.normalize()
    prices = prices[~prices.index.duplicated()].sort_index()

    vn = pd.read_csv(os.path.join(args.raw_dir, "vnindex.csv"), index_col=0, parse_dates=True).iloc[:, 0]
    vn.index = vn.index.normalize()
    vn = vn[~vn.index.duplicated()].sort_index()

    # ---- 2. Lợi suất log, căn chỉnh ngày ----
    ret = np.log(prices).diff().dropna(how="all")
    ret = ret.dropna(axis=1, thresh=int(len(ret) * 0.7))  # bỏ mã thiếu quá nhiều (vd SSB)
    mkt = np.log(vn).diff().dropna()
    idx = ret.index.intersection(mkt.index)
    ret, mkt = ret.loc[idx], mkt.loc[idx]
    banks = list(ret.columns)
    n = len(banks)
    print(f"{n} ngân hàng: {banks}")
    print(f"{len(ret)} ngày chung, từ {ret.index[0].date()} đến {ret.index[-1].date()}")

    ret.to_csv(os.path.join(args.out_dir, "returns.csv"), float_format="%.6f")

    # ---- 3. Các cửa sổ trượt (cửa sổ cuối luôn kết thúc ở ngày mới nhất) ----
    ends = list(range(len(ret), args.window - 1, -args.step))[::-1]
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]

    windows, long_rows, summary_rows = [], [], []
    for e in ends:
        w = ret.iloc[e - args.window:e]
        keep = [c for c in banks if w[c].notna().mean() >= args.min_obs]
        wk = w[keep]
        corr_raw = wk.corr()
        corr_res = residual_returns(wk, mkt).corr()
        date = ret.index[e - 1].strftime("%Y-%m-%d")

        raw_vals = upper_values(corr_raw, banks, pairs)
        res_vals = upper_values(corr_res, banks, pairs)
        windows.append({"end": date, "raw": raw_vals, "residual": res_vals})

        for mode, vals in (("raw", raw_vals), ("residual", res_vals)):
            ok = [v for v in vals if v is not None]
            summary_rows.append({"window_end": date, "mode": mode,
                                 "avg_corr": round(float(np.mean(ok)), 4) if ok else None,
                                 "n_banks": len(keep)})
            for (i, j), v in zip(pairs, vals):
                if v is not None:
                    long_rows.append((date, mode, banks[i], banks[j], v))

    pd.DataFrame(long_rows, columns=["window_end", "mode", "bank_a", "bank_b", "corr"]) \
        .to_csv(os.path.join(args.out_dir, "correlations_long.csv"), index=False)
    pd.DataFrame(summary_rows).to_csv(os.path.join(args.out_dir, "summary.csv"), index=False)

    # ---- 4. JSON cho web ----
    data = {
        "meta": {
            "description": "Rolling correlation of daily log returns among listed Vietnamese banks (proxy co-movement network).",
            "source": "vnstock (VCI), community edition",
            "window_days": args.window,
            "step_days": args.step,
            "residual_note": "residual = bank return minus beta * VN-Index return, beta estimated within each window",
            "n_windows": len(windows),
            "first_window_end": windows[0]["end"],
            "last_window_end": windows[-1]["end"],
        },
        "banks": [{"id": b, "group": GROUPS.get(b, DEFAULT_GROUP)} for b in banks],
        "pairs": [[i, j] for i, j in pairs],   # chỉ số vào mảng banks
        "windows": windows,                     # raw/residual: giá trị theo đúng thứ tự pairs; null = thiếu dữ liệu
    }
    path = os.path.join(args.out_dir, "network_data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nĐã tạo {len(windows)} cửa sổ x {len(pairs)} cặp x 2 chế độ")
    print(f"network_data.json: {os.path.getsize(path) / 1024:.0f} KB")
    print(f"Các file trong {args.out_dir}: {sorted(os.listdir(args.out_dir))}")


if __name__ == "__main__":
    main()
