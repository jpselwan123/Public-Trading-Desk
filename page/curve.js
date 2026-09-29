/* ---------------- the account against the S&P 500, week by week (history.curve) ---------------- */
// The line is history.curve's: the account rebuilt at each week's close, and what the same deposits
// would be worth in the S&P 500 on that day. Drawn here and worked out nowhere here; no colour is typed
// in this file (the styles name them), and the words, not a colour, say ahead or behind.
const CURVE_RANGES = [['3M', 91], ['1Y', 365], ['All', null]];     // what the range buttons show, in days
let curveRange = 'All', curveDrawn = false, curveAnimating = 0;                          // the line draws itself in once, and again on a new range; a refresh redraws it still
function curveStep(span, n){
  const raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}
function axisMoney(v, cur){
  try { return new Intl.NumberFormat(undefined, {style:'currency', currency:cur, notation:'compact', maximumFractionDigits:1}).format(v); }
  catch(e){ return String(Math.round(v)); }                       // a code Intl does not know: still only text
}
function curveFrom(C){
  const range = CURVE_RANGES.find(r => r[0] === curveRange), n = C.days.length;
  if (!range || !range[1]) return 0;
  const cut = new Date(C.days[n - 1] + 'T00:00:00Z'); cut.setUTCDate(cut.getUTCDate() - range[1]);
  const iso = cut.toISOString().slice(0, 10), i = C.days.findIndex(d => d >= iso);
  return i < 0 ? 0 : Math.min(i, n - 3);
}
function curveSpanDays(C){ return (Date.parse(C.days[C.days.length - 1]) - Date.parse(C.days[0])) / 864e5; }

function drawCurve(animate){
  // the first draw that finds room animates (the page draws before the Overview is on show, so that is often the resize's), and a
  // redraw to a new width in the first second carries the draw-in on
  animate = animate || !curveDrawn || performance.now() < curveAnimating;
  const C = (DATA.history || {}).curve, host = $('perfPlot');
  if (!host || !C || !C.days || C.days.length < 4 || !host.clientWidth) return;
  const W = Math.round(host.clientWidth), H = W < 520 ? 220 : 300, L = 6, R = 6, T = 14, B = 30, cur = C.currency || 'USD';
  const i0 = curveFrom(C), days = C.days.slice(i0), A = C.account.slice(i0), M = C.market.slice(i0), N = C.net.slice(i0);
  const t = days.map(d => Date.parse(d + 'T00:00:00Z')), t0 = t[0], t1 = t[t.length - 1];
  const all = A.concat(M.filter(v => v != null), N);
  let lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
  const step = curveStep((hi - lo) || hi || 1, 4);
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  if (hi <= lo) hi = lo + step;                                    // an account that was empty all along still has a scale
  const xs = t.map(v => L + (t1 === t0 ? 0 : (v - t0) / (t1 - t0)) * (W - L - R));
  const y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  const line = vals => vals.map((v, i) => v == null ? '' : ((i && vals[i - 1] != null ? 'L' : 'M') + xs[i].toFixed(1) + ',' + y(v).toFixed(1))).join('');
  const stepped = vals => vals.map((v, i) => (i ? 'H' + xs[i].toFixed(1) + 'V' : 'M' + xs[i].toFixed(1) + ',') + y(v).toFixed(1)).join('');
  const base = (H - B).toFixed(1);
  let grid = '';
  for (let v = lo; v <= hi + step / 1e6; v += step)
    grid += '<line class="grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '"/>' +
      (Math.abs(v) < step / 1e6 ? '' : '<text class="ax" x="' + (L + 2) + '" y="' + (y(v) - 5).toFixed(1) + '">' + esc(axisMoney(v, cur)) + '</text>');   // the line starts on zero: no label to sit on it
  const long = curveSpanDays({days}) > 400, ticks = W < 520 ? 3 : 5;
  let axis = '';
  for (let k = 0; k < ticks; k++){
    const i = Math.round(k * (days.length - 1) / (ticks - 1)), [yy, mm, dd] = days[i].split('-');
    const label = long ? MONTHS[+mm - 1] + ' ' + yy.slice(2) : (+dd) + ' ' + MONTHS[+mm - 1];
    axis += '<text class="ax" x="' + xs[i].toFixed(1) + '" y="' + (H - 8) + '" text-anchor="' + (k === 0 ? 'start' : k === ticks - 1 ? 'end' : 'middle') + '">' + esc(label) + '</text>';
  }
  const last = A.length - 1;
  const summary = 'Account value from ' + fmtDay(days[0]) + ' to ' + fmtDay(days[last]) + ': ' + money(A[0]) + ' to ' + money(A[last]) +
    (M[last] != null ? '; the same deposits in the S&P 500: ' + money(M[last]) : '') + '.';
  host.innerHTML = '<svg class="perf-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(summary) + '">' +
    '<defs><linearGradient id="perfFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="fill-a" stop-opacity=".30"/><stop offset="1" class="fill-a" stop-opacity="0"/></linearGradient></defs>' +
    grid + axis +
    '<path class="area" d="' + line(A) + 'L' + xs[last].toFixed(1) + ',' + base + 'L' + xs[0].toFixed(1) + ',' + base + 'Z"/>' +
    '<path class="line-n" d="' + stepped(N) + '"/>' +
    '<path class="line-m" d="' + line(M) + '"/>' +
    '<path class="line-a' + (animate ? ' draw' : '') + '" d="' + line(A) + '"/>' +
    '<g class="cursor" hidden><line class="cur-x" y1="' + T + '" y2="' + base + '"/><circle class="dot-m" r="4"/><circle class="dot-a" r="5"/></g>' +
    '<rect class="hit" x="0" y="0" width="' + W + '" height="' + H + '"/></svg><div class="perf-tip" hidden></div>';
  const svg = host.firstChild, tip = host.querySelector('.perf-tip'), cursor = svg.querySelector('.cursor');
  const path = svg.querySelector('.line-a.draw');
  if (path){ const len = path.getTotalLength(); path.style.setProperty('--len', len.toFixed(0)); }
  let at = last;
  const show = i => {
    at = Math.max(0, Math.min(last, i));
    cursor.hidden = false;
    const x = xs[at];
    svg.querySelector('.cur-x').setAttribute('x1', x); svg.querySelector('.cur-x').setAttribute('x2', x);
    const da = svg.querySelector('.dot-a'), dm = svg.querySelector('.dot-m');
    da.setAttribute('cx', x); da.setAttribute('cy', y(A[at]));
    dm.setAttribute('cx', x); dm.setAttribute('cy', M[at] == null ? -20 : y(M[at]));
    const diff = M[at] == null ? '' : '<div class="tip-s">' + money(Math.abs(A[at] - M[at])) + ' ' + (A[at] >= M[at] ? 'ahead of' : 'behind') + ' the S&amp;P 500</div>';
    tip.innerHTML = '<div class="tip-d">' + fmtDay(days[at]) + '</div>' +
      '<div class="tip-r"><span class="sw a"></span>You <b>' + money(A[at]) + '</b></div>' +
      (M[at] == null ? '' : '<div class="tip-r"><span class="sw m"></span>S&amp;P 500, same deposits <b>' + money(M[at]) + '</b></div>') +
      '<div class="tip-r"><span class="sw n"></span>Put in <b>' + money(N[at]) + '</b></div>' + diff;
    tip.hidden = false;
    const w = tip.offsetWidth;
    tip.style.left = Math.max(4, Math.min(W - w - 4, x - w / 2)) + 'px';
  };
  const near = ev => { const r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) * (W / r.width);
    let a = 0, b = xs.length - 1; while (b - a > 1){ const m = (a + b) >> 1; if (xs[m] < x) a = m; else b = m; }
    return Math.abs(xs[a] - x) <= Math.abs(xs[b] - x) ? a : b; };
  const hit = svg.querySelector('.hit');
  hit.addEventListener('pointermove', ev => show(near(ev)));
  hit.addEventListener('pointerdown', ev => show(near(ev)));
  hit.addEventListener('pointerleave', ev => { if (ev.pointerType === 'mouse'){ cursor.hidden = true; tip.hidden = true; } });
  host.onkeydown = ev => {
    if (ev.key === 'ArrowLeft'){ show((cursor.hidden ? last : at) - 1); ev.preventDefault(); }
    else if (ev.key === 'ArrowRight'){ show((cursor.hidden ? last : at) + 1); ev.preventDefault(); }
    else if (ev.key === 'Escape'){ cursor.hidden = true; tip.hidden = true; }
  };
  host.dataset.width = W;
  curveDrawn = true;
  if (animate && !(performance.now() < curveAnimating)) curveAnimating = performance.now() + 1100;
}

