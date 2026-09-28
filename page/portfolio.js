/* ---------------- portfolio ---------------- */
let holdSort = 'value';
function renderMix(){
  const a = DATA.account || {}, P = DATA.positions || {rows: []};
  if (!DATA.connected){ $('mixChart').innerHTML = '<div class="empty">Connect your account to see the split.</div>'; $('mixSub').textContent = ''; return; }
  const holdings = (P.rows || []).slice(0, 6).map(r => ({label: r.ticker, value: r.value, text: money(r.value)}));
  const rest = (P.rows || []).slice(6).reduce((t, r) => t + r.value, 0);
  if (rest > 0) holdings.push({label: 'Other holdings', value: rest, text: money(rest)});
  const slices = holdings.concat([
    {label: 'Cash', value: a.cash || 0, text: money(a.cash || 0), colour: 'var(--border-strong)'},
    {label: 'Spending pot', value: a.spending_pot || 0, text: money(a.spending_pot || 0), colour: 'var(--surface-2)'},
  ]);
  $('mixSub').textContent = money(a.total) + ' in total';
  $('mixChart').innerHTML = donut(slices, {centre: money(a.total, {dp: 0}), centreLabel: 'account',
                                           title: 'How the account is split', empty: 'The account is empty.'});
}

function renderHoldings(){
  const P = DATA.positions;
  $('holdSub').textContent = P.count
    ? P.count + (P.count === 1 ? ' holding' : ' holdings') + ' · largest ' + pct(P.largest) + (P.count > 5 ? ' · top 5 ' + pct(P.top5) : '')
    : '';
  if (!P.count){
    $('holdList').innerHTML = '<div class="empty">' + (DATA.connected ? 'No open positions right now.' : 'Connect your account to see your holdings.') + '</div>';
    return;
  }
  const rows = P.rows.slice().sort((x, y) => {
    if (holdSort === 'ticker') return x.ticker.localeCompare(y.ticker);
    const a = x[holdSort] == null ? -Infinity : x[holdSort], b = y[holdSort] == null ? -Infinity : y[holdSort];
    return b - a;
  });
  const maxW = Math.max.apply(null, rows.map(r => r.weight)) || 1;
  let html = '<div class="h-row h-head" aria-hidden="true"><span>Holding</span><span>Share of holdings</span><span class="r">Value</span><span class="r">Gain</span></div>';
  rows.forEach((r, i) => {
    html += '<button class="h-row" aria-expanded="false" data-i="' + i + '">' +
      '<span class="h-n"><div class="tk">' + esc(r.ticker) + ' ' + ratingTag(r.rating) + '</div><div class="nm">' + esc(r.name) + '</div></span>' +
      '<span class="wbar"><span class="track"><span class="fill" style="width:' + (r.weight / maxW * 100).toFixed(1) + '%"></span></span><span class="pct">' + pct(r.weight) + '</span></span>' +
      '<span class="r num h-v">' + money(r.value) + '</span>' +
      '<span class="r num h-g">' + money(r.pl, {sign:true}) + '<div style="font-size:13px">' + pct1(r.pl_pct, true) + '</div></span>' +
      '</button>' +
      '<div class="h-detail" id="hd' + i + '">' +
        kv('Shares', qty(r.quantity)) + kv('Average price', pricePer(r.avg_price, r.currency)) + kv('Price now', pricePer(r.price, r.currency)) +
        kv('Cost', money(r.cost)) + (Math.abs(r.fx) > 0.004 ? kv('From currency moves', '<span>' + money(r.fx, {sign:true}) + '</span>') : '') +
        kv('Opened', fmtDay(r.opened)) + kv('Held', held(r.days_held)) +
        kv('Desk rating', r.rating && r.rating.label ? esc(r.rating.label) + '<div class="dash-why">' + ratingPlace(r.rating) + '</div>'
           : '–' + (r.rating ? '<div class="dash-why">' + esc(sentence(r.rating.why_not)) + '</div>' : '')) +
      '</div>';
  });
  // an export's line with no daily close is valued at what it cost (broker.complete), and says so
  const atCost = (DATA.broker || {}).valued_at_cost || [];
  if (atCost.length) html += '<div class="co-note">' + esc(atCost.join(', ')) + (atCost.length === 1 ? ' is' : ' are') +
    ' valued at cost: the desk has daily closes only for US shares, and your export gives no price for ' +
    (atCost.length === 1 ? 'it' : 'them') + '. The account&rsquo;s total counts ' + (atCost.length === 1 ? 'it' : 'them') + ' so.</div>';
  $('holdList').innerHTML = html;
}
/* The account by industry (build_exposure): the SEC's own code for each company, in the
   SIC Manual's words; funds and lines outside the SEC's data named together; cash apart. */
