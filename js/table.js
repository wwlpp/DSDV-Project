/* Ranking view (M4 + S5) — plan v3 D7 tiers, D5 source badge.
 * Reads centrality measures through DSDV.data.metrics() so on-grid settings use
 * centrality.json and off-grid settings compute in browser with identical shape.
 * Local state (tableFilter) stays here, not in the shared contract. */
window.DSDV = window.DSDV || {};
DSDV.views = DSDV.views || {};

DSDV.views.ranking = (function () {
  const data = () => DSDV.data;
  const state = () => DSDV.state;
  const showTip = DSDV.ui.showTip, hideTip = DSDV.ui.hideTip;
  const GROUP_COLORS = DSDV.ui.GROUP_COLORS;
  let filter = 'all';           // 'all' | 'state' | 'private'  (S5, view-local)
  let tbody = null;

  function buildRows(s) {
    const d = data();
    const m = d.metrics(s.windowIndex, s);
    const active = d.activeBanks(s.windowIndex);
    const base = active.length ? 1 / active.length : 0;
    const groups = {};
    d.banks().forEach(b => { groups[b.id] = b.group; });
    const rows = d.bankIds().map(id => {
      const pr = m.pagerank[id];
      if (pr == null) return { id, group: groups[id], inactive: true };
      return {
        id, group: groups[id], inactive: false,
        pr, degree: m.degree[id], strength: m.strength[id],
        tier: d.tier(pr, m.degree[id], active.length), ratio: base ? pr / base : 0
      };
    });
    const act = rows.filter(r => !r.inactive).sort((a, b) => b.pr - a.pr);
    act.forEach((r, k) => { r.rank = k + 1; });
    const ina = rows.filter(r => r.inactive).sort((a, b) => a.id < b.id ? -1 : 1);
    return act.concat(ina);
  }

  function visible(rows) {
    if (filter === 'all') return rows;
    return rows.filter(r => r.group === filter);
  }

  function init(el) {
    el.innerHTML =
      '<div class="ranking-filter" role="group" aria-label="Filter by ownership">' +
      ['all', 'state', 'private'].map(f =>
        '<button type="button" data-filter="' + f + '" aria-pressed="' + (f === filter) + '">' +
        (f === 'all' ? 'All' : f === 'state' ? 'State' : 'Private') + '</button>').join('') +
      '</div>' +
      '<table class="ranking-table"><thead><tr>' +
      '<th>Tier</th><th>Bank</th><th>PR</th><th>PR/base</th><th>Deg</th><th>Str</th>' +
      '</tr></thead><tbody></tbody></table>' +
      '<p class="ranking-note">Top PageRank scores are close; read by tier — differences below ' +
      '0.5 percentage points are not meaningful. Numeric rank is in the row tooltip.</p>';
    tbody = el.querySelector('tbody');
    el.querySelectorAll('.ranking-filter button').forEach(btn => {
      btn.addEventListener('click', () => {
        filter = btn.dataset.filter;
        el.querySelectorAll('.ranking-filter button').forEach(b =>
          b.setAttribute('aria-pressed', String(b === btn)));
        render(state().get());
      });
    });
  }

  function render(s) {
    if (!tbody) return;
    hideTip();   // a row under the mouse may be removed by this render
    const rows = visible(buildRows(s));
    const maxPR = d3.max(rows.filter(r => !r.inactive), r => r.pr) || 1;
    const sel = s.selectedBank;

    const tr = d3.select(tbody).selectAll('tr').data(rows, r => r.id);
    tr.exit().remove();
    const enter = tr.enter().append('tr')
      .attr('tabindex', 0)
      .on('click', (ev, r) => { if (!r.inactive) pick(r.id); })
      .on('keydown', (ev, r) => {
        if ((ev.key === 'Enter' || ev.key === ' ') && !r.inactive) { ev.preventDefault(); pick(r.id); }
      })
      .on('mousemove', (ev, r) => {
        if (r.inactive) { showTip(ev, '<b>' + r.id + '</b><br>N/A – no data in this window'); return; }
        showTip(ev, '<b>' + r.id + '</b> · rank #' + r.rank + '<br>PageRank ' + (r.pr * 100).toFixed(3) +
          '%<br>' + r.tier + ' · ' + r.ratio.toFixed(2) + '× baseline');
      })
      .on('mouseleave', hideTip);
    enter.append('td').attr('class', 'rk-tier');
    enter.append('td').attr('class', 'rk-bank');
    enter.append('td').attr('class', 'rk-pr');
    enter.append('td').attr('class', 'rk-ratio');
    enter.append('td').attr('class', 'rk-deg');
    enter.append('td').attr('class', 'rk-str');

    const all = enter.merge(tr);
    all.classed('selected', r => r.id === sel)
      .classed('inactive', r => r.inactive)
      .classed('dimmed', r => sel != null && r.id !== sel && !r.inactive);
    all.select('.rk-tier').text(r => r.inactive ? '—' : r.tier)
      .attr('data-tier', r => r.inactive ? '' : r.tier);
    all.select('.rk-bank').html(r =>
      '<span class="group-bar" style="background:' + GROUP_COLORS[r.group] + '"></span>' + r.id);
    all.select('.rk-pr').html(r => r.inactive
      ? '<span class="na">N/A – no data in this window</span>'
      : '<span class="pr-bar"><span style="width:' + (r.pr / maxPR * 100).toFixed(1) + '%"></span></span>' +
        '<span class="pr-val">' + (r.pr * 100).toFixed(1) + '%</span>');
    all.select('.rk-ratio').text(r => r.inactive ? '—' : r.ratio.toFixed(2) + '×');
    all.select('.rk-deg').text(r => r.inactive ? '—' : r.degree);
    all.select('.rk-str').text(r => r.inactive ? '—' : r.strength.toFixed(2));
    // Null rows: one colspan cell, so the N/A sentence can never widen the
    // nowrap PR column past the sidebar width (DoD-7).
    all.select('.rk-pr').attr('colspan', r => r.inactive ? 4 : null);
    ['.rk-ratio', '.rk-deg', '.rk-str'].forEach(sel =>
      all.select(sel).style('display', r => r.inactive ? 'none' : null));
    all.order();   // keep DOM order = data order (active by PR, then nulls at bottom)
  }

  function pick(id) {
    const s = state().get();
    state().set({ selectedBank: s.selectedBank === id ? null : id }, 'ranking');
  }

  function update(s, changed) {
    // Ranking sidebar is independent of the active tab and of pair selection.
    if (changed && changed.length &&
        changed.every(k => k === 'activeTab' || k === 'selectedPair')) return;
    render(s);
  }

  return { init, update };
})();