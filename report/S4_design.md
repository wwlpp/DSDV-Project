# S4 — Interface design: three options and the chosen combination (DRAFT)

Status: draft for PR#3 (25/11/2026). Authors: Tín (Network) + Đạt (Matrix / Ranking /
Timeline / Layout). This draft covers Đạt's parts; Tín's Network evaluation and the
final hand sketches are due with the 30/11 freeze. Figures referenced below are in
`report/figures/` (p3a_*.png, captured 24/11/2026 at 1280/1366/1920 widths).

## 1. The three options considered

**Option A — force-directed network as the primary view.**
Nodes = banks, edges = correlations at or above the threshold; node colour = ownership
group; layout re-simulated per window. Reads topology (who is central, which clusters
form) at a glance and animates well during Play.

**Option B — correlation matrix as the primary view.**
19×19 heatmap, one shared diverging scale for both modes. Every pair is readable at
every window, including windows where the network is dense; exact values on hover and
in a pair panel.

**Option C — coordinated multiple views.**
Network, matrix, ranking and timeline visible together with linked selection
(one shared state: selected bank / pair / window). Strongest for cross-view tasks,
but needs the most screen area and the most implementation effort.

## 2. Trade-offs

| Criterion | A (network) | B (matrix) | C (all linked) |
|---|---|---|---|
| Topology / clusters at a glance | strong | weak (order-dependent) | strong |
| Read one exact pair value | weak (hover on thin edges) | strong | strong |
| Dense windows (many edges) | fails: hairball | unaffected | unaffected |
| Screen area at 1366×768 | small | medium | large (needs tabs) |
| Implementation cost | medium (Tín) | medium | high |
| Play animation readability | good | good (stable order needed) | mixed |

**Evidence for the dense-window failure of A:** at threshold 0.50 the raw edge count
ranges from **9 to 137** of 171 possible pairs across the 88 windows (re-verified on
`network_data.json`, 24/11/2026). Near 137 edges a force-directed drawing becomes a
hairball: individual edges and their values cannot be read. This is the concrete
reason a matrix is required even though a network exists.

## 3. Decision

**A as the main tab, B as the second tab, linking borrowed from C.**
Network stays the default tab (topology first impression); Matrix is the second tab
for exact pair reading; the shared-state linking of C (selected bank / pair / window
synchronised across Network, Matrix, Ranking, Timeline) is implemented without
showing all views at once, which keeps the 1366×768 layout usable. Tabs: Network,
Matrix, Analysis, About; the timeline and ranking stay visible outside the tabs so
window context and centrality context are never lost.

## 4. Rejected alternatives (with reasons)

- **Separate colour scale per mode** (raw YlOrRd, residual asymmetric diverging):
  the same colour would mean two different things across modes, and switching
  Raw → Residual would not visibly fade the matrix, hiding the Q2 message that much
  connectedness is market-wide. Replaced by one shared reversed-RdBu scale
  [−0.8, 0, 0.8], clamped, for both modes (D3).
- **Q1 as 19 overlapping line charts**: unreadable spaghetti and dependent on the
  threshold slider; replaced by a tier heatmap at default settings, reproducible
  from `centrality.json` (P3B).
- **Numeric ranking #1…#19**: top PageRank scores differ by <0.5 percentage points
  (VIB 9.03 vs CTG 9.02 at the last window), so ordinal ranks exaggerate noise.
  Replaced by D7 tiers (Core / Middle / Periphery / isolated) against the 1/N_active
  baseline; numeric rank only in tooltips.
- **Null cells as light grey**: on a diverging scale 0 is near-white, so light grey
  nulls would read as "correlation ≈ 0". Replaced by diagonal stripes (D3).

## 5. Encoding table (Đạt's views, plan §7)

| View | Mark | Channels | Scale / rule | Interaction |
|---|---|---|---|---|
| Ranking | table row + bar | position/length (PR), colour bar (group), tier label | PR 1 decimal; D7 tiers; nulls last | click/Enter selects; neighbours highlighted |
| Timeline | lines + bands + ticks | y position (avg corr), colour (mode), dash (balanced panel) | y fixed [0, 0.7] both modes | click/drag window; tooltip; jump buttons |
| Matrix | square cell | colour (reversed RdBu diverging) | shared [−0.8, 0, 0.8] clamp; stripes null; grey diagonal | hover value; cell click → pair panel; label click → bank |
| Pair panel | table + sparkline | position (88-window series) | sparkline y fixed [−0.4, 0.9] | click sparkline → window |

Selection is a 2px `#08306b` border only (never a fill change); bank labels use dark
text with a 4px ownership-colour bar for WCAG contrast (D4).

## 6. Scientific-safety design points

- Fixed banner states what the proxy does not imply; it is the only place those
  terms appear (wording audit V-14).
- Timeline annotations are descriptive and window-based: "windows ending May–Aug
  2022" for the residual peak, "Raw-only jump … (window ending 2025-04-18)" for 2025;
  entry markers at 2021-08-10 / 2021-11-04 / 2021-12-02 (errata v3.1).
- The dashed balanced 15-bank panel line separates sample-composition effects from
  co-movement changes when reading the 2021–2022 rise (D6). At the peak window
  2022-07-27: full-sample residual 0.3049 vs balanced 0.2931.
- Null banks are never zero: striped cells, N/A rows, excluded from means/PageRank.

## 7. Open items for the 30/11 final

- Tín: Network option evaluation, hairball screenshot at the 137-edge window,
  node-size/encoding rationale.
- Hand sketches of A/B/C (draft currently uses implemented-view screenshots).
- Internal-evaluation before/after figures (S6).