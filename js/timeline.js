/* Timeline view (M5 + S3 + S2) — plan v3 D6/D10, errata v3.1 dates.
 * Two solid lines (raw, residual) + dashed balanced 15-bank residual panel,
 * fixed y [0, 0.7] for both modes. Click/drag changes the window.
 * Annotation wording is descriptive only (§8): "window ending …" phrasing. */
window.DSDV = window.DSDV || {};
DSDV.views = DSDV.views || {};

DSDV.views.timeline = (function () {
  const data = () => DSDV.data;
  const state = () => DSDV.state;
  const H = 250;
  const M = { top: 34, right: 14, bottom: 26, left: 44 };
  const COLORS = DSDV.ui.COLORS;
  const showTip = DSDV.ui.showTip, hideTip = DSDV.ui.hideTip;
  const parseDate = d3.utcParse('%Y-%m-%d');

  const ENTRIES = [
    { end: '2021-08-10', label: 'NAB enters', anchor: 'end', row: 0 },
    { end: '2021-11-04', label: 'MSB + ABB enter', anchor: 'middle', row: 1 },
    { end: '2021-12-02', label: 'OCB enters', anchor: 'start', row: 0 }
  ];
  const REGIONS = [
    {
      from: '2022-05-04', to: '2022-08-24',
      lines: ['Residual peaks ≈ 0.30 in windows ending May–Aug 2022;',
              'it rises while four banks enter (windows ending Aug–Dec 2021)']
    },
    {
      from: '2025-03-20', to: '2025-04-18',
      lines: ['Raw-only jump: raw +0.14, residual +0.02',
              '(window ending 2025-04-18)']
    }
  ];
  const JUMPS = [
    { label: 'May–Aug 2022', end: '2022-07-27', title: 'Residual peak — window ending 2022-07-27' },
    { label: 'Apr 2025', end: '2025-04-18', title: 'Raw-only jump — window ending 2025-04-18' },
    { label: 'Latest', end: null, title: 'Latest window' }
  ];

  let host = null, svg = null, g = null, x = null, y = null;
  let innerW = 0, innerH = 0;
  let dates = [], ends = [];
  let markerLine = null, dotRaw = null, dotRes = null;
  let bankPath = null, bankLabel = null;
  let dragging = false;
  const bisect = d3.bisector(d => d).center;

  function nearestIndex(ev) {
    const px = d3.pointer(ev, g.node())[0];
    const i = bisect(dates, x.invert(Math.max(0, Math.min(innerW, px))));
    return Math.max(0, Math.min(dates.length - 1, i));
  }

  function tipHTML(i, s) {
    const d = data();
    const sum = d.summaryAt(i);
    const ratio = sum.raw ? (sum.residual / sum.raw).toFixed(3) : '—';
    let html = '<b>Window ending ' + sum.end + '</b><br>' +
      'Raw ' + sum.raw.toFixed(4) + ' · Residual ' + sum.residual.toFixed(4) + '<br>' +
      'Residual/Raw ' + ratio + ' (descriptive ratio of averages)<br>' +
      'Balanced 15-bank residual ' + d.balancedSeries('residual')[i].toFixed(4) + '<br>' +
      'Active banks ' + sum.n_banks + '/' + d.bankIds().length;
    if (s.selectedBank) {
      const v = d.bankAvgSeries(s.selectedBank, s.mode)[i];
      html += '<br><b>' + s.selectedBank + '</b> avg (' + s.mode + ') ' +
        (v == null ? 'N/A' : v.toFixed(4));
    }
    return html;
  }

  function build() {
    dragging = false;   // a rebuild drops the old overlay and its pointer capture
    const d = data();
    ends = d.windows().map(w => w.end);
    dates = ends.map(parseDate);
    const W = Math.max(320, host.clientWidth);
    innerW = W - M.left - M.right;
    innerH = H - M.top - M.bottom;
    x = d3.scaleUtc().domain([dates[0], dates[dates.length - 1]]).range([0, innerW]);
    y = d3.scaleLinear().domain([0, 0.7]).range([innerH, 0]);   // fixed for both modes (D3 lie-factor guard)

    d3.select(host).select('svg').remove();
    svg = d3.select(host).append('svg')
      .attr('width', W).attr('height', H)
      .attr('role', 'img')
      .attr('aria-label', 'Average connectedness over time: raw and residual lines with balanced panel');
    g = svg.append('g').attr('transform', 'translate(' + M.left + ',' + M.top + ')');

    // Annotation regions (D4: neutral black 6%, never orange)
    const regions = g.append('g');
    REGIONS.forEach(r => {
      const x0 = x(parseDate(r.from)) - 4, x1 = x(parseDate(r.to)) + 4;
      regions.append('rect')
        .attr('x', x0).attr('y', 0).attr('width', x1 - x0).attr('height', innerH)
        .attr('fill', 'rgba(0,0,0,0.06)');
      const text = regions.append('text').attr('class', 'tl-annotation').attr('x', x0);
      r.lines.forEach((ln, k) =>
        text.append('tspan').attr('x', x0).attr('y', -20 + k * 14).text(ln));
    });

    // Grid + axes
    g.append('g').attr('class', 'tl-grid')
      .selectAll('line').data(y.ticks(7)).join('line')
      .attr('x1', 0).attr('x2', innerW).attr('y1', v => y(v)).attr('y2', v => y(v));
    g.append('g').attr('class', 'tl-axis')
      .attr('transform', 'translate(0,' + innerH + ')')
      .call(d3.axisBottom(x).ticks(d3.utcYear.every(1)).tickFormat(d3.utcFormat('%Y')).tickSizeOuter(0));
    g.append('g').attr('class', 'tl-axis')
      .call(d3.axisLeft(y).ticks(7).tickFormat(d3.format('.1f')).tickSizeOuter(0));
    g.append('text').attr('class', 'tl-axis-title')
      .attr('transform', 'rotate(-90)')
      .attr('x', -innerH / 2).attr('y', -M.left + 12)
      .attr('text-anchor', 'middle').text('Avg correlation');

    // Series: raw + residual solid, balanced residual dashed (D6)
    const line = d3.line().defined(v => v != null).x((v, i) => x(dates[i])).y(v => y(v));
    const series = g.append('g');
    series.append('path').datum(d.avgSeries('raw'))
      .attr('class', 'tl-line').attr('stroke', COLORS.raw).attr('d', line);
    series.append('path').datum(d.avgSeries('residual'))
      .attr('class', 'tl-line').attr('stroke', COLORS.residual).attr('d', line);
    series.append('path').datum(d.balancedSeries('residual'))
      .attr('class', 'tl-line tl-balanced').attr('stroke', COLORS.residual).attr('d', line);

    // Entry markers (errata v3.1 dates)
    const entries = g.append('g');
    ENTRIES.forEach(e => {
      const ex = x(parseDate(e.end));
      entries.append('line').attr('class', 'tl-entry-line')
        .attr('x1', ex).attr('x2', ex).attr('y1', 0).attr('y2', innerH);
      entries.append('text').attr('class', 'tl-entry-label')
        .attr('x', ex).attr('y', innerH - 6 - e.row * 14)
        .attr('text-anchor', e.anchor).text(e.label);
    });

    // Selected-bank average line (S2), hidden until a bank is selected
    bankPath = series.append('path').attr('class', 'tl-line tl-bank').attr('fill', 'none');
    bankLabel = g.append('text').attr('class', 'tl-bank-label').attr('text-anchor', 'end');

    // Current-window marker
    markerLine = g.append('line').attr('class', 'tl-marker').attr('y1', 0).attr('y2', innerH);
    dotRaw = g.append('circle').attr('class', 'tl-dot').attr('r', 3.5).attr('fill', COLORS.raw);
    dotRes = g.append('circle').attr('class', 'tl-dot').attr('r', 3.5).attr('fill', COLORS.residual);

    // Pointer overlay: hover tooltip, click + drag to change window
    const overlay = g.append('rect')
      .attr('class', 'tl-overlay').attr('width', innerW).attr('height', innerH);
    overlay
      .on('pointermove', ev => {
        const i = nearestIndex(ev);
        if (dragging) state().set({ windowIndex: i }, 'timeline');
        showTip(ev, tipHTML(i, state().get()));
      })
      .on('pointerdown', ev => {
        dragging = true;
        overlay.node().setPointerCapture(ev.pointerId);
        state().set({ windowIndex: nearestIndex(ev) }, 'timeline');
      })
      .on('pointerup', ev => {
        dragging = false;
        overlay.node().releasePointerCapture(ev.pointerId);
      })
      // A cancelled pointer is already inactive: releasing capture would throw.
      .on('pointercancel', () => { dragging = false; hideTip(); })
      .on('pointerleave', () => { if (!dragging) hideTip(); });
  }

  function render(s) {
    if (!g) return;
    hideTip();   // marker/lines under the mouse may move; stale tooltip must not linger
    const d = data();
    const i = s.windowIndex;
    const mx = x(dates[i]);
    markerLine.attr('x1', mx).attr('x2', mx);
    dotRaw.attr('cx', mx).attr('cy', y(d.avgSeries('raw')[i]));
    dotRes.attr('cx', mx).attr('cy', y(d.avgSeries('residual')[i]));

    // S2: selected bank's average correlation in the current mode
    if (s.selectedBank) {
      const vals = d.bankAvgSeries(s.selectedBank, s.mode);
      const line = d3.line().defined(v => v != null).x((v, k) => x(dates[k])).y(v => y(v));
      bankPath.attr('stroke', COLORS[s.mode]).attr('d', line(vals)).style('display', null);
      const last = vals[vals.length - 1];
      if (last != null) {
        bankLabel.text(s.selectedBank)
          .attr('fill', COLORS[s.mode])
          .attr('x', x(dates[dates.length - 1]) - 2)
          .attr('y', y(last) - 5)
          .style('display', null);
      } else bankLabel.style('display', 'none');
    } else {
      bankPath.style('display', 'none');
      bankLabel.style('display', 'none');
    }
  }

  function init(el) {
    host = document.createElement('div');
    host.className = 'tl-chart';
    const jumps = document.createElement('div');
    jumps.className = 'tl-jumps';
    jumps.innerHTML = '<span class="muted">Jump to:</span>' + JUMPS.map((j, k) =>
      '<button type="button" data-jump="' + k + '" title="' + j.title + '">' + j.label + '</button>').join('');
    el.appendChild(jumps);
    el.appendChild(host);
    jumps.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        const j = JUMPS[+btn.dataset.jump];
        const idx = j.end ? ends.indexOf(j.end) : data().windowCount() - 1;
        if (idx >= 0) state().set({ windowIndex: idx }, 'timeline');
      });
    });
    build();
    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { build(); render(state().get()); }, 150);
    });
  }

  function update(s) { render(s); }

  return { init, update };
})();