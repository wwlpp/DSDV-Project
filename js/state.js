/* Shared state contract — plan v3 §4.2 (Đạt + Tín).
 * Field names are frozen with the team; local view state stays in each view module.
 * Do not add view-local fields here without notifying the whole team. */
window.DSDV = window.DSDV || {};
DSDV.views = DSDV.views || {};

DSDV.state = (function () {
  const s = {
    mode: 'raw',          // 'raw' | 'residual'
    windowIndex: 87,      // 0..87; 87 = window ending 2026-09-30
    threshold: 0.50,      // 0.05..0.90
    matchRawEdges: true,  // residual: match raw edge count, floor 0.05 (D1)
    selectedBank: null,   // string id, e.g. 'MBB' — never an index
    selectedPair: null,   // sorted string key, e.g. 'MBB|TCB'
    playing: false,
    activeTab: 'network'  // 'network' | 'matrix' | 'analysis' | 'about'
  };
  const subs = [];
  return {
    get: () => ({ ...s }),
    set(patch, source) {
      const changed = Object.keys(patch).filter(k => s[k] !== patch[k]);
      if (!changed.length) return;            // block update loops
      Object.assign(s, patch);
      subs.forEach(fn => fn({ ...s }, changed, source));
    },
    on(fn) { subs.push(fn); }
  };
})();