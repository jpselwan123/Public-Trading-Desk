/* ---------------- the Chart tab: a line or candles for any US share or fund (charts.py) ---------------- */
// The bars are charts.py's: split-adjusted daily candles, or the session's IEX bars, each [time or day, open, high, low, close, volume].
// Drawn here and worked out nowhere here; no colour is typed in (the styles name them). A candle that closed above its open is hollow
// and one that closed below is filled: colour says what a number is, never whether it is good.
const PC_SLOT_MIN = 2.5;           // candles narrower than this (in pixels) are a smear: a line is drawn instead
let pcx = {ticker: null, range: null, kind: 'candles', data: null, at: 0, busy: false, hold: false, message: ''};

// The scale for what is drawn: tidy steps over the lowest low and highest high, a little room above and below.
function pcScale(values){
  let lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
  if (!(hi > lo)){ const pad = Math.abs(hi) * 0.01 || 1; lo -= pad; hi += pad; }
  const room = (hi - lo) * 0.04; lo -= room; hi += room;
  const step = curveStep(hi - lo, 4);
  return {lo: Math.floor(lo / step) * step, hi: Math.ceil(hi / step) * step, step};
}
function pcPrice(v, step){
  const dp = step >= 1 && step % 1 === 0 ? 0 : step >= 0.1 ? (step * 10) % 1 === 0 ? 1 : 2 : 2;
  return '$' + v.toLocaleString(undefined, {minimumFractionDigits: dp, maximumFractionDigits: dp});
}
// Where each bar sits: equal slots, so weekends and nights leave no gap.
function pcSlots(count, left, width){
  const slot = width / Math.max(1, count);
  return {slot, x: i => left + slot * (i + 0.5)};
}
function pcBody(slot){ return Math.max(1, Math.min(14, Math.floor(slot * 0.62))); }
function pcKindShown(kind, slot){ return kind === 'candles' && slot >= PC_SLOT_MIN ? 'candles' : 'line'; }

function pcDefault(){
  const rows = ((DATA.positions || {}).rows || []).filter(r => r.us_line);
  return (rows[0] && rows[0].ticker) || ((DATA.companies || [])[0] || {}).ticker || 'SPY';
}
function pcName(ticker){
  const card = (DATA.companies || []).find(c => c.ticker === ticker), row = ((DATA.positions || {}).rows || []).find(r => r.ticker === ticker);
  return (card && card.name) || (row && row.name) || '';
}
function pcChipTickers(){
  const held = ((DATA.positions || {}).rows || []).filter(r => r.us_line).map(r => r.ticker);
  const list = held.concat((DATA.companies || []).map(c => c.ticker), ['SPY']);
  return list.filter((t, i) => t && list.indexOf(t) === i).slice(0, 14);
}

function renderChart(){
  const box = $('pcx');
  if (!box) return;
  const past = !!DATA.as_of;
  box.hidden = past;
  if (past) return;
  const ch = DATA.chart || {};
  if (!ch.ranges || !ch.default){ $('pcPlot').innerHTML = '<div class="pc-empty">not recorded</div>'; return; }          // a page built before this tab
  if (!pcx.range) pcx.range = ch.default;
  if (!pcx.ticker) pcx.ticker = pcDefault();
  $('pcRange').innerHTML = ch.ranges.map(r => '<button type="button" data-range="' + esc(r) + '" aria-pressed="' + (r === pcx.range) + '">' + esc(r) + '</button>').join('');
  $('pcChips').innerHTML = pcChipTickers().map(t => '<button type="button" data-chart="' + esc(t) + '" aria-pressed="' + (t === pcx.ticker) + '">' + esc(t) + '</button>').join('');
  pcHeadDraw();
  if (pcx.data && pcx.data.ticker === pcx.ticker && pcx.data.range === pcx.range) pcDraw(false);
  else if (currentPage === 'chart' && !pcx.busy) pcLoad(false);
}

