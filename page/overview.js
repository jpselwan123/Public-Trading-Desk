/* ---------------- overview ---------------- */
function renderHeader(){
  const B = DATA.broker || {}, practice = DATA.env === 'demo' || DATA.env === 'paper';
  const demo = practice || DATA.demo;
  $('env').textContent = DATA.demo ? 'Demo data' : practice ? 'Practice' : DATA.env === 'export' ? 'From an export' : 'Live';
  $('env').classList.toggle('demo', !!demo);
  $('env').hidden = !DATA.connected && !DATA.demo;             // no account yet: neither live nor practice
  $('synced').textContent = DATA.synced_at ? 'account ' + fmtStamp(DATA.synced_at) : 'account not synced yet';
  const sync = B.key === 'csv' ? 'Read your export again'
    : 'Sync your ' + brokerName() + ' account';
  $('refreshBtn').setAttribute('aria-label', sync);
  $('refreshBtn').title = sync;
  safe(renderMarketAt);
  $('setup').hidden = (!!DATA.connected && !B.problem) || !!DATA.as_of;
  $('setupTitle').textContent = B.key === 'csv' ? 'Import your account (read-only)' : 'Connect ' + brokerName() + ' (read-only)';
  $('setupSteps').innerHTML = (B.connect || []).map(t => '<li>' + stepText(t) + '</li>').join('');
  $('setupOther').innerHTML = B.problem ? '<b>' + esc(sentence(B.problem)) + '</b>'
    : 'With another broker, set <code>BROKER</code> in <code>.env</code>: Trading 212, Alpaca, Interactive Brokers, ' +
      'or a CSV export from any broker (docs/BROKERS.md).';
  $('valueCard').hidden = !DATA.connected;
  $('statsCard').hidden = !DATA.connected;
}

function renderHero(){
  const a = DATA.account, g = DATA.growth, dv = DATA.dividends;
  $('total').textContent = DATA.connected ? money(a.total) : '–';
  let gain = '';
  if (g.investing != null && DATA.connected){
    const m = g.mwr;
    let ret = '';
    if (m){
      ret = m.days >= 365
        ? ' · <span>' + pct1(m.annual, true) + ' a year</span> <span class="why">money-weighted</span>'
        : ' · <span>' + pct1(m.period, true) + '</span> <span class="why">over ' + held(m.days) + '</span>';
    }
    gain = '<span>' + money(g.investing, {sign:true}) + '</span> <span class="why">earned by investing</span>' + ret;
  }
  $('gain').innerHTML = gain;
  // the same deposits in the S&P 500 (build_vs_market): the plain alternative, in the account's currency
  const v = DATA.vs_market;
  $('vsLine').innerHTML = !DATA.connected || !v ? ''
    : v.why_not ? '<span class="faint">Against the S&amp;P 500: not compared, because ' + esc(v.why_not) + '.</span>'
    : 'The same deposits in the S&amp;P 500 would be worth <b>' + money(v.market_value) + '</b>. You are <b>' +
      money(Math.abs(v.difference)) + ' ' + (v.difference >= 0 ? 'ahead' : 'behind') + '</b>' +
      (v.difference_pct != null ? ' (' + pct1(Math.abs(v.difference_pct)) + ')' : '') + '.';
  // what was put in and taken out, and each year's return, are on the History tab (28 Sep 2026)
  $('flows').innerHTML = g.first_deposit && DATA.connected
    ? '<a class="linkish" href="#history">Each year, since ' + fmtDay(g.first_deposit) + '</a>' : '';
  const stat = (k, v, sub, cls) => '<div class="stat"><div class="k">' + k + '</div><div class="v ' + (cls || '') + '">' + v + '</div>' +
    (sub ? '<div class="sv2">' + sub + '</div>' : '') + '</div>';
  $('stats').innerHTML = DATA.connected ? [
    stat('Invested', money(a.invested)),
    stat('Cash', money(a.cash), a.spending_pot > 0.004 ? '+ ' + money(a.spending_pot) + ' spending pot' : ''),
    stat('Open gain', money(a.unrealized, {sign:true}), a.cost > 0 ? pct1(a.unrealized / a.cost, true) + ' on cost' : ''),
    stat('Closed gain', money(a.realized, {sign:true}), ''),
    stat('Dividends', money(dv.last_12), 'last 12 months'),
  ].join('') : '';
}

