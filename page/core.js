const DATA_INITIAL = __DATA__;
let DATA = DATA_INITIAL;
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// a link from the stores: a web address only, escaped. Anything else (javascript:, data:) is no link.
const link = u => /^https?:\/\//i.test(String(u == null ? '' : u)) ? esc(u) : '#';
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

/* The broker the account comes from, as broker.py names it (Trading 212 unless .env names another). */
function brokerName(){ return (DATA.broker || {}).name || 'your broker'; }
/* A connect step as broker.py writes it: plain words, `a name` set as code. */
function stepText(text){ return esc(text).replace(/`([^`]+)`/g, '<code>$1</code>'); }

/* ---------------- formatting ---------------- */
function money(v, opts){
  opts = opts || {};
  const cur = (DATA.account && DATA.account.currency) || 'USD';
  const abs = Math.abs(v || 0);
  let s;
  try { s = new Intl.NumberFormat(undefined, {style:'currency', currency:cur, minimumFractionDigits:opts.dp==null?2:opts.dp, maximumFractionDigits:opts.dp==null?2:opts.dp}).format(abs); }
  catch(e){ s = abs.toFixed(2) + ' ' + cur; }
  if (opts.sign) return (v > 0.004 ? '+' : v < -0.004 ? '−' : '') + s;
  return (v < -0.004 ? '−' : '') + s;
}
function priceIn(v, cur){
  try { return new Intl.NumberFormat(undefined, {style:'currency', currency:cur || 'USD', maximumFractionDigits: v < 1 ? 4 : 2}).format(v || 0); }
  catch(e){ return (v || 0).toFixed(2) + ' ' + (cur || ''); }
}
/* A share's price in its own currency; a London line's pence (GBX) as pence, which Intl does not know. */
function pricePer(v, cur){
  if (v == null || !isFinite(v)) return '–';
  if (cur === 'GBX') return v.toLocaleString(undefined, {maximumFractionDigits: 2}) + 'p';
  return cur ? priceIn(v, cur) : v.toFixed(2);
}
function pct(v){ return v == null || !isFinite(v) ? '–' : (v < 0 ? '−' : '') + (Math.abs(v) * 100).toFixed(Math.abs(v) < 0.1 ? 1 : 0) + '%'; }
function pct1(v, sign){
  if (v == null || !isFinite(v)) return '–';
  const s = (Math.abs(v) * 100).toFixed(1) + '%';
  return (sign ? (v > 0.0005 ? '+' : v < -0.0005 ? '−' : '') : (v < 0 ? '−' : '')) + s;
}
function qty(v){ return (+v).toLocaleString(undefined, {maximumFractionDigits: v % 1 ? 4 : 0}); }
function fmtDay(d){
  if (!d) return '–';
  const [y, m, dd] = d.split('-');
  return (+dd) + ' ' + MONTHS[+m - 1] + ' ' + y.slice(2);
}
function fmtStamp(iso, done){
  if (!iso) return 'not synced yet';
  return (done == null ? 'synced ' : done ? done + ' ' : '') +
    new Date(iso).toLocaleString(undefined, {day:'numeric', month:'short', hour:'numeric', minute:'2-digit'});
}
function held(days){
  if (days == null) return '–';
  if (days < 1) return 'today';
  if (days < 60) return days + (days === 1 ? ' day' : ' days');
  if (days < 730) return Math.round(days / 30.44) + ' months';
  return (days / 365.25).toFixed(1) + ' years';
}
/* ---------------- measures ----------------
   How a measure looks is declared once, by the module that owns it — screen.py's
   MEASURE_DISPLAY and value.py's VALUE_DISPLAY — and arrives in DATA.measure_display.
   formatMeasure is the only reader; no page decides a measure's format or its label.
   screen.format_with is the command line's twin, and a test runs both on the same
   inputs (J-04). Everything between the markers is extracted by that test. */
/* formatMeasure:begin */
const MINUS = '\u2212';
function scaledFigure(a){
  if (a >= 1e12) return (a / 1e12).toFixed(2) + 'tn';
  if (a >= 1e9) return (a / 1e9).toFixed(1) + 'bn';
  if (a >= 1e6) return (a / 1e6).toFixed(0) + 'm';
  return a.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}
function formatWith(spec, v){
  if (v == null || !isFinite(v)) return '–';
  if (!spec) return String(v);
  const kind = spec.kind, a = Math.abs(v), neg = v < 0;
  if (kind === 'flag') return v ? 'yes' : 'no';
  if (kind === 'percent' || kind === 'ratio'){
    const x = kind === 'percent' ? a * 100 : a;
    let t = x.toFixed(spec.dp != null ? spec.dp : (kind === 'percent' ? 1 : 2));
    if (x > 0 && Number(t) === 0) t = x.toFixed(Math.min(6, 1 - Math.floor(Math.log10(x))));
    const sign = neg && Number(t) !== 0 ? MINUS : (spec.signed && v > 0 ? '+' : '');
    return sign + t + (kind === 'percent' ? '%' : '');
  }
  if (kind === 'money' || kind === 'count') return (neg ? MINUS : '') + (kind === 'money' ? '$' : '') + scaledFigure(a);
  if (kind === 'per_share') return (neg ? MINUS : '') + '$' + a.toFixed(2);
  return String(v);
}
function formatMeasure(name, v){ return formatWith((DATA.measure_display || {})[name], v); }
function measureLabel(name){ const m = (DATA.measure_display || {})[name]; return m ? m.label : name; }
/* formatMeasure:end */

/* A blank figure carries its reason where the dash is, from the module that left it
   blank — a dash alone reads as missing data (Q2). */
/* A dash with its reason (Q2). Coloured as withheld only when the owning module says
   the desk declined the figure; a figure the company never filed stays plain. */
function withReason(text, why, name, withheld){
  const reason = why && why[name];
  if (!reason || text !== '–') return text;
  const held = (withheld || []).indexOf(name) >= 0;
  return '<span' + (held ? ' class="withheld"' : '') + '>–</span><div class="dash-why' + (held ? ' withheld' : '') + '">' + esc(reason) + '</div>';
}

/* ---------------- the interval (Phase 5) ----------------
   One component for every count or median the page reads as evidence. Each `iv` comes
   from uncertainty.py with everything the drawing needs — the interval, the estimate,
   the value chance would give (`expected`, when there is one) and whether the interval
   is a finding (`reads`) — so the page decides none of it. The interval is the mark,
   the estimate a tick inside it, chance a reference line. */
function intervalBar(iv, lo, hi){
  if (!iv || iv.low == null || iv.high == null || !(hi > lo)) return '';
  const W = 64, H = 12, x = v => (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * W;
  const a = x(iv.low), b = x(iv.high);
  return '<svg class="ivbar ' + ({measured: 'measured', bounded: 'bounded'}[iv.reads] || 'uncertain') + '" width="' + W + '" height="' + H +
      '" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true">' +
    '<rect class="iv-axis" x="0" y="5.5" width="' + W + '" height="1"/>' +
    '<rect class="iv-span" x="' + a.toFixed(1) + '" y="3" width="' + Math.max(2, b - a).toFixed(1) + '" height="6" rx="3"/>' +
    (iv.expected != null ? '<rect class="iv-null" x="' + (x(iv.expected) - 0.5).toFixed(1) + '" y="0" width="1" height="' + H + '"/>' : '') +
    '<rect class="iv-est" x="' + (x(iv.estimate) - 1).toFixed(1) + '" y="1" width="2" height="10" rx="1"/>' +
  '</svg>';
}
function rangeText(iv, show){
  return iv.low == null ? 'too few to put a range on'
    : iv.level + ' range ' + show(iv.low) + ' to ' + show(iv.high);
}
/* "7 of 29", drawn and written with its interval: a count read as a rate never
   appears without one (test_no_page_reports_a_proportion_without_its_interval). */
function ofCount(p){
  if (!p) return '–';
  return '<span class="ivn"><b>' + p.k + ' of ' + p.n + '</b>' + intervalBar(p, 0, 1) + '</span><span class="iv-txt">' +
    rangeText(p, v => formatMeasure('share', v)) + '</span>';
}
/* What the interval says about chance, from uncertainty.py's own verdict. */
function chanceText(p){
  if (!p) return '';
  if (p.expected == null) return p.reads === 'uncertain' ? 'Too few to establish a rate.' : '';
  const about = 'Chance alone would give about ' + Math.round(p.expected_count) + '. ';
  if (!p.distinguishable) return about + 'This cannot be told from luck.';
  return about + (p.estimate < p.expected ? 'This is a real shortfall, not noise.' : 'This is more than luck would give.');
}
/* A median move's interval, on an axis centred on no move. */
function moveBar(m){
  const s = Math.max(Math.abs(m.low || 0), Math.abs(m.high || 0), Math.abs(m.estimate || 0));
  return intervalBar(m, -s, s);
}
function medianMove(m, show){
  if (!m) return '–';
  /* no range, so no bar to set the text apart: it read "−2.2%too few…" (S-32) */
  if (m.low == null) return '<b>' + show(m.estimate) + '</b> <span class="iv-txt">(' + rangeText(m, show) + ')</span>';
  return '<span class="ivn"><b>' + show(m.estimate) + '</b>' + moveBar(m) + '</span><span class="iv-txt">' + rangeText(m, show) + '</span>';
}

/* ---------------- the bridge (Phase 7) ----------------
   What changed between the last two annual reports, from bridge.py: one line on the
   card, the four blocks on click. Every figure formats from its declaration and every
   blank carries bridge.py's reason; the page computes nothing. */
function bridgeBlock(b){
  if (!b) return '';
  const title = 'What changed in the last year' +
    (b.years && b.years.length === 2 ? ' <span class="faint">' + esc(b.years[0]) + ' → ' + esc(b.years[1]) + '</span>' : '');
  if (b.why_not) return foldOpen(title, 'not available') + '<div class="co-note faint">' + esc(sentence(b.why_not)) + '</div></details>';
  const F = formatMeasure, r = b.revenue || {}, cash = b.cash || {}, debt = b.debt || {};
  const val = (block, name, v) => v == null ? withReason('–', block.why, name, block.withheld) : F(name, v);
  const pair = (name, before, now) => F(name, before) + ' → ' + F(name, now);
  const row = (label, value) => '<div class="br-row"><span>' + label + '</span><span class="num">' + value + '</span></div>';
  const op = (b.margins || []).find(m => m.name === 'operating_margin') || {};
  const summary = [
    r.growth != null ? 'revenue ' + F('revenue_growth', r.growth) : '',
    op.change_bp != null ? 'operating margin ' + F('margin_change_bp', op.change_bp) + ' bp' : '',
    cash.cash_conversion != null ? 'cash conversion ' + F('cash_conversion', cash.cash_conversion) : '',
  ].filter(Boolean).join(' · ');
  return foldOpen(title, summary) +
    '<div class="br-block"><div class="br-h">Revenue</div>' +
      row(measureLabel('revenue'), pair('revenue', r.before, r.now)) +
      row(measureLabel('revenue_change'), F('revenue_change', r.change) + (r.growth != null ? ' (' + F('revenue_growth', r.growth) + ')' : '')) +
      '<div class="co-note faint br-note">' + esc(r.segments || '') + '</div></div>' +
    '<div class="br-block"><div class="br-h">Where the margin moved</div>' +
      '<div class="br-walk br-head"><span></span><span class="num">' + esc(b.years ? b.years[0] : '') + '</span><span class="num">' +
        esc(b.years ? b.years[1] : '') + '</span><span class="num">' + measureLabel('margin_change_bp') + '</span></div>' +
      (b.margins || []).map(m => '<div class="br-walk"><span>' + measureLabel(m.name) +
        (m.why ? '<div class="dash-why">' + esc(m.why) + '</div>' : '') + '</span><span class="num">' + F(m.name, m.before) +
        '</span><span class="num">' + F(m.name, m.now) + '</span><span class="num">' + F('margin_change_bp', m.change_bp) + '</span></div>').join('') + '</div>' +
    '<div class="br-block"><div class="br-h">From profit to cash</div>' +
      row(measureLabel('net_income'), val(cash, 'net_income', cash.net_income)) +
      (cash.lines || []).map(l => row('+ ' + measureLabel(l.name) +
        (l.name === 'depreciation' && cash.depreciation_basis === 'summed' ? ' <span class="faint">(the notes&rsquo; two figures, summed)</span>' : ''),
        val(cash, l.name, l.value))).join('') +
      row('= ' + measureLabel('operating_cash_flow'), val(cash, 'operating_cash_flow', cash.operating_cash_flow)) +
      row(measureLabel('cash_conversion'), val(cash, 'cash_conversion', cash.cash_conversion) +
        (cash.cash_conversion_before != null ? ' <span class="faint">(' + F('cash_conversion', cash.cash_conversion_before) + ' a year before)</span>' : '')) + '</div>' +
    '<div class="br-block"><div class="br-h">Debt</div>' +
      row(measureLabel('debt'), debt.debt_before != null && debt.debt != null ? pair('debt', debt.debt_before, debt.debt) : val(debt, 'debt', debt.debt)) +
      (debt.maturing != null
        /* every year of the table, a missing one with its reason: dropping it read as
           "nothing due in year two" (S-23) */
        ? (debt.maturities || []).map(m => row('Falls due ' + esc(m.when),
            m.amount != null ? F('maturing', m.amount) : withReason('–', debt.why, m.name, debt.withheld))).join('')
        : row(measureLabel('maturing'), val(debt, 'maturing', null))) +
      row(measureLabel('interest_coverage'), val(debt, 'interest_coverage', debt.interest_coverage) +
        (debt.interest_coverage_before != null ? ' <span class="faint">(' + F('interest_coverage', debt.interest_coverage_before) + ' a year before)</span>' : '')) + '</div>' +
  '</details>';
}

/* ---------------- as of a past day (Phase 11) ----------------
   The desk rebuilt from what was known at the end of a past day (asof.py, on the
   server). The page only fetches it and shows it; nothing can be changed from it. */
function renderAsOf(){
  const day = DATA.as_of, today = DATA_INITIAL.today;
  document.body.classList.toggle('as-of', !!day);
  const pick = $('asofDate');
  if (pick){
    if (today){ const t = new Date(today + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() - 1); pick.max = t.toISOString().slice(0, 10); }
    pick.value = day || '';
  }
  $('asofBanner').hidden = !day;
  $('asofBanner').innerHTML = day
    ? 'Showing the desk as it was at the end of <b>' + fmtDay(day) + '</b>: only what was known by then. A figure not yet known reads &ndash;, ' +
      'and the account&rsquo;s balances are only kept as of the latest sync. Nothing can be changed from this view. ' +
      '<button class="linkish" id="asofBack">Back to today</button>'
    : '';
}
async function showAsOf(day){
  if (!day) return backToToday();
  $('msg').textContent = 'Rebuilding the desk as of ' + fmtDay(day) + '…';
  try {
    const r = await fetch('/asof?date=' + encodeURIComponent(day));
    const res = await r.json();
    if (!r.ok) throw new Error(res.message || res.error || 'Could not show that day');
    DATA = res;
    $('msg').textContent = '';
    renderAll();
    window.scrollTo(0, 0);
  } catch(err){ $('msg').textContent = err.message; }
}
async function backToToday(){
  try { const r = await fetch('/data'); if (r.ok) DATA = await r.json(); else DATA = DATA_INITIAL; }
  catch(e){ DATA = DATA_INITIAL; }
  renderAll();
}
$('asofDate').addEventListener('change', e => showAsOf(e.target.value));
/* each journal trade opens the desk as it looked the day it was made */
document.addEventListener('click', e => { const b = e.target.closest('[data-asof]'); if (b) showAsOf(b.dataset.asof); });
$('asofBanner').addEventListener('click', e => { if (e.target.id === 'asofBack') backToToday(); });

/* ---------------- the annual report's wording (Phase 10) ----------------
   From diffs.py: passages added and removed in Items 1A and 7 against the year
   before, longest first. Shown, never interpreted. */
const WORDING_SHOWN = 5;
function passageList(list, sign, key){
  if (!list.length) return '<div class="faint" style="font-size:13.5px">None.</div>';
  return list.map((p, i) => '<div class="wd-p' + (i >= WORDING_SHOWN ? ' wd-more' : '') + '" data-wd="' + key + '">' +
      '<span class="wd-text" title="Click to read it all"><span class="wd-sign">' + sign + '</span>' + esc(p) + '</span></div>').join('') +
    (list.length > WORDING_SHOWN ? '<button class="linkish" data-wd-all="' + key + '">Show all ' + list.length + '</button>' : '');
}
function wordingBlock(w){
  if (!w) return '';
  const title = 'Changes in the annual report&rsquo;s wording' +
    (w.old && w.new ? ' <span class="faint">' + fmtDay(w.old.date) + ' → ' + fmtDay(w.new.date) + '</span>' : '');
  if (w.why_not) return foldOpen(title, 'not available') + '<div class="co-note faint">' + esc(sentence(w.why_not)) + '</div></details>';
  const parts = Object.entries(w.sections || {});
  /* not a rate: counts of passages in one pair of documents, a census of the text */
  const summary = parts.map(([, s]) => esc(s.label) + ': ' + (s.why_not ? 'not found' : s.added.length + ' added, ' + s.removed.length + ' removed')).join(' · ');
  return foldOpen(title, summary) +
    parts.map(([key, s]) => '<div class="br-block"><div class="br-h">' + esc(s.label) + '</div>' +
      (s.why_not ? '<div class="co-note faint">' + esc(sentence(s.why_not)) + '</div>'
        /* not a rate: sentences carried over between two documents, counted in full */
        : '<div class="co-note faint br-note">' + s.sentences_before + ' sentences before, ' + s.sentences_now + ' now; ' +
          s.kept + ' carried over unchanged.</div>' +
          '<div class="wd-h">Added, longest first</div>' + passageList(s.added, '+', key + '-a') +
          '<div class="wd-h">Removed, longest first</div>' + passageList(s.removed, '−', key + '-r')) + '</div>').join('') +
    '</details>';
}

/* ---------------- theses (Phase 9) ----------------
   Written once, before the results, on thesis.py's rules; scored when the quarter is
   filed. The page shows and posts; every rule and every number is thesis.py's. */
function thesisWords(t){
  return 'revenue ' + esc(t.revenue_direction) + (t.revenue_change != null ? ' (about ' + formatMeasure('revenue_growth', t.revenue_change) + ')' : '') +
    ' and operating margin ' + esc(t.margin_direction) + ' on the same quarter a year before · ' +
    formatMeasure('confidence', t.confidence) + ' sure · &ldquo;' + esc(t.reason) + '&rdquo;';
}
function thesisBlock(ticker){
  const th = ((DATA.theses || {}).companies || {})[ticker];
  /* a past day's view is read-only: only a thesis written by then is shown, never the button */
  if (!th || (DATA.as_of && !th.pending)) return '';
  const body = th.pending
    ? '<div class="co-note">Written ' + fmtDay(th.pending.written) + ': ' + thesisWords(th.pending) +
      '. Scored when the quarter after ' + fmtDay(th.pending.after) + ' is filed.</div>'
    : th.can_write
      ? '<button class="btn" data-thesis="' + esc(ticker) + '">Write a thesis before the results</button>' +
        (th.due ? ' <span class="faint" style="font-size:13.5px">results due ' + fmtDay(th.due) + '</span>' : '')
      /* the reason is thesis.py's own fragment, framed as its refusal words it (S-25) */
      : '<div class="co-note faint">' + (th.why_not ? 'No thesis can be written now: ' + esc(th.why_not) + '.'
          : 'A thesis for this quarter is already written.') + '</div>';
  return foldOpen('Your forecast for the next results',
    th.pending ? 'written ' + fmtDay(th.pending.written) : th.can_write ? 'you can write one now' : 'not open now') +
    body + '</details>';
}
function openThesis(ticker){
  const th = ((DATA.theses || {}).companies || {})[ticker] || {}, range = (DATA.theses || {}).confidence_range || [];
  $('thTitle').textContent = 'Thesis: ' + ticker;
  $('thWhat').textContent = 'The quarter after ' + fmtDay(th.after) + (th.due ? ', due ' + fmtDay(th.due) : '') +
    '. Written once: it cannot be edited or deleted, and it is scored when that quarter is filed.';
  $('thesisForm').dataset.ticker = ticker;
  ['thRev', 'thMargin'].forEach(id => { $(id).value = ''; });
  ['thSize', 'thWhy', 'thConf'].forEach(id => { $(id).value = ''; });
  /* the range is thesis.py's, shown where it is typed; no step of the page's own (S-28:
     a step of 5 refused a 67 that thesis.py accepts) */
  $('thConf').min = Math.round(range[0] * 100); $('thConf').max = Math.round(range[1] * 100); $('thConf').step = 1;
  $('thConf').placeholder = Math.round(range[0] * 100) + ' to ' + Math.round(range[1] * 100);
  $('thMsg').textContent = '';
  $('thesisDlg').showModal();
}
$('thesisForm').addEventListener('submit', async e => {
  if (e.submitter && e.submitter.value === 'cancel') return;
  e.preventDefault();
  $('thMsg').textContent = 'Saving…';
  try {
    const r = await fetch('/thesis', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
      ticker: $('thesisForm').dataset.ticker, revenue_direction: $('thRev').value, revenue_change_pct: $('thSize').value,
      margin_direction: $('thMargin').value, reason: $('thWhy').value, confidence_pct: $('thConf').value})});
    const res = await r.json();
    if (!res.ok) throw new Error(res.message || 'Could not save');
    DATA.theses = res.theses || DATA.theses;
    $('thesisDlg').close();
    safe(renderCompanies); safe(renderTheses);
  } catch(err){ $('thMsg').textContent = err.message; }
});
function renderTheses(){
  const T = DATA.theses || {}, resolved = T.resolved || [];
  $('thSub').textContent = T.scored ? T.scored + ' scored' : '';
  // the card shows once a thesis has been scored: writing one is the user's choice, never asked
  $('thList').closest('.card').hidden = !resolved.length;
  if (!resolved.length) return;
  const bands = (T.calibration || []).map(b =>
    '<div class="th-row"><span class="th-said">Said about ' + formatMeasure('confidence', b.said) + ':</span> right in ' + ofCount(b.right) + '. ' +
    (b.right.distinguishable ? (b.right.estimate < b.said ? 'Over-confident here.' : 'Under-confident here.')
                             : 'Cannot be told apart from what you said.') + '</div>').join('');
  $('thList').innerHTML =
    '<div class="verdict">Brier score <b>' + formatMeasure('brier', T.brier) + '</b> over ' + T.scored +
      ' scored ' + (T.scored === 1 ? 'thesis' : 'theses') + ' — 0 is perfect, and saying 50% every time scores ' +
      formatMeasure('brier', T.always_half) + ' (Brier, 1950).</div>' + bands +
    resolved.map(t => '<div class="th-row"><span class="tk">' + esc(t.ticker) + '</span> ' + fmtDay(t.written) + ': ' + thesisWords(t) +
      '<div class="th-what">' + (t.outcome.status === 'right' || t.outcome.status === 'wrong'
        ? '<b>' + (t.outcome.status === 'right' ? 'Right' : 'Wrong') + '.</b> Revenue ' + formatMeasure('revenue_growth', t.outcome.revenue_change) +
          ', operating margin ' + formatMeasure('margin_change_bp', t.outcome.margin_change_bp) + ' bp, quarter to ' + fmtDay(t.outcome.quarter) + '.'
        : 'Not scored: ' + esc(t.outcome.why) + '.') + '</div></div>').join('');
}

/* How long a company has been followed, and the notes written on it (Phase 6). */
/* On a past day, the companies followed today that the desk cannot place in time:
   added before follow dates were kept (asof.coverage, K-03). Named, never shown as
   covered then. */
function notPlaced(){
  const U = DATA.as_of ? (DATA.undated_coverage || []) : [];
  return U.length
    ? U.map(esc).join(', ') + (U.length === 1 ? ' is' : ' are') + ' not shown: followed before the desk kept follow dates, ' +
      'so there is no telling whether ' + (U.length === 1 ? 'it was' : 'they were') + ' followed on this day. ' +
      'The next company update dates ' + (U.length === 1 ? 'it' : 'each') + ' from that day on.'
    : '';
}

function coverageLine(cv, ticker, c){
  if (!cv) return '';
  if (c && !c.followed)                  // held, and shown without being followed
    return '<div class="co-cover">In your account · <button class="linkish" data-follow-held="' + esc(ticker) + '">Follow it</button></div>';
  const age = (cv.days != null
    ? 'Followed for ' + cv.days + (cv.days === 1 ? ' day' : ' days')
    : 'Followed since before the desk kept dates') + (c && c.held ? ' · in your account' : '');
  // what has been written on it, only when something has
  const notes = (cv.notes ? ' · ' + cv.notes + (cv.notes === 1 ? ' note' : ' notes') : '') +
    (cv.theses ? ' · ' + cv.theses + (cv.theses === 1 ? ' thesis' : ' theses') : '');
  return '<div class="co-cover">' + age + notes +
    (DATA.as_of ? '' : ' · <button class="linkish" data-remove="' + esc(ticker) + '">Stop following</button>') + '</div>';
}

/* ---------------- five filed years (Phase 5) ----------------
   A 60×16 line beside each figure: its annual filings, oldest to newest, from
   screen.history — the same measure definitions, applied to each year. No axes, no
   interaction. Measures a block declares alike (the same kind and sign in their
   display declaration) share one scale, so a line never magnifies its own small
   wiggles: the three margins read against each other. A money figure has its own
   scale (fifth review, Q2): on revenue's, cash drew as a near-flat line, and a flat
   line says "nothing happened", which is false. Revenue against cash is the bridge's
   profit-to-cash block, in words and numbers. A gap is a year its filings could not
   support. */
function sparkline(name, h, block){
  const line = h && h.lines && h.lines[name];
  if (!line || line.filter(v => v != null).length < 2) return '';
  const spec = m => (DATA.measure_display || {})[m] || {};
  const alike = m => spec(name).kind === 'money' ? m === name
    : spec(m).kind === spec(name).kind && !spec(m).signed === !spec(name).signed;
  const pool = block.filter(alike).flatMap(m => ((h.lines || {})[m] || []).filter(v => v != null));
  let lo = Math.min.apply(null, pool), hi = Math.max.apply(null, pool);
  if (hi === lo){ lo -= 1; hi += 1; }
  const W = 60, H = 16, n = line.length;
  const x = i => 1 + i / (n - 1) * (W - 2), y = v => H - 2 - (v - lo) / (hi - lo) * (H - 4);
  let d = '', pen = false, last = null;
  line.forEach((v, i) => {
    if (v == null){ pen = false; return; }
    d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1);
    pen = true; last = [x(i), y(v)];
  });
  return '<svg class="spark" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true">' +
    '<path d="' + d + '"/><circle cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) + '" r="1.6"/></svg>';
}
function kv(k, v){ return '<div class="kv"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>'; }
function safe(fn){ try { fn(); } catch(e){ console.error(fn.name, e); } }

