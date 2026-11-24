"""Node regression harness for js/data.js (run: python src/test_data.py).

Covers the plan v3 numeric cases (V-01..V-16 subset), the D7 tier boundaries,
the browser-vs-centrality agreement on the 9-threshold grid (D5 / V-SC), and
the unified metrics() shape. Exits non-zero on any failure.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JS = r"""
global.window = globalThis;
global.location = { protocol: 'file:' };
require(%(bundle)s);
require(%(state)s);
require(%(data)s);
const d = DSDV.data;
d.load().then(() => {
  const close = (a, b, t = 1e-4) => Math.abs(a - b) < t;
  let pass = 0, fail = 0;
  const T = (n, ok) => { ok ? pass++ : fail++; console.log((ok ? 'PASS ' : 'FAIL ') + n); };

  // Numeric cases (plan v3 §9.1)
  const s87 = d.summaryAt(87), s0 = d.summaryAt(0);
  T('V-01', close(s87.raw, 0.4365) && close(s87.residual, 0.2026) && s87.n_banks === 19);
  const a0 = d.activeBanks(0);
  T('V-02', close(s0.raw, 0.3683) && close(s0.residual, 0.1257) && s0.n_banks === 15 &&
    !['MSB', 'OCB', 'NAB', 'ABB'].some(b => a0.includes(b)));
  const e87 = d.edges(87, { mode: 'raw', threshold: 0.5, matchRawEdges: true });
  const pr = d.pagerank(e87.edges, d.activeBanks(87));
  T('V-07', e87.edges.length === 64 && close(pr.VIB, 0.0903, 5e-5) &&
    close(pr.CTG, 0.0902, 5e-5) && close(pr.OCB, 0.0875, 5e-5));
  const r87 = d.edges(87, { mode: 'residual', threshold: 0.5, matchRawEdges: true });
  T('V-08', close(r87.threshold, 0.225, 1e-9) && r87.edges.length === 64);
  const wi = d.windows().findIndex(w => w.end === '2025-09-12');
  const rf = d.edges(wi, { mode: 'residual', threshold: 0.20, matchRawEdges: true });
  T('V-15', rf.floorHit && rf.threshold === 0.05 && rf.edges.every(e => e.c >= 0.05));
  const e90 = d.edges(87, { mode: 'raw', threshold: 0.90, matchRawEdges: true });
  T('V-16', e90.edges.length === 0 && close(d.pagerank(e90.edges, d.activeBanks(87)).VCB, 1 / 19, 1e-9));
  T('V-09', close(d.pairValue(0, 'raw', 'VCB', 'BID'), 0.467, 1e-9) &&
    close(d.pairValue(0, 'raw', 'VCB', 'CTG'), 0.520, 1e-9));
  const w22 = d.windows().findIndex(w => w.end === '2022-07-27');
  T('V-10', close(d.pairValue(w22, 'residual', 'TCB', 'MBB'), 0.642, 1e-9));
  const actAt = e => {
    const w = d.windows().find(x => x.end === e); const s = new Set();
    w.raw.forEach((c, k) => { if (c != null) { s.add(d.bankIds()[d.pairs()[k][0]]); s.add(d.bankIds()[d.pairs()[k][1]]); } });
    return s;
  };
  T('NAB entry 2021-08-10', actAt('2021-08-10').has('NAB') && !actAt('2021-07-13').has('NAB'));

  // P3A timeline cases (plan v3 §9.1, errata v3.1 dates)
  const ends = d.windows().map(w => w.end);
  const iOf = e => ends.indexOf(e);
  const sum = d.summary();
  const rMax = sum.reduce((a, r) => r.residual > a.residual ? r : a);
  const rMin = sum.reduce((a, r) => r.residual < a.residual ? r : a);
  T('V-03', close(rMax.residual, 0.3049) && rMax.end === '2022-07-27' &&
    close(rMin.residual, 0.0745) && rMin.end === '2024-01-02');
  const j0 = d.summaryAt(iOf('2025-03-20')), j1 = d.summaryAt(iOf('2025-04-18'));
  T('V-04', close(j0.raw, 0.3806) && close(j0.residual, 0.0902) &&
    close(j1.raw, 0.5197) && close(j1.residual, 0.1073));
  const nullsAt = e => d.bankIds().filter(id => !d.activeBanks(iOf(e)).includes(id));
  T('V-05', nullsAt('2021-08-10').join(',') === 'MSB,OCB,ABB' &&
    nullsAt('2021-11-04').join(',') === 'OCB' && nullsAt('2021-12-02').length === 0 &&
    d.summaryAt(iOf('2021-08-10')).n_banks === 16 && d.summaryAt(iOf('2021-11-04')).n_banks === 18);
  const bal = d.balancedSeries('residual');
  T('V-06', close(bal[iOf('2021-12-02')], 0.2062) && close(bal[iOf('2022-07-27')], 0.2931));
  T('balanced panel 15, no nulls', d.balancedPanel().length === 15 && bal.every(v => v != null));
  const vibK = d.bankIds().indexOf('VIB');
  const v87 = d.window(87).raw.filter((c, k) => c != null &&
    (d.pairs()[k][0] === vibK || d.pairs()[k][1] === vibK));
  T('bankAvgSeries', d.bankAvgSeries('MSB', 'raw')[0] === null &&
    close(d.bankAvgSeries('VIB', 'raw')[87], v87.reduce((a, b) => a + b, 0) / v87.length));
  const mx = a => a.reduce((p, v) => v > p ? v : p, -Infinity);
  T('timeline y-domain guard', mx(sum.map(r => r.raw)) < 0.7 &&
    mx(sum.map(r => r.residual)) < 0.7 && mx(bal) < 0.7);
  // V-SC part 2: browser pair-mean vs summary.csv, all 88 windows x 2 modes
  let maxAvg = 0;
  for (let i = 0; i < d.windowCount(); i++) {
    for (const mode of ['raw', 'residual']) {
      const v = d.window(i)[mode].filter(c => c != null);
      const mean = v.reduce((a, b) => a + b, 0) / v.length;
      maxAvg = Math.max(maxAvg, Math.abs(mean - d.summaryAt(i)[mode]));
    }
  }
  T('V-SC avg vs summary (' + maxAvg.toExponential(2) + ')', maxAvg < 1e-4);

  // D7 tier boundaries (shared rule used by Ranking and Q1)
  const base = 1 / 19;
  T('tier Core', d.tier(1.5 * base, 5, 19) === 'Core');
  T('tier Periphery', d.tier(0.5 * base, 5, 19) === 'Periphery');
  T('tier Middle at baseline', d.tier(base, 5, 19) === 'Middle');
  T('tier isolated overrides', d.tier(base, 0, 19) === 'isolated');
  T('tier last-window VIB Core', d.tier(pr.VIB, 12, 19) === 'Core');
  T('tier last-window BAB isolated', d.tier(pr.BAB, 0, 19) === 'isolated');

  // metrics() unified shape + source gating (D5)
  const on = d.metrics(87, { mode: 'raw', threshold: 0.5, matchRawEdges: true });
  const off = d.metrics(87, { mode: 'raw', threshold: 0.51, matchRawEdges: true });
  T('metrics on-grid source', on.source === 'centrality.json' && typeof on.pagerank.VIB === 'number');
  T('metrics off-grid source', off.source === 'browser' && typeof off.pagerank.VIB === 'number');

  // Browser vs centrality on the grid (D5 / V-SC): 88 windows x 9 thresholds x 3 variants
  const grid = d.centrality().meta.thresholds.map(Number);
  const variants = [
    { mode: 'raw', matchRawEdges: false },
    { mode: 'residual', matchRawEdges: true },
    { mode: 'residual', matchRawEdges: false }
  ];
  let maxPR = 0, maxST = 0, bad = 0, cells = 0;
  for (let i = 0; i < d.windowCount(); i++) {
    for (const t of grid) {
      for (const v of variants) {
        const opts = { mode: v.mode, threshold: t, matchRawEdges: v.matchRawEdges };
        const entry = d.centralityFor({ ...opts, windowIndex: i });
        if (!entry) { bad++; continue; }
        const er = d.edges(i, opts); const act = d.activeBanks(i);
        const bp = d.pagerank(er.edges, act); const ds = d.degreeStrength(er.edges, act);
        d.centrality().banks.forEach((id, k) => {
          const cp = entry.pagerank[k], pp = bp[id];
          if (cp == null || pp == null) { if (cp !== pp) bad++; }
          else maxPR = Math.max(maxPR, Math.abs(cp - pp));
          const cs = entry.strength[k], bs = ds.strength[id];
          if (cs == null || bs == null) { if (cs !== bs) bad++; }
          else maxST = Math.max(maxST, Math.abs(cs - bs));
          if (entry.degree[k] !== ds.degree[id]) bad++;
        });
        if (entry.n_edges !== er.edges.length) bad++;
        if (Math.abs(entry.threshold - er.threshold) > 1e-9) bad++;
        cells++;
      }
    }
  }
  T('V-SC centrality agreement (' + cells + ' cells)', bad === 0 && maxPR < 0.001 && maxST < 0.001);
  console.log('max|PR diff|=' + maxPR.toExponential(3) + ' max|strength diff|=' + maxST.toExponential(3));
  console.log(pass + ' passed, ' + fail + ' failed');
  process.exit(fail ? 1 : 0);
});
"""


def main() -> int:
    js = JS % {
        "bundle": json.dumps(str(ROOT / "js" / "data_bundle.js")),
        "state": json.dumps(str(ROOT / "js" / "state.js")),
        "data": json.dumps(str(ROOT / "js" / "data.js")),
    }
    proc = subprocess.run(["node", "-e", js], cwd=ROOT)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())