function renderExposure(){
  const X = DATA.exposure || {};
  $('expSub').textContent = '';
  if (!DATA.connected){ $('expBody').innerHTML = '<div class="empty">Connect your account to see what the account is invested in.</div>'; return; }
  const line = (label, part, note, cls) => '<div class="ex-row"><div class="ex-top"><span class="ex-nm">' + label + '</span>' +
    '<span class="num">' + money(part.value) + ' · ' + pct1(part.weight) + '</span></div>' +
    '<div class="wbar"><span class="track"><span class="fill' + (cls ? ' ' + cls : '') + '" style="width:' +
      Math.max(0, Math.min(100, (part.weight || 0) * 100)).toFixed(1) + '%"></span></span></div>' +
    (note ? '<div class="dash-why">' + note + '</div>' : '') + '</div>';
  const groups = X.groups || [];
  if (groups.length) $('expSub').textContent = groups.length + (groups.length === 1 ? ' industry' : ' industries') +
    /* not a rate: a share of money, measured in full, not a count of cases */
    ' · largest ' + pct1(groups[0].weight) + ' of the account';
  $('expBody').innerHTML =
    (groups.length || X.unplaced || (X.cash || {}).value
      ? groups.map(g => line(esc(g.label), g, esc(g.tickers.join(', ')))).join('') +
        (X.unplaced ? line('Funds, and shares outside the SEC\'s data', X.unplaced,
          esc(X.unplaced.tickers.join(', ')) + ' — a fund holds many companies, and the desk does not see inside it') : '') +
        ((X.cash || {}).value > 0.004 ? line('Cash', X.cash, '', 'cash') : '')
      : '<div class="empty">The account is empty.</div>') +
    (X.missing ? '<p class="co-note faint" style="margin-top:12px">Industries are not shown: ' + esc(X.missing) + '.</p>'
      : '');
}

/* Every charge on every fill, by kind, and the tax withheld from dividends (build_costs),
   with their share of what investing earned before them. */
function renderCosts(){
  const C = DATA.costs || {};
  $('costSub').textContent = C.since ? 'since ' + fmtDay(C.since) : '';
  if (!DATA.connected){ $('costBody').innerHTML = '<div class="empty">Connect your account to see what investing has cost.</div>'; return; }
  const row = (label, value, note) => '<div class="br-row"><span>' + label + (note ? '<div class="dash-why">' + note + '</div>' : '') +
    '</span><span class="num">' + value + '</span></div>';
  $('costBody').innerHTML =
    '<div class="cost-top"><span class="cost-total">' + money(C.total) + '</span>' +
      /* not a rate: a share of money, measured in full, not a count of cases */
      (C.share_of_gain != null ? ' <span class="muted">— ' + pct1(C.share_of_gain) + ' of what investing earned before them</span>' : '') + '</div>' +
    (C.kinds || []).map(k => row(esc(k.label), money(k.amount))).join('') +
    row('Tax withheld from dividends', money(C.withheld),
        C.unconverted_dividends ? C.unconverted_dividends + ' paid in another currency are left out: no exchange rate is stored for them' : '') +
    '<div class="wd-h" style="margin-top:16px">Beside them</div>' +
    row('Interest paid on your cash', money(C.interest, {sign:true})) +
    (Math.abs(C.currency_moves || 0) > 0.004 ? row('Currency moves on what you hold', money(C.currency_moves, {sign:true})) : '');
}

$('holdList').addEventListener('click', e => {
  const b = e.target.closest('.h-row[data-i]'); if (!b) return;
  const d = $('hd' + b.dataset.i), open = !d.classList.contains('open');
  d.classList.toggle('open', open); b.setAttribute('aria-expanded', open);
});
$('holdSort').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  holdSort = b.dataset.k;
  [...$('holdSort').children].forEach(x => x.setAttribute('aria-pressed', x === b));
  safe(renderHoldings);
});