function pcHeadDraw(){
  const d = pcx.data, host = $('pcHead');
  $('pcTicker').placeholder = 'Ticker, like ' + (pcx.ticker || 'NVDA');
  if (!d || d.ticker !== pcx.ticker){
    host.innerHTML = '<div class="pc-name"><b>' + esc(pcx.ticker || '') + '</b>' + esc(pcName(pcx.ticker)) + '</div>';
    return;
  }
  const p = d.price || {};
  const when = p.at_label ? esc(p.session) + ' · ' + esc(p.at_label) : 'Last close · ' + esc(fmtDay(p.close_day));
  host.innerHTML = '<div class="pc-name"><b>' + esc(d.ticker) + '</b>' + esc(pcName(d.ticker)) + '</div>' +
    '<div class="pc-price"><span class="big">' + esc(pricePer(p.price, d.currency)) + '</span>' +
    (p.change == null ? '' : '<span class="pc-chg">' + pct1(p.change, true) + (p.at ? ' today' : ' on ' + esc(fmtDay(p.close_day))) + '</span>') + '</div>' +
    '<div class="pc-sub">' + when + (p.via ? (p.stream ? ' · live trade from ' : ' · via ') + esc(p.via) : '') +
    (d.live ? ((d.streaming || []).length ? ' · every trade as it comes' : d.every_seconds ? ' · updates every ' + pcAge(d.every_seconds) : '') : '') +
    (d.demo ? ' · demo prices' : '') + '</div>';
}
// a length of time as it is read: seconds under a minute and a half, else minutes
function pcAge(seconds){ return seconds < 90 ? Math.round(seconds) + ' s' : Math.round(seconds / 60) + ' min'; }

function pcNoteDraw(forcedLine){
  const d = pcx.data, feeds = d && d.feeds || [];
  const base = forcedLine ? 'Too many days for candles: drawn as a line.'
    : d && d.kind === 'intraday' ? 'New York time, regular session. ' + (d.consolidated ? 'Prices are the whole market’s, from Yahoo, which is unofficial.'
      : 'Prices are IEX’s, one exchange, so they can differ a little from the consolidated price.')
    : d ? 'Prices adjusted for splits. Volume in shares.' : '';
  const sources = feeds.length > 1 || (feeds.length && feeds[0].stream) ? ' Sources: ' + feeds.map(f => f.name + (f.stream ? ' stream ' : ' ') + pcAge(f.age)).join(' · ') + '.' : '';
  const differ = d && d.differ ? ' They disagree noticeably right now; the newest is shown.' : '';
  const problems = d && (d.problems || []).length ? ' ' + d.problems.join(' ') : '';
  $('pcNote').textContent = pcx.message ? pcx.message : base + sources + differ + problems;
}

async function pcLoad(silent){
  if (pcx.busy || !pcx.ticker) return;
  if (location.protocol === 'file:'){ pcx.message = 'Open the desk through its server to see charts.'; pcNoteDraw(); return; }
  const want = {ticker: pcx.ticker, range: pcx.range};
  pcx.busy = true;
  if (!silent){ pcx.message = 'Loading…'; pcNoteDraw(); }
  let res = null;
  try {
    const r = await fetch('/chart', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(want)});
    res = await r.json();
  } catch(e){ res = {ok: false, message: 'Could not reach the desk to draw it.'}; }
  pcx.busy = false;
  if (want.ticker !== pcx.ticker || want.range !== pcx.range) { pcLoad(false); return; }        // the owner moved on while it was coming
  if (res.ok){ pcx.data = res.chart; pcx.message = ''; pcx.at = Date.now(); }
  else { pcx.message = res.message || 'No chart.'; if (!silent) pcx.data = null; }
  pcHeadDraw();
  pcDraw(!silent);
}