/* What is new since the sync before this one (build_digest): one line of each kind. */
function renderDigest(){
  const D = DATA.digest;
  $('digestCard').hidden = !D;
  if (!D) return;
  $('digestSub').textContent = D.since
    ? 'since you last looked, ' + new Date(D.since).toLocaleString(undefined, {day:'numeric', month:'short', hour:'numeric', minute:'2-digit'})
    : 'in the last ' + D.fallback_days + ' days';
  const more = (shown, count) => count > shown ? ' <span class="faint">and ' + (count - shown) + ' more</span>' : '';
  const filing = i => '<b>' + esc(i.ticker) + '</b> <a href="' + link(i.url) + '" target="_blank" rel="noopener noreferrer">' + esc(i.headline || i.label) + '</a>';
  const rows = [];
  if (D.important_count) rows.push(['Important filings', D.important.map(filing).join(' · ') + more(D.important.length, D.important_count)]);
  if (D.insider_buys_count) rows.push(['Insiders buying', D.insider_buys.map(i => '<b>' + esc(i.ticker) + '</b> ' + esc(i.what || '')).join(' · ') +
    more(D.insider_buys.length, D.insider_buys_count)]);
  if (D.ratings_count) rows.push(['Desk ratings', D.ratings.map(r => '<b>' + esc(r.ticker) + '</b> ' +
    (r.was ? esc(r.was) + ' → ' : 'rated ') + esc(r.label)).join(' · ') + more(D.ratings.length, D.ratings_count)]);
  if ((D.moves || []).length) rows.push(['Biggest moves in your holdings', D.moves.map(m => '<b>' + esc(m.ticker) + '</b> ' +
    pct1(m.change, true)).join(' · ') + ' <span class="faint">close ' + fmtDay(D.moves[0].from) + ' to ' + fmtDay(D.moves[0].to) + '</span>']);
  if ((D.rated_sell || []).length) rows.push(['Holdings the desk rates Sell', D.rated_sell.map(t => '<b>' + esc(t) + '</b>').join(', ')]);
  const side = t => (t.side === 'SELL' ? 'sold ' : 'bought ') + '<b>' + esc(t.ticker) + '</b> ' + fmtDay(t.date);
  if (D.due_count) rows.push(['Trades you planned to look at again', D.due.map(t => side(t) + ', due ' + fmtDay(t.look_again) +
    (t.note ? ' <span class="faint">— ' + esc(t.note.length > 90 ? t.note.slice(0, 88) + '…' : t.note) + '</span>' : '')).join('<br>') +
    more(D.due.length, D.due_count)]);
  $('digest').innerHTML = rows.length
    ? rows.map(([k, v]) => '<div class="dg-row"><div class="dg-k">' + k + '</div><div class="dg-v">' + v + '</div></div>').join('')
    : '<div class="empty">' + (D.since ? 'Nothing new since then.' : 'Nothing new in the last ' + D.fallback_days + ' days.') + '</div>';
}

function renderHeadlines(){
  const N = DATA.news || {};
  const items = (N.items || []).filter(i => i.material).slice(0, 6);
  $('headSub').textContent = items.length ? 'important filings' : '';
  $('headlines').innerHTML = items.length ? items.map(i =>
    '<div class="headline"><span class="when">' + fmtDay(i.date) + '</span>' +
      '<span class="body"><div class="t"><span class="tk">' + esc(i.ticker) + '</span> ' +
        '<a href="' + link(i.url) + '" target="_blank" rel="noopener noreferrer">' + esc(i.headline || i.label) + '</a></div>' +
        '<div class="s">' + esc(i.what) + '</div></span></div>').join('')
    : '<div class="empty">Nothing important filed recently.</div>';
}