function renderDividends(){
  const D = DATA.dividends;
  $('divSub').textContent = D.count ? money(D.last_12) + ' in 12 months · ' + money(D.total) + ' all time' : '';
  const box = $('divChart');
  if (!D.count){
    box.innerHTML = '<div class="empty">' + (DATA.connected ? 'No dividends paid yet.' : 'Dividends appear here once connected.') + '</div>';
    $('divPayers').innerHTML = '';
    return;
  }
  const M = D.months, W = 640, H = 210, L = 52, R = 8, T = 12, B = 26;
  const max = Math.max.apply(null, M.map(m => m.amount)) || 1;
  const step = niceStep(max / 3), top = Math.ceil(max / step) * step;
  const bw = (W - L - R) / M.length, gap = 2;
  const y = v => T + (H - T - B) * (1 - v / top);
  let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Dividends per month"><g class="grid">';
  for (let v = 0; v <= top + 1e-9; v += step) svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>';
  svg += '</g><g class="axis">';
  for (let v = 0; v <= top + 1e-9; v += step) svg += '<text x="' + (L - 8) + '" y="' + (y(v) + 3.5) + '" text-anchor="end">' + money(v, {dp: step < 1 ? 2 : 0}) + '</text>';
  M.forEach((m, i) => {
    const mo = +m.month.slice(5);
    if (mo === 1 || i === 0) svg += '<text x="' + (L + i * bw + 1) + '" y="' + (H - 8) + '">' + (mo === 1 ? m.month.slice(0, 4) : MONTHS[mo - 1] + ' ' + m.month.slice(2, 4)) + '</text>';
  });
  svg += '</g>';
  const cur = DATA.today.slice(0, 7);
  M.forEach((m, i) => {
    const x = L + i * bw + gap / 2, w = Math.max(1, bw - gap), yy = y(m.amount), h = y(0) - yy;
    svg += '<rect class="hit" data-i="' + i + '" x="' + (L + i * bw) + '" y="' + T + '" width="' + bw + '" height="' + (H - T - B) + '"/>';
    if (m.amount > 0) svg += '<path class="bar' + (m.month === cur ? ' partial' : '') + '" id="db' + i + '" d="' + roundTop(x, yy, w, h, Math.min(4, w / 2, h)) + '"/>';
  });
  box.innerHTML = svg + '</svg><div class="tip" id="divTip"></div>';
  const tip = $('divTip');
  const show = el => {
    const i = +el.dataset.i, m = M[i];
    box.querySelectorAll('.bar.on').forEach(b => b.classList.remove('on'));
    const bar = $('db' + i); if (bar) bar.classList.add('on');
    const [yy, mm] = m.month.split('-');
    tip.innerHTML = MONTHS[+mm - 1] + ' ' + yy + (m.month === cur ? ' (so far)' : '') + ' · <span class="num">' + money(m.amount) + '</span>';
    const s = box.getBoundingClientRect().width / W;
    tip.style.left = Math.max(70, Math.min(box.clientWidth - 70, (L + (i + 0.5) * bw) * s)) + 'px';
    tip.style.top = (y(m.amount) * s - 6) + 'px';
    tip.classList.add('on');
  };
  box.querySelectorAll('.hit').forEach(h => { h.addEventListener('mouseenter', () => show(h)); h.addEventListener('click', () => show(h)); });
  box.addEventListener('mouseleave', () => { tip.classList.remove('on'); box.querySelectorAll('.bar.on').forEach(b => b.classList.remove('on')); });
  $('divPayers').innerHTML = '<div class="eyebrow" style="margin-bottom:6px">Top payers, all time</div>' +
    D.tickers.slice(0, 6).map(t => '<div class="p"><span class="tk">' + esc(t.ticker) + '</span><span class="num">' + money(t.amount) + '</span></div>').join('');
}
function niceStep(raw){
  if (!(raw > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}
function roundTop(x, y, w, h, r){
  if (h <= 0) return '';
  r = Math.max(0, r);
  return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y + 'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
}