function renderPerformance(){
  const C = (DATA.history || {}).curve, box = $('perf');
  if (!box) return;
  const has = !!(DATA.connected && C && C.days && C.days.length > 3);
  box.hidden = !DATA.connected || !C || (!has && !C.why);            // a new account has too few weeks to draw, and nothing to say about it
  $('perfHead').hidden = $('perfPlot').hidden = !has;
  $('perfWhy').textContent = DATA.connected && C && C.why ? 'The account’s weekly line is not drawn: ' + sentence(C.why) : '';
  if (!has) return;
  const span = curveSpanDays(C);
  const ranges = CURVE_RANGES.filter(r => !r[1] || r[1] < span - 14);
  if (!ranges.some(r => r[0] === curveRange)) curveRange = 'All';
  $('perfRange').innerHTML = ranges.length > 1 ? ranges.map(r =>
    '<button type="button" data-range="' + r[0] + '" aria-pressed="' + (r[0] === curveRange) + '">' + r[0] + '</button>').join('') : '';
  const market = C.market.some(v => v != null);
  $('perfLegend').innerHTML = '<span class="lg"><span class="sw a"></span>You</span>' +
    (market ? '<span class="lg"><span class="sw m"></span>S&amp;P 500, same deposits</span>' : '') +
    '<span class="lg"><span class="sw n"></span>Put in</span>';
  drawCurve(!curveDrawn);
}
$('perfRange').addEventListener('click', ev => {
  const b = ev.target.closest('[data-range]');
  if (!b) return;
  curveRange = b.dataset.range;
  document.querySelectorAll('#perfRange [data-range]').forEach(x => x.setAttribute('aria-pressed', x === b));
  drawCurve(true);
});
if (window.ResizeObserver){
  let pending = 0;
  new ResizeObserver(() => { cancelAnimationFrame(pending); pending = requestAnimationFrame(() => {
    const host = $('perfPlot'); if (host && host.clientWidth && Math.abs(host.clientWidth - (+host.dataset.width || 0)) > 2) drawCurve(false); }); }).observe($('perfPlot'));
}