function pcDraw(animate){
  const host = $('pcPlot'), d = pcx.data;
  $('pcKind').innerHTML = ['candles', 'line'].map(k => '<button type="button" data-kind="' + k + '" aria-pressed="' + (k === pcx.kind) + '">' + (k === 'candles' ? 'Candles' : 'Line') + '</button>').join('');
  if (!d || d.ticker !== pcx.ticker || d.range !== pcx.range || !d.bars || d.bars.length < 2){
    host.innerHTML = '<div class="pc-empty">' + esc(pcx.message || (pcx.busy ? 'Loading…' : 'Nothing to draw yet.')) + '</div>';
    pcNoteDraw();
    return;
  }
  if (!host.clientWidth) return;
  const W = Math.round(host.clientWidth), phone = W < 520, H = phone ? 300 : 400, L = phone ? 48 : 58, R = 6, T = 14, B = 26, VOL = phone ? 44 : 64, GAP = 10;   // the left room is for the prices
  const bars = d.bars, n = bars.length, bottom = H - B - VOL - GAP;
  const {slot, x} = pcSlots(n, L, W - L - R), kind = pcKindShown(pcx.kind, slot);
  const scale = pcScale(kind === 'candles' ? bars.map(b => b[3]).concat(bars.map(b => b[2])) : bars.map(b => b[4]));
  const {lo, hi, step} = scale;
  const y = v => T + (hi - v) / (hi - lo) * (bottom - T);
  const peak = Math.max.apply(null, bars.map(b => b[5])) || 1, vh = v => Math.max(v > 0 ? 1 : 0, v / peak * VOL);
  let grid = '';
  for (let v = lo; v <= hi + step / 1e6; v += step)
    grid += '<line class="grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '"/>' +
      '<text class="ax" x="' + (L - 8) + '" y="' + (y(v) + 4).toFixed(1) + '" text-anchor="end">' + esc(pcPrice(v, step)) + '</text>';
  const ticks = phone ? 3 : 5, long = d.kind === 'daily' && (Date.parse(bars[n - 1][0]) - Date.parse(bars[0][0])) / 864e5 > 400;
  const stamp = i => {
    if (d.kind === 'intraday') return d.labels[i];
    const [yy, mm, dd] = bars[i][0].split('-');
    return long ? MONTHS[+mm - 1] + ' ' + yy.slice(2) : (+dd) + ' ' + MONTHS[+mm - 1];
  };
  let axis = '';
  for (let k = 0; k < ticks; k++){
    const i = Math.round(k * (n - 1) / (ticks - 1));
    axis += '<text class="ax" x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="' + (k === 0 ? 'start' : k === ticks - 1 ? 'end' : 'middle') + '">' + esc(stamp(i)) + '</text>';
  }
  let marks = '';
  if (kind === 'candles'){
    const bw = pcBody(slot);
    let wicks = '', up = '', down = '';
    bars.forEach((b, i) => {
      const cx = x(i), top2 = y(Math.max(b[1], b[4])), h = Math.max(1, Math.abs(y(b[1]) - y(b[4])));
      wicks += 'M' + cx.toFixed(1) + ',' + y(b[2]).toFixed(1) + 'V' + y(b[3]).toFixed(1);
      const rect = 'M' + (cx - bw / 2).toFixed(1) + ',' + top2.toFixed(1) + 'h' + bw + 'v' + h.toFixed(1) + 'h' + (-bw) + 'z';
      if (b[4] >= b[1]) up += rect; else down += rect;
    });
    marks = '<path class="wick" d="' + wicks + '"/><path class="body-up" d="' + up + '"/><path class="body-down" d="' + down + '"/>';
  } else {
    const path = bars.map((b, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(b[4]).toFixed(1)).join('');
    marks = '<path class="area" d="' + path + 'L' + x(n - 1).toFixed(1) + ',' + bottom + 'L' + x(0).toFixed(1) + ',' + bottom + 'Z"/><path class="line-a" d="' + path + '"/>';
  }
  const volumes = bars.map((b, i) => '<rect class="vol" x="' + (x(i) - Math.max(0.5, slot * 0.35)).toFixed(1) + '" y="' + (H - B - vh(b[5])).toFixed(1) +
    '" width="' + Math.max(1, slot * 0.7).toFixed(1) + '" height="' + vh(b[5]).toFixed(1) + '"/>').join('');
  const prev = d.kind === 'intraday' && d.range === '1D' && d.price && d.price.previous_close != null && d.price.previous_close > lo && d.price.previous_close < hi
    ? '<line class="prev" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(d.price.previous_close).toFixed(1) + '" y2="' + y(d.price.previous_close).toFixed(1) + '"/>' : '';
  const summary = d.ticker + ', ' + d.range + ': from ' + pricePer(bars[0][4], d.currency) + ' to ' + pricePer(bars[n - 1][4], d.currency) + '.';
  host.innerHTML = '<svg class="pc-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(summary) + '">' +
    '<defs><linearGradient id="pcFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="fill-a" stop-opacity=".28"/><stop offset="1" class="fill-a" stop-opacity="0"/></linearGradient></defs>' +
    grid + axis + volumes + prev + marks +
    '<g class="cursor" hidden><line class="cur-x" y1="' + T + '" y2="' + (H - B) + '"/><circle class="dot-a" r="4.5"/></g>' +
    '<rect class="hit" x="0" y="0" width="' + W + '" height="' + H + '"/></svg><div class="pc-tip" hidden></div>';
  pcNoteDraw(pcx.kind === 'candles' && kind === 'line');
  const svg = host.firstChild, tip = host.querySelector('.pc-tip'), cursor = svg.querySelector('.cursor');
  let at = n - 1;
  const show = i => {
    at = Math.max(0, Math.min(n - 1, i));
    const b = bars[at], cx = x(at), before = at ? bars[at - 1][4] : null;
    cursor.hidden = false;
    svg.querySelector('.cur-x').setAttribute('x1', cx); svg.querySelector('.cur-x').setAttribute('x2', cx);
    const dot = svg.querySelector('.dot-a');
    dot.setAttribute('cx', cx); dot.setAttribute('cy', y(b[4])); dot.style.display = kind === 'line' ? '' : 'none';
    const when = d.kind === 'intraday' ? d.labels[at] : fmtDay(b[0]);
    const row = (k, v) => '<div class="tip-r">' + k + '<b>' + v + '</b></div>';
    tip.innerHTML = '<div class="tip-d">' + esc(when) + '</div>' +
      (kind === 'candles' ? row('Open', esc(pricePer(b[1], d.currency))) + row('High', esc(pricePer(b[2], d.currency))) + row('Low', esc(pricePer(b[3], d.currency))) : '') +
      row('Close', esc(pricePer(b[4], d.currency))) +
      (before ? row(d.kind === 'daily' ? 'From the day before' : 'From the bar before', pct1(b[4] / before - 1, true)) : '') +
      row('Volume', b[5].toLocaleString());
    tip.hidden = false;
    const w = tip.offsetWidth;
    tip.style.left = Math.max(4, Math.min(W - w - 4, cx - w / 2)) + 'px';
  };
  const near = ev => { const r = svg.getBoundingClientRect(); return Math.round(((ev.clientX - r.left) * (W / r.width) - L) / slot - 0.5); };
  const hit = svg.querySelector('.hit');
  hit.addEventListener('pointermove', ev => { pcx.hold = true; show(near(ev)); });
  hit.addEventListener('pointerdown', ev => { pcx.hold = true; show(near(ev)); });
  hit.addEventListener('pointerleave', ev => { if (ev.pointerType === 'mouse'){ pcx.hold = false; cursor.hidden = true; tip.hidden = true; } });
  host.onkeydown = ev => {
    if (ev.key === 'ArrowLeft'){ pcx.hold = true; show((cursor.hidden ? n - 1 : at) - 1); ev.preventDefault(); }
    else if (ev.key === 'ArrowRight'){ pcx.hold = true; show((cursor.hidden ? n - 1 : at) + 1); ev.preventDefault(); }
    else if (ev.key === 'Escape'){ pcx.hold = false; cursor.hidden = true; tip.hidden = true; }
  };
  host.dataset.width = W;
}

function pcShow(ticker){
  pcx.ticker = String(ticker || '').trim().toUpperCase();
  pcx.data = null; pcx.message = '';
  renderChart();
  pcLoad(false);
}
function openChart(ticker){ pcShow(ticker); showPage('chart'); }
$('pcForm').addEventListener('submit', ev => {
  ev.preventDefault();
  const t = $('pcTicker').value.trim();
  if (t){ $('pcTicker').value = ''; pcShow(t); }
});
document.addEventListener('click', ev => {
  const chip = ev.target.closest('[data-chart]');
  if (chip){ ev.preventDefault(); openChart(chip.dataset.chart); return; }
  const range = ev.target.closest('#pcRange [data-range]');
  if (range){ pcx.range = range.dataset.range; pcx.data = null; pcx.message = ''; renderChart(); pcLoad(false); return; }
  const kind = ev.target.closest('#pcKind [data-kind]');
  if (kind){ pcx.kind = kind.dataset.kind; pcDraw(false); }
});
document.addEventListener('pointerdown', ev => { if (!ev.target.closest('#pcPlot')) pcx.hold = false; });          // a touch elsewhere lets a live chart carry on
$('pcAsk').addEventListener('click', () => { if (typeof openChat === 'function') openChat({ticker: pcx.ticker, range: pcx.range}); });
if (window.ResizeObserver){
  let pending = 0;
  new ResizeObserver(() => { cancelAnimationFrame(pending); pending = requestAnimationFrame(() => {
    const host = $('pcPlot'); if (host && host.clientWidth && Math.abs(host.clientWidth - (+host.dataset.width || 0)) > 2) pcDraw(false); }); }).observe($('pcPlot'));
}
// the page's timer asks here every second: a live chart on show asks again as often as its own answer says (charts.py: every_seconds,
// once a second while a trade stream feeds it, every few with a fast feed, slower with Tiingo alone), a second short for the timer's
// slack, while a session is on
function chartTick(){
  const d = pcx.data;
  if (currentPage !== 'chart' || document.hidden || pcx.busy || pcx.hold || !d || !d.live || !d.every_seconds || DATA.as_of || DATA.demo) return;
  if (Date.now() - pcx.at >= d.every_seconds * 1000 - 1000) pcLoad(true);
}