function renderUpcoming(){
  const C = (DATA.companies || []).filter(c => c.days_to_earnings != null)
    .sort((a, b) => a.days_to_earnings - b.days_to_earnings);
  $('upcoming').innerHTML = C.length ? C.map(c =>
    '<div class="headline"><span class="when">' + fmtDay(c.next_earnings.date) + '</span>' +
      '<span class="body"><div class="t"><span class="tk">' + esc(c.ticker) + '</span> results' +
        (c.next_earnings.when ? ' ' + esc(c.next_earnings.when) : '') + '</div>' +
        '<div class="s">in ' + c.days_to_earnings + ' days' +
          (c.beats ? ' · beat the estimate: ' + ofCount(c.beats) : '') + '</div></span></div>').join('')
    : '<div class="empty">' + (DATA.as_of ? 'Reporting dates are a forecast kept only from the latest company update, so none is shown for a past day.'
                                           : 'No reporting dates announced yet.') + '</div>';
}

/* ---------------- donut ---------------- */
const SLICE_COLOURS = ['var(--c1)','var(--c2)','var(--c3)','var(--c4)','var(--c5)','var(--c6)','var(--c7)'];
function donut(slices, opts){
  opts = opts || {};
  const shown = slices.filter(s => s.value > 0);
  if (!shown.length) return '<div class="empty">' + esc(opts.empty || 'Nothing to show yet.') + '</div>';
  const total = shown.reduce((t, s) => t + s.value, 0);
  const R = 62, r = 40, C = 85, gap = shown.length > 1 ? 0.018 : 0;
  let angle = -Math.PI / 2, paths = '';
  shown.forEach((s, i) => {
    const sweep = (s.value / total) * Math.PI * 2;
    const a0 = angle + gap / 2, a1 = angle + sweep - gap / 2;
    angle += sweep;
    if (a1 <= a0) return;
    const big = (a1 - a0) > Math.PI ? 1 : 0;
    const p = (rad, ang) => (C + rad * Math.cos(ang)).toFixed(2) + ',' + (C + rad * Math.sin(ang)).toFixed(2);
    paths += '<path class="slice" fill="' + (s.colour || SLICE_COLOURS[i % SLICE_COLOURS.length]) + '"' +
      ' d="M' + p(R, a0) + 'A' + R + ',' + R + ' 0 ' + big + ',1 ' + p(R, a1) +
      'L' + p(r, a1) + 'A' + r + ',' + r + ' 0 ' + big + ',0 ' + p(r, a0) + 'Z">' +
      '<title>' + esc(s.label) + ' · ' + esc(s.text || '') + '</title></path>';
  });
  const legend = shown.map((s, i) =>
    '<div class="row"><span class="dot" style="background:' + (s.colour || SLICE_COLOURS[i % SLICE_COLOURS.length]) + '"></span>' +
    '<span class="nm">' + esc(s.label) + '</span>' +
    '<span class="amt">' + esc(s.text || '') + '</span>' +
    '<span class="pc">' + pct(s.value / total) + '</span></div>').join('');
  return '<div class="donut"><svg viewBox="0 0 170 170" role="img" aria-label="' + esc(opts.title || 'Breakdown') + '">' +
    paths +
    (opts.centre ? '<text class="hole" x="85" y="80" text-anchor="middle" fill="var(--ink)" font-size="15" font-weight="600">' +
      esc(opts.centre) + '</text><text class="hole" x="85" y="95" text-anchor="middle" fill="var(--ink-faint)" font-size="9">' +
      esc(opts.centreLabel || '') + '</text>' : '') +
    '</svg><div class="legend">' + legend + '</div></div>';
}

