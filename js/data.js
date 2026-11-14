/* Shared data layer — plan v3 §4 (loader, edges with D1 floor, PageRank per D2).
 * Single source of truth for every view; no view may recompute these differently. */
window.DSDV = window.DSDV || {};

DSDV.data = (function () {
  const FLOOR = 0.05;        // D1: residual matched threshold never goes below this
  const ALPHA = 0.85;        // D2: PageRank damping
  const TOL = 1e-10;         // D2: L1 convergence tolerance
  const MAX_ITER = 200;

  let net = null;            // network_data.json
  let summary = null;        // [{end, raw, residual, n_banks}]
  let centrality = null;     // centrality.json when available (Lợi)
  let clusterOrder = null;   // cluster_order.json when available (Lợi)
  let sensitivity = null;    // sensitivity.json when available (Lợi)
  let source = 'none';       // 'fetch' | 'bundle'
  let bankIds = [];
  let pairIndex = new Map(); // 'A|B' -> index into pairs/values

  function pairKey(a, b) { return a < b ? a + '|' + b : b + '|' + a; }

  function parseSummary(text) {
    const rows = [];
    const lines = text.trim().split(/\r?\n/);
    const head = lines[0].split(',');
    const iEnd = head.indexOf('window_end'), iMode = head.indexOf('mode');
    const iAvg = head.indexOf('avg_corr'), iN = head.indexOf('n_banks');
    const byEnd = new Map();
    for (let k = 1; k < lines.length; k++) {
      const c = lines[k].split(',');
      const end = c[iEnd];
      if (!byEnd.has(end)) byEnd.set(end, { end, raw: null, residual: null, n_banks: null });
      const row = byEnd.get(end);
      row[c[iMode]] = parseFloat(c[iAvg]);
      row.n_banks = parseInt(c[iN], 10);
    }
    for (const row of byEnd.values()) rows.push(row);
    rows.sort((a, b) => a.end < b.end ? -1 : 1);
    return rows;
  }

  function indexData() {
    bankIds = net.banks.map(b => b.id);
    pairIndex = new Map();
    net.pairs.forEach((p, k) => pairIndex.set(pairKey(bankIds[p[0]], bankIds[p[1]]), k));
  }

  async function fetchOptional(name, fallback) {
    try {
      const r = await fetch('data/processed/' + name);
      return r.ok ? await r.json() : fallback;
    } catch (e) { return fallback; }
  }

  async function load() {
    const bundle = window.DSDV_BUNDLE || null;
    // Only request an optional file when the bundle confirms it exists, so absent
    // deliverables (centrality/cluster/sensitivity) never log 404 console errors.
    const listed = name => !!(bundle && bundle.hashes && bundle.hashes[name]);
    const optional = (name, key) => listed(name)
      ? fetchOptional(name, bundle[key] || null)
      : (bundle ? (bundle[key] || null) : null);
    const canFetch = location.protocol === 'http:' || location.protocol === 'https:';
    if (canFetch) {
      try {
        const [nj, sc] = await Promise.all([
          fetch('data/processed/network_data.json').then(r => {
            if (!r.ok) throw new Error('network_data.json: HTTP ' + r.status);
            return r.json();
          }),
          fetch('data/processed/summary.csv').then(r => {
            if (!r.ok) throw new Error('summary.csv: HTTP ' + r.status);
            return r.text();
          })
        ]);
        net = nj;
        summary = parseSummary(sc);
        [centrality, clusterOrder, sensitivity] = await Promise.all([
          optional('centrality.json', 'centrality'),
          optional('cluster_order.json', 'cluster_order'),
          optional('sensitivity.json', 'sensitivity')
        ]);
        source = 'fetch';
        indexData();
        return api;
      } catch (e) { /* fall back to bundle below */ }
    }
    if (bundle && bundle.network && bundle.summary_csv) {
      net = bundle.network;
      summary = parseSummary(bundle.summary_csv);
      centrality = bundle.centrality || null;
      clusterOrder = bundle.cluster_order || null;
      sensitivity = bundle.sensitivity || null;
      source = 'bundle';
      indexData();
      return api;
    }
    throw new Error('No data available. Serve over http(s), or run "python src/make_bundle.py" for file:// use.');
  }

  /* D1: when matching raw edge count, the n-th largest residual can be negative;
   * negative weights make PageRank meaningless, so clamp at FLOOR and flag it. */
  function edges(i, opts) {
    const w = net.windows[i];
    const mode = opts.mode, match = opts.matchRawEdges;
    let t = opts.threshold, matched = null, floorHit = false;
    if (mode === 'residual' && match) {
      const n = w.raw.filter(c => c != null && c >= opts.threshold).length;
      const sorted = w.residual.filter(c => c != null).sort((a, b) => b - a);
      matched = (n > 0 && sorted.length) ? sorted[Math.min(n, sorted.length) - 1] : 1.01;
      t = Math.max(matched, FLOOR);
      floorHit = matched < FLOOR;
    }
    const list = [];
    w[mode].forEach((c, k) => {
      if (c != null && c >= t) {
        const p = net.pairs[k];
        list.push({ a: bankIds[p[0]], b: bankIds[p[1]], c });
      }
    });
    return { edges: list, threshold: t, matchedThreshold: matched, floorHit };
  }

  function activeBanks(i) {
    const w = net.windows[i];
    const act = new Set();
    w.raw.forEach((c, k) => {
      if (c != null) { act.add(bankIds[net.pairs[k][0]]); act.add(bankIds[net.pairs[k][1]]); }
    });
    return bankIds.filter(id => act.has(id));
  }

  /* D2: PageRank over active banks only, weights = edge correlations.
   * Dangling mass (degree-0 banks) is shared equally among active banks.
   * Inactive banks get null, never 0. */
  function pagerank(edgeList, activeIds) {
    const n = activeIds.length;
    const out = {};
    bankIds.forEach(id => { out[id] = null; });
    if (!n) return out;
    const idx = new Map(activeIds.map((id, k) => [id, k]));
    const adj = Array.from({ length: n }, () => []);
    const s = new Array(n).fill(0);
    for (const e of edgeList) {
      const i = idx.get(e.a), j = idx.get(e.b);
      if (i === undefined || j === undefined) continue;
      adj[i].push([j, e.c]); adj[j].push([i, e.c]);
      s[i] += e.c; s[j] += e.c;
    }
    let r = new Array(n).fill(1 / n);
    for (let it = 0; it < MAX_ITER; it++) {
      const next = new Array(n).fill((1 - ALPHA) / n);
      let dangling = 0;
      for (let i = 0; i < n; i++) {
        if (s[i] === 0) { dangling += r[i]; continue; }
        for (const [j, c] of adj[i]) next[j] += ALPHA * r[i] * c / s[i];
      }
      const share = ALPHA * dangling / n;
      let diff = 0;
      for (let i = 0; i < n; i++) { next[i] += share; diff += Math.abs(next[i] - r[i]); }
      r = next;
      if (diff < TOL) break;
    }
    activeIds.forEach((id, k) => { out[id] = r[k]; });
    return out;
  }

  function degreeStrength(edgeList, activeIds) {
    const degree = {}, strength = {};
    bankIds.forEach(id => { degree[id] = null; strength[id] = null; });
    activeIds.forEach(id => { degree[id] = 0; strength[id] = 0; });
    for (const e of edgeList) {
      if (degree[e.a] == null || degree[e.b] == null) continue;
      degree[e.a]++; degree[e.b]++;
      strength[e.a] += e.c; strength[e.b] += e.c;
    }
    return { degree, strength };
  }

  function pairValue(i, mode, a, b) {
    const k = pairIndex.get(pairKey(a, b));
    return k === undefined ? null : net.windows[i][mode][k];
  }

  const api = {
    load,
    edges,
    activeBanks,
    pagerank,
    degreeStrength,
    pairKey,
    pairValue,
    FLOOR,
    ALPHA,
    banks: () => net.banks,
    bankIds: () => bankIds.slice(),
    pairs: () => net.pairs,
    windows: () => net.windows,
    window: i => net.windows[i],
    windowCount: () => net.windows.length,
    meta: () => net.meta,
    summary: () => summary,
    summaryAt: i => summary[i],
    avgSeries: mode => summary.map(r => r[mode]),
    centrality: () => centrality,
    clusterOrder: () => clusterOrder,
    sensitivity: () => sensitivity,
    source: () => source
  };
  return api;
})();