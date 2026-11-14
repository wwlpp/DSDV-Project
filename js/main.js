/* App shell: controls, tabs, view lifecycle. Views register as
 * DSDV.views.<name> = { init(el), update(state, changedKeys) } and decide
 * themselves whether to redraw when their tab is hidden. */
(function () {
  const $ = id => document.getElementById(id);
  const state = DSDV.state;
  const data = DSDV.data;
  const TABS = ['network', 'matrix', 'analysis', 'about'];
  const HOSTS = {
    network: 'view-network',
    matrix: 'view-matrix',
    analysis: 'view-analysis',
    timeline: 'view-timeline',
    ranking: 'view-ranking'
  };
  const PENDING = {
    network: ['Network view', 'js/network.js (Tín) plugs into this container through DSDV.views.network. The container and the init/update contract are ready; integration lands with PR#4.'],
    matrix: ['Matrix view', 'The 19×19 matrix with the shared diverging scale arrives in PR#3 (timeline + matrix).'],
    analysis: ['Analysis views', 'Q1 (tier heatmap), Q3 (ownership groups) and Q4 (sensitivity) arrive in PR#4.'],
    timeline: ['Timeline', 'Raw + residual lines, balanced 15-bank panel, entry markers and annotations arrive in PR#3.'],
    ranking: ['Ranking table', 'Tier-based ranking (Core / Middle / Periphery) arrives in PR#2.']
  };
  let playTimer = null;

  function initControls() {
    document.querySelectorAll('input[name="mode"]').forEach(r => {
      r.addEventListener('change', () => state.set({ mode: r.value }, 'control'));
    });
    $('match-edges').addEventListener('change', e =>
      state.set({ matchRawEdges: e.target.checked }, 'control'));
    $('window-slider').addEventListener('input', e =>
      state.set({ windowIndex: +e.target.value }, 'control'));
    $('threshold-slider').addEventListener('input', e =>
      state.set({ threshold: +e.target.value }, 'control'));
    $('play-btn').addEventListener('click', () =>
      state.set({ playing: !state.get().playing }, 'control'));
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') state.set({ selectedBank: null, selectedPair: null }, 'keyboard');
    });
  }

  function initTabs() {
    document.querySelectorAll('.tabs button').forEach(btn => {
      btn.addEventListener('click', () => state.set({ activeTab: btn.dataset.tab }, 'tabs'));
    });
  }

  function initViews() {
    for (const [name, hostId] of Object.entries(HOSTS)) {
      const el = $(hostId);
      const view = DSDV.views[name];
      if (view && typeof view.init === 'function') {
        view.init(el);
      } else {
        const [title, note] = PENDING[name];
        el.innerHTML = '<div class="view-pending"><b>' + title + '</b>' + note + '</div>';
      }
    }
  }

  function syncPlay(s) {
    const btn = $('play-btn');
    btn.setAttribute('aria-pressed', String(s.playing));
    btn.innerHTML = s.playing ? '&#10074;&#10074; Pause' : '&#9654; Play';
    if (s.playing && !playTimer) {
      playTimer = setInterval(() => {
        const cur = state.get();
        state.set({ windowIndex: (cur.windowIndex + 1) % data.windowCount() }, 'play');
      }, 500);
    } else if (!s.playing && playTimer) {
      clearInterval(playTimer);
      playTimer = null;
    }
  }

  function render(s, changed) {
    const w = data.window(s.windowIndex);
    const active = data.activeBanks(s.windowIndex);
    const er = data.edges(s.windowIndex, s);
    const sum = data.summaryAt(s.windowIndex);
    const auto = s.mode === 'residual' && s.matchRawEdges;

    $('window-slider').value = s.windowIndex;
    $('threshold-slider').value = s.threshold;
    $('match-edges').checked = s.matchRawEdges;
    document.querySelectorAll('input[name="mode"]').forEach(r => { r.checked = r.value === s.mode; });
    syncPlay(s);

    $('window-label').textContent = w.end;
    $('threshold-label').textContent = s.threshold.toFixed(2) + (auto ? ' (raw target)' : '');
    $('stat-active').textContent = active.length + '/' + data.bankIds().length;
    $('stat-edges').textContent = er.edges.length;
    $('stat-avg').textContent = sum ? sum[s.mode].toFixed(4) : '—';
    $('stat-residual-wrap').hidden = !auto;
    if (auto) {
      $('stat-residual-t').textContent =
        er.threshold.toFixed(3) + (er.floorHit ? ' (floor)' : ' (matched)');
    }
    const floorBadge = $('floor-badge');
    floorBadge.hidden = !er.floorHit;
    if (er.floorHit) {
      floorBadge.textContent = 'Residual network has fewer edges than raw (only ' +
        er.edges.length + ' pairs ≥ 0.05)';
    }

    $('ranking-badge').textContent = data.centrality()
      ? 'Source: centrality.json (verified)'
      : 'Computed in browser for threshold = ' + s.threshold.toFixed(2);

    for (const t of TABS) {
      $('tab-' + t).hidden = t !== s.activeTab;
      const btn = $('tabbtn-' + t);
      btn.classList.toggle('on', t === s.activeTab);
      btn.setAttribute('aria-selected', String(t === s.activeTab));
    }

    for (const name of Object.keys(HOSTS)) {
      const view = DSDV.views[name];
      if (view && typeof view.update === 'function') view.update(s, changed);
    }
  }

  async function boot() {
    try {
      await data.load();
    } catch (err) {
      const el = $('data-status');
      el.textContent = 'Data failed to load';
      el.classList.add('error');
      el.title = String(err && err.message || err);
      return;
    }
    $('data-status').textContent =
      data.windowCount() + ' windows · ' + data.bankIds().length + ' banks · data: ' + data.source();
    initControls();
    initTabs();
    initViews();
    state.on(render);
    render(state.get(), Object.keys(state.get()));
  }

  boot();
})();