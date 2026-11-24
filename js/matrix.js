/* Matrix view (M6 + S1) — plan v3 D3/D4.
 * 19x19 data join, one shared diverging scale for both modes: reversed RdBu,
 * domain [-0.8, 0, 0.8], clamped (negative = blue, positive = red).
 * Null cells are striped (never near-white, which would read as 0); diagonal is
 * dark grey with a dash. Cell click -> selectedPair + pair panel with sparkline.
 * Ordering in P3A is the D8 default (state -> private, A-Z); the selector lands in P3B. */
window.DSDV = window.DSDV || {};
DSDV.views = DSDV.views || {};

DSDV.views.matrix = (function () {
  const data = () => DSDV.data;
  const state = () => DSDV.state;
  const CELL = 24, GAP = 1, STEP = CELL + GAP, LBL = 48, TOP = 34;
  const COLORS = DSDV.ui.COLORS;
  const GROUP_COLORS = DSDV.ui.GROUP_COLORS;
  const showTip = DSDV.ui.showTip, hideTip = DSDV.ui.hideTip;
  const SPARK_W = 252, SPARK_H = 96, SPARK_L = 30;
  const color = d3.scaleDiverging(t => d3.interpolateRdBu(1 - t))
    .domain([-0.8, 0, 0.8]).clamp(true);

  let host = null, svg = null, cellsG = null, outlineG = null;
  let cellSel = null, rowSel = null, colSel = null;
  let order = [], pos = {}, grid = 0;
  let titleEl = null, panel = null, spark = null, sparkY = null;

  function groupOrder() {
    const banks = data().banks();
    const byGroup = g => banks.filter(b => (b.group === 'state') === (g === 'state'))
      .map(b => b.id).sort();
    return byGroup('state').concat(byGroup('private'));
  }

  function cellXY(d) {
    return { x: LBL + pos[d.c] * STEP, y: TOP + pos[d.r] * STEP };
  }

  function edgeInfo(s) {
    const er = data().edges(s.windowIndex, s);
    const matched = s.mode === 'residual' && s.matchRawEdges;
    return { t: er.threshold, matched, floorHit: er.floorHit };
  }

  function tipHTML(d, s) {
    if (d.diag) return '<b>' + d.r + '</b><br>Diagonal — not a pair';
    const dd = data();
    const raw = dd.pairValue(s.windowIndex, 'raw', d.r, d.c);
    if (raw == null) return '<b>' + d.r + '–' + d.c + '</b><br>N/A – no data in this window';
    const res = dd.pairValue(s.windowIndex, 'residual', d.r, d.c);
    const e = edgeInfo(s);
    const v = s.mode === 'raw' ? raw : res;
    const first = s.mode === 'raw'
      ? 'Raw ' + raw.toFixed(3) + ' · Residual ' + res.toFixed(3)
      : 'Residual ' + res.toFixed(3) + ' · Raw ' + raw.toFixed(3);
    return '<b>' + d.r + '–' + d.c + '</b> · window ending ' + dd.window(s.windowIndex).end +
      '<br>' + first +
      '<br>Edge at ' + (e.matched ? 'matched ' : '') + 'threshold ' + e.t.toFixed(3) + ': ' +
      (v >= e.t ? 'Yes' : 'No');
  }

  function init(el) {
    order = groupOrder();
    pos = {};
    order.forEach((id, k) => { pos[id] = k; });
    grid = order.length * STEP - GAP;
    const W = LBL + grid + 2;
    const cbY = TOP + grid + 26;
    const H = cbY + 40;

    el.innerHTML =
      '<div class="matrix-title"></div>' +
      '<div class="matrix-wrap">' +
      '<div class="matrix-chart"></div>' +
      '<div class="pair-panel">' +
      '<h3>Pair detail</h3>' +
      '<p class="pair-empty">Click a matrix cell to inspect a pair across all 88 windows. ' +
      'Click a bank label to select the bank.</p>' +
      '<div class="pair-body" hidden>' +
      '<div class="pair-title"><span class="pair-names"></span>' +
      '<span class="pair-window muted"></span></div>' +
      '<table class="pair-table"><tbody>' +
      '<tr><td>Raw</td><td class="pv-raw"></td></tr>' +
      '<tr><td>Residual</td><td class="pv-res"></td></tr>' +
      '<tr><td>Raw − residual</td><td class="pv-diff"></td></tr>' +
      '</tbody></table>' +
      '<p class="pair-edge"></p>' +
      '<svg class="pair-spark" width="' + SPARK_W + '" height="' + SPARK_H + '" ' +
      'role="img" aria-label="Pair correlation across all windows"></svg>' +
      '<p class="pair-hint">Sparkline: raw &amp; residual, 88 windows, y fixed −0.4 to 0.9. ' +
      'Click to jump to a window.</p>' +
      '</div></div></div>' +
      '<p class="matrix-note">Order: state-owned → private, A–Z within each group. ' +
      'Shared scale for both modes; striped cells = no data in this window.</p>';
    titleEl = el.querySelector('.matrix-title');
    host = el.querySelector('.matrix-chart');
    panel = {
      empty: el.querySelector('.pair-empty'),
      body: el.querySelector('.pair-body'),
      names: el.querySelector('.pair-names'),
      window: el.querySelector('.pair-window'),
      raw: el.querySelector('.pv-raw'),
      res: el.querySelector('.pv-res'),
      diff: el.querySelector('.pv-diff'),
      edge: el.querySelector('.pair-edge')
    };

    svg = d3.select(host).append('svg').attr('width', W).attr('height', H)
      .attr('role', 'img').attr('aria-label', '19 by 19 correlation matrix');
    const defs = svg.append('defs');
    const stripe = defs.append('pattern')
      .attr('id', 'mx-null').attr('width', 6).attr('height', 6)
      .attr('patternUnits', 'userSpaceOnUse').attr('patternTransform', 'rotate(45)');
    stripe.append('rect').attr('width', 6).attr('height', 6).attr('fill', '#f5f5f5');
    stripe.append('line').attr('x1', 0).attr('y1', 0).attr('x2', 0).attr('y2', 6)
      .attr('stroke', '#bdbdbd').attr('stroke-width', 3);
    const grad = defs.append('linearGradient').attr('id', 'mx-cbar');
    d3.range(0, 1.0001, 0.1).forEach(t =>
      grad.append('stop').attr('offset', (t * 100) + '%').attr('stop-color', color(-0.8 + 1.6 * t)));

    // Cells: one join, keyed by pair id; only fill changes on window/mode updates
    const cells = [];
    order.forEach(r => order.forEach(c => cells.push({ key: r + '|' + c, r, c, diag: r === c })));
    cellsG = svg.append('g');
    cellSel = cellsG.selectAll('rect').data(cells, d => d.key).join('rect')
      .attr('class', d => 'mx-cell' + (d.diag ? ' mx-diag' : ''))
      .attr('x', d => cellXY(d).x).attr('y', d => cellXY(d).y)
      .attr('width', CELL).attr('height', CELL)
      .on('mousemove', (ev, d) => showTip(ev, tipHTML(d, state().get())))
      .on('mouseleave', hideTip)
      .on('click', (ev, d) => {
        if (d.diag) return;
        const key = data().pairKey(d.r, d.c);
        const s = state().get();
        state().set({ selectedPair: s.selectedPair === key ? null : key }, 'matrix');
      });
    cellsG.selectAll('text').data(order).join('text')
      .attr('class', 'mx-diag-mark')
      .attr('x', id => LBL + pos[id] * STEP + CELL / 2)
      .attr('y', id => TOP + pos[id] * STEP + CELL / 2)
      .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
      .text('—');

    // Labels: dark text + 4px ownership bar (D4 contrast rule)
    const banks = {};
    data().banks().forEach(b => { banks[b.id] = b; });
    rowSel = svg.append('g').selectAll('g').data(order).join('g')
      .attr('class', 'mx-row-label');
    rowSel.append('rect')
      .attr('x', LBL - 7).attr('y', id => TOP + pos[id] * STEP + CELL / 2 - 6)
      .attr('width', 4).attr('height', 12).attr('rx', 1)
      .attr('fill', id => GROUP_COLORS[banks[id].group]);
    rowSel.append('text')
      .attr('x', LBL - 11).attr('y', id => TOP + pos[id] * STEP + CELL / 2)
      .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
      .text(id => id);
    colSel = svg.append('g').selectAll('g').data(order).join('g')
      .attr('class', 'mx-col-label');
    colSel.append('text')
      .attr('x', id => LBL + pos[id] * STEP + CELL / 2).attr('y', TOP - 12)
      .attr('text-anchor', 'middle').text(id => id);
    colSel.append('rect')
      .attr('x', id => LBL + pos[id] * STEP + CELL / 2 - 6).attr('y', TOP - 8)
      .attr('width', 12).attr('height', 4).attr('rx', 1)
      .attr('fill', id => GROUP_COLORS[banks[id].group]);
    const labelTip = (ev, id) => {
      const active = data().activeBanks(state().get().windowIndex).includes(id);
      showTip(ev, '<b>' + id + '</b> · ' +
        (banks[id].group === 'state' ? 'State-owned' : 'Private') + '<br>' +
        (active ? 'Click to select' : 'N/A – no data in this window'));
    };
    rowSel.on('click', (ev, id) => pickBank(id))
      .on('mousemove', labelTip).on('mouseleave', hideTip);
    colSel.on('click', (ev, id) => pickBank(id))
      .on('mousemove', labelTip).on('mouseleave', hideTip);

    outlineG = svg.append('g').attr('class', 'mx-outlines');

    // Colorbar (D3): shared scale, clamped ends labelled with arrows
    const cb = svg.append('g');
    cb.append('text').attr('class', 'mx-cbar-title').attr('x', LBL).attr('y', cbY - 8)
      .text('Correlation — shared scale, both modes');
    cb.append('rect').attr('x', LBL).attr('y', cbY).attr('width', 200).attr('height', 10)
      .attr('fill', 'url(#mx-cbar)').attr('stroke', '#d8dee8');
    cb.append('text').attr('class', 'mx-cbar-end').attr('x', LBL - 6).attr('y', cbY + 9)
      .attr('text-anchor', 'end').text('≤ −0.8');
    cb.append('text').attr('class', 'mx-cbar-end').attr('x', LBL + 206).attr('y', cbY + 9)
      .text('≥ +0.8');
    [-0.4, 0, 0.4].forEach(v => {
      const cx = LBL + (v + 0.8) / 1.6 * 200;
      cb.append('line').attr('x1', cx).attr('x2', cx).attr('y1', cbY + 10).attr('y2', cbY + 14)
        .attr('stroke', '#9aa7ba');
      cb.append('text').attr('class', 'mx-cbar-tick').attr('x', cx).attr('y', cbY + 27)
        .attr('text-anchor', 'middle').text(v === 0 ? '0' : d3.format('+.1f')(v));
    });

    initSpark(el);
  }

  function pickBank(id) {
    const s = state().get();
    if (!data().activeBanks(s.windowIndex).includes(id)) return;
    state().set({ selectedBank: s.selectedBank === id ? null : id }, 'matrix');
  }

  function initSpark(el) {
    spark = d3.select(el).select('.pair-spark');
    sparkY = d3.scaleLinear().domain([-0.4, 0.9]).range([SPARK_H - 16, 6]);
    const sy = sparkY;
    spark.append('line').attr('class', 'sp-zero')
      .attr('x1', SPARK_L).attr('x2', SPARK_W - 2).attr('y1', sy(0)).attr('y2', sy(0));
    [[0.9, '0.9'], [0, '0'], [-0.4, '−0.4']].forEach(([v, lab]) =>
      spark.append('text').attr('class', 'sp-tick').attr('x', SPARK_L - 4).attr('y', sy(v) + 4)
        .attr('text-anchor', 'end').text(lab));
    spark.append('path').attr('class', 'sp-line sp-raw').attr('stroke', COLORS.raw);
    spark.append('path').attr('class', 'sp-line sp-res').attr('stroke', COLORS.residual);
    spark.append('line').attr('class', 'sp-marker');
    spark.append('circle').attr('class', 'sp-dot sp-dot-raw').attr('r', 3).attr('fill', COLORS.raw);
    spark.append('circle').attr('class', 'sp-dot sp-dot-res').attr('r', 3).attr('fill', COLORS.residual);
    spark.append('rect').attr('class', 'sp-overlay')
      .attr('x', SPARK_L).attr('y', 0).attr('width', SPARK_W - SPARK_L - 2).attr('height', SPARK_H)
      .on('click', ev => {
        const px = d3.pointer(ev, spark.node())[0];
        const n = data().windowCount();
        const i = Math.round((px - SPARK_L) / (SPARK_W - 2 - SPARK_L) * (n - 1));
        state().set({ windowIndex: Math.max(0, Math.min(n - 1, i)) }, 'matrix');
      });
  }

  function renderSpark(a, b, s) {
    const dd = data();
    const n = dd.windowCount();
    const raw = dd.windows().map((w, i) => dd.pairValue(i, 'raw', a, b));
    const res = dd.windows().map((w, i) => dd.pairValue(i, 'residual', a, b));
    const sx = i => SPARK_L + i / (n - 1) * (SPARK_W - 2 - SPARK_L);
    const sy = sparkY;
    const line = d3.line().defined(v => v != null).x((v, i) => sx(i)).y(v => sy(v));
    spark.select('.sp-raw').attr('d', line(raw));
    spark.select('.sp-res').attr('d', line(res));
    const mx = sx(s.windowIndex);
    spark.select('.sp-marker').attr('x1', mx).attr('x2', mx).attr('y1', 4).attr('y2', SPARK_H - 14);
    const rv = raw[s.windowIndex], sv = res[s.windowIndex];
    spark.select('.sp-dot-raw').style('display', rv == null ? 'none' : null)
      .attr('cx', mx).attr('cy', rv == null ? 0 : sy(rv));
    spark.select('.sp-dot-res').style('display', sv == null ? 'none' : null)
      .attr('cx', mx).attr('cy', sv == null ? 0 : sy(sv));
  }

  function renderPanel(s) {
    if (!s.selectedPair) {
      panel.empty.hidden = false;
      panel.body.hidden = true;
      return;
    }
    const [a, b] = s.selectedPair.split('|');
    const dd = data();
    const raw = dd.pairValue(s.windowIndex, 'raw', a, b);
    const res = dd.pairValue(s.windowIndex, 'residual', a, b);
    const groups = {};
    dd.banks().forEach(x => { groups[x.id] = x.group; });
    const bar = id => '<span class="group-bar" style="background:' +
      GROUP_COLORS[groups[id]] + '"></span>';
    panel.empty.hidden = true;
    panel.body.hidden = false;
    panel.names.innerHTML = bar(a) + a + ' – ' + bar(b) + b;
    panel.window.textContent = 'window ending ' + dd.window(s.windowIndex).end;
    panel.raw.textContent = raw == null ? 'N/A' : raw.toFixed(3);
    panel.res.textContent = res == null ? 'N/A' : res.toFixed(3);
    panel.diff.textContent = (raw == null || res == null) ? '—' : (raw - res).toFixed(3);
    const e = edgeInfo(s);
    const v = s.mode === 'raw' ? raw : res;
    if (v == null) {
      panel.edge.textContent = 'N/A – no data in this window';
    } else {
      const isEdge = v >= e.t;
      panel.edge.innerHTML = 'Edge at ' + (e.matched ? 'matched ' : '') + 'threshold ' +
        e.t.toFixed(3) + (e.floorHit ? ' (floor)' : '') + ': <b>' + (isEdge ? 'Yes' : 'No') +
        '</b> in ' + s.mode + ' mode';
    }
    renderSpark(a, b, s);
  }

  function render(s) {
    if (!svg) return;
    hideTip();   // a cell under the mouse may change value/position on this render
    const dd = data();
    const active = new Set(dd.activeBanks(s.windowIndex));
    titleEl.textContent = (s.mode === 'raw' ? 'Raw' : 'Residual') +
      ' correlations · window ending ' + dd.window(s.windowIndex).end;

    cellSel.attr('fill', d => {
      if (d.diag) return '#737373';
      const v = dd.pairValue(s.windowIndex, s.mode, d.r, d.c);
      return v == null ? 'url(#mx-null)' : color(v);
    });
    rowSel.classed('inactive', id => !active.has(id));
    colSel.classed('inactive', id => !active.has(id));

    // Selection outlines (D4: border only, never a fill change)
    const marks = [];
    if (s.selectedBank && pos[s.selectedBank] !== undefined) {
      const k = pos[s.selectedBank];
      marks.push({ key: 'row', x: LBL - 1, y: TOP + k * STEP - 1, w: grid + 2, h: CELL + 2 });
      marks.push({ key: 'col', x: LBL + k * STEP - 1, y: TOP - 1, w: CELL + 2, h: grid + 2 });
    }
    if (s.selectedPair) {
      const [a, b] = s.selectedPair.split('|');
      if (pos[a] !== undefined && pos[b] !== undefined) {
        [[a, b], [b, a]].forEach(([r, c]) => marks.push({
          key: 'pair:' + r + '|' + c,
          x: LBL + pos[c] * STEP - 1, y: TOP + pos[r] * STEP - 1, w: CELL + 2, h: CELL + 2
        }));
      }
    }
    outlineG.selectAll('rect').data(marks, d => d.key).join('rect')
      .attr('x', d => d.x).attr('y', d => d.y).attr('width', d => d.w).attr('height', d => d.h);

    renderPanel(s);
  }

  function update(s) {
    if (s.activeTab !== 'matrix') return;   // hidden tab: skip redraw (§4.1)
    render(s);
  }

  return { init, update };
})();