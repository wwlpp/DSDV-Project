/* Shared view helpers: the single #tooltip node and the frozen D4 palette.
 * Views must not keep their own copies — these change together (plan v3 D4). */
window.DSDV = window.DSDV || {};

DSDV.ui = (function () {
  const COLORS = { raw: '#252525', residual: '#6a51a3' };
  const GROUP_COLORS = { state: '#d95f02', private: '#1b9e77' };

  function showTip(ev, html) {
    const t = document.getElementById('tooltip');
    t.style.display = 'block';
    t.innerHTML = html;
    t.style.left = (ev.clientX + 12) + 'px';
    t.style.top = (ev.clientY + 12) + 'px';
  }
  function hideTip() { document.getElementById('tooltip').style.display = 'none'; }

  return { COLORS, GROUP_COLORS, showTip, hideTip };
})();