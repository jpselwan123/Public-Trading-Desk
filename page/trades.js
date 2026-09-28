/* ---------------- practice portfolio ---------------- */
const usd = v => (v == null ? '–' : (v < 0 ? '−' : '') + '$' + Math.abs(v).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}));
let pSide = 'buy';
function renderPaper(){
  const P = DATA.paper || {};
  $('pUnread').hidden = !P.unreadable;
  $('pUnread').textContent = P.unreadable || '';
  // fills at the last close and pays the real account's cost, so nothing is flattered
  $('pCost').textContent = 'last close' + (P.cost != null ? ' · ' + (P.cost * 100).toFixed(2) + '% cost' : '');
  $('pTotal').textContent = usd(P.total);
  $('pReturn').innerHTML = P.started
    ? '<span>' + pct1(P['return'], true) + '</span> <span class="why">since ' + fmtDay(P.started) + '</span>' +
      (P.vs_market != null
        ? ' · <span>' + pct1(P.vs_market, true) + '</span> <span class="why">vs holding the market</span>'
        : ' <span class="why">· the market comparison starts once a day has passed</span>')
    /* not a rate: an amount of money */
    : '<span class="why">Start with ' + usd(P.start_cash) + ' of pretend money.</span>';
  $('pLines').innerHTML = 'Cash <span class="num">' + usd(P.cash) + '</span>' +
    '<br>In shares <span class="num">' + usd(P.invested) + '</span>' +
    (P.trade_count ? '<br>Costs paid <span class="num">' + usd(P.fees) + '</span> · closed gains <span class="num">' + usd(P.realised) + '</span>' : '') +
    /* not a rate: a length of time */
    (P.days ? '<br><span class="faint">' + held(P.days) + ' of practice</span>' : '');

  const holdings = P.positions || [];
  $('pHoldSub').textContent = holdings.length ? holdings.length + (holdings.length === 1 ? ' holding' : ' holdings') : '';
  $('pHold').innerHTML = holdings.length
    ? '<div class="p-row head"><span>Holding</span><span class="num hide">Shares</span><span class="num">Value</span><span class="num">Gain</span></div>' +
      holdings.map(r => '<div class="p-row"><span><span class="tk">' + esc(r.ticker) + '</span>' +
        '<div class="faint" style="font-size:12.5px">bought at ' + usd(r.average) + ' · now ' + usd(r.price) + '</div></span>' +
        '<span class="num hide">' + qty(r.quantity) + '</span>' +
        '<span class="num"><span class="lbl">Value</span>' + usd(r.value) + '</span>' +
        '<span class="num"><span class="lbl">Gain</span>' + usd(r.pl) +
          '<div style="font-size:12.5px">' + pct1(r.pl_pct, true) + '</div></span></div>').join('')
    : '<div class="empty">No practice holdings yet.</div>';

  $('pMix').innerHTML = holdings.length
    ? donut(holdings.map(h => ({label: h.ticker, value: h.value, text: usd(h.value)}))
              .concat([{label: 'Cash', value: P.cash || 0, text: usd(P.cash || 0), colour: 'var(--border-strong)'}]),
            {centre: usd(P.total).replace(/\.\d+$/, ''), centreLabel: 'practice', title: 'Practice split'})
    : '';

  const trades = P.trades || [];
  $('pTradeSub').textContent = trades.length ? trades.length + (trades.length === 1 ? ' trade' : ' trades') : '';
  $('pTrades').innerHTML = trades.length
    ? trades.slice(0, 50).map(t => '<div class="p-trade"><div class="line">' +
        '<span><span class="side ' + esc(t.side) + '">' + esc(t.side) + '</span> <span class="tk">' + esc(t.ticker) + '</span> ' +
          '<span class="faint" style="font-size:13.5px">' + qty(t.quantity) + ' @ ' + usd(t.price) + ' · ' + fmtDay(t.date) + '</span></span>' +
        '<span class="num">' + usd(t.value) +
          (t.realised != null ? ' <span style="font-size:13.5px">' + usd(t.realised) + ' closed</span>' : '') + '</span>' +
        '</div>' + (t.reason ? '<div class="why">' + esc(t.reason) + '</div>' : '') + '</div>').join('')
    : '<div class="empty">Your practice trades appear here, with the reason you gave.</div>';

  const tickers = [...new Set(((DATA.news || {}).tickers || []).concat(holdings.map(h => h.ticker)))];
  const sel = $('pTicker'), chosen = sel.value;
  sel.innerHTML = tickers.length ? tickers.map(t => '<option' + (t === chosen ? ' selected' : '') + '>' + esc(t) + '</option>').join('')
    : '<option value="">follow a company at the top of the Companies tab</option>';
}
$('pSide').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  pSide = b.dataset.side;
  [...$('pSide').children].forEach(x => x.setAttribute('aria-pressed', x === b));
});
async function paperPost(body){
  const msg = $('pMsg');
  msg.textContent = 'Working…';
  try {
    const r = await fetch('/paper', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const res = await r.json();
    if (!res.ok) throw new Error(res.message || 'Could not place it');
    DATA.paper = res.paper;
    safe(renderPaper); safe(renderNav);
    msg.textContent = '';
    return true;
  } catch(err){ msg.textContent = err.message; return false; }
}
$('pSubmit').addEventListener('click', async () => {
  if (DATA.as_of) return;                                   // a past day is read-only
  const ticker = $('pTicker').value, amount = $('pAmount').value, reason = $('pReason').value;
  if (!ticker) return;
  const done = await paperPost({action: pSide, ticker, amount, reason});
  if (done){ $('pAmount').value = ''; $('pReason').value = ''; }
});
$('pReset').addEventListener('click', () => {
  if (DATA.as_of) return;                                   // a past day never resets today's book
  if (confirm('Clear every practice trade and start again with pretend cash?')) paperPost({action:'reset'});
});

/* ---------------- closed trades vs the market ---------------- */
function renderClosed(){
  const C = DATA.closed_trades || {};
  if (!C.count){
    $('ctSub').textContent = '';
    $('ctList').innerHTML = '<div class="empty">Once you close a position, each trade is compared with leaving the same money in the market.</div>';
    return;
  }
  $('ctSub').textContent = C.count + (C.count === 1 ? ' sale' : ' sales');
  const lead = C.scored
    ? 'Sales at a gain: ' + ofCount(C.won) + '.<br>Ahead of leaving the same money in the market: ' + ofCount(C.beat_market) + '. ' +
      chanceText(C.beat_market) + '<br>At the middle trade you were ' + vsMarket(C.vs_market) + '.'
    : 'Every trade so far was opened and closed on the same day, and daily prices can\'t measure an intraday market move — so there is nothing honest to compare against yet.';
  const row = r =>
      '<div class="ct-row"><span><span class="tk">' + esc(r.ticker) + '</span> <span class="ct-when">' + qty(r.quantity) + ' @ ' +
        pricePer(r.buy_price, r.price_currency) + ' → ' + pricePer(r.sell_price, r.price_currency) +
        (r.split ? ' · split-adjusted' : '') + '</span></span>' +
      '<span class="ct-when">' + (r.buys > 1 ? r.buys + ' buys from ' : '') + fmtDay(r.bought) + ' → ' + fmtDay(r.sold) +
        (r.days ? ' · ' + held(r.days) : ' · same day') + '</span>' +
      '<span class="num"><span class="lbl">You</span>' + pct1(r.gain, true) + '</span>' +
      '<span class="num mkt"><span class="lbl">Market</span>' + (r.market != null ? pct1(r.market, true) : '–') + '</span>' +
      '<span class="num"><span class="lbl">Difference</span>' +
        (r.vs_market != null ? pct1(r.vs_market, true) : '–') + '</span></div>';
  // the latest few, the rest a click away: the verdict above already counts them all
  const rows = C.rows.slice(0, 40), first = 5;
  $('ctList').innerHTML = '<div class="verdict">' + lead + '</div>' +
    '<div class="ct-row head"><span>Trade</span><span>Held</span><span class="num">You</span><span class="num mkt">Market</span><span class="num">Difference</span></div>' +
    rows.slice(0, first).map(row).join('') +
    (rows.length > first ? '<details class="page-fold"><summary>' + (rows.length - first) + ' earlier ' +
      (rows.length - first === 1 ? 'sale' : 'sales') + '</summary>' + rows.slice(first).map(row).join('') + '</details>' : '') +
    about('<p>One row a sale, however many buys it closed, matched first in, first out: the sale is the decision, and each ' +
      'is counted once. &ldquo;You&rdquo; is what the money did in your account&rsquo;s currency: what each buy took and the sale ' +
      'gave back, fees and the day&rsquo;s exchange rate in both; &ldquo;Market&rdquo; is the S&amp;P 500 over each buy&rsquo;s ' +
      'own days in the same currency, weighted by what each cost. A buy made before a split is counted in the ' +
      'sale&rsquo;s shares, so a split never reads as a loss. A buy sold the same day is left out of the comparison: daily ' +
      'prices cannot measure it.</p><p>' + ((DATA.broker || {}).states_gains ? esc(brokerName()) + ' counts' : 'The desk&rsquo;s closed gain, as Trading 212 states it, counts') +
      ' a sale against the average price of the whole holding, so where a ' +
      'holding was bought at several prices, a sale&rsquo;s result here can differ from the one in its app and in your list of trades, ' +
      'which shows its own; so is the closed gain on the Overview.</p>', 'How this is counted');
}

/* ---------------- plans before trades (plans.py) ----------------
   Why, and what would prove it wrong, written before the order; matched to the trade when
   the account syncs; scored against the market on the day chosen. Written once. */
function planResult(r){
  const x = r.result;
  if (!x) return 'no result yet';
  return (x.final ? 'at ' : 'so far, to ') + fmtDay(x.to) + ': shares ' + pct1(x.shares, true) + ', market ' +
    pct1(x.market, true) + ' · ' + pct1(Math.abs(x.edge)) + (x.edge >= 0 ? ' better' : ' worse') + ' than the market for this ' +
    (r.side === 'SELL' ? 'sale' : 'purchase');
}
function planRow(r){
  const state = r.state === 'waiting' ? 'waiting for the trade, until ' + fmtDay(r.match_until)
    : r.state === 'not acted on' ? 'not acted on'
    : (r.side === 'SELL' ? 'sold ' : 'bought ') + fmtDay((r.trade || {}).date) + ' · ' + planResult(r);
  return '<div class="pl-row"><div class="pl-h"><span><span class="tk">' + esc(r.ticker) + '</span> ' +
      (r.side === 'SELL' ? 'Sell' : 'Buy') + '</span><span class="faint">' + state + '</span></div>' +
    '<div class="pl-why">' + esc(r.why) + '</div>' +
    '<div class="pl-wrong faint">Wrong if: ' + esc(r.wrong_if) + '</div>' +
    '<div class="pl-meta faint">Written ' + fmtStamp(r.written, '') + ' · look again on ' + fmtDay(r.review_by) + '</div></div>';
}
function renderPlans(){
  const P = DATA.plans || {}, rows = P.rows || [];
  $('planNew').hidden = !!DATA.as_of;
  $('plSub').textContent = rows.length ? rows.length + (rows.length === 1 ? ' plan' : ' plans') +
    (P.waiting ? ' · ' + P.waiting + ' waiting for the trade' : '') : '';
  // optional, never asked for: with none written the card is its title and button alone
  $('plSub').textContent = rows.length ? $('plSub').textContent : 'optional';
  if (!rows.length){
    $('plList').innerHTML = DATA.as_of ? '<div class="empty">No plan had been written by this day.</div>' : '';
    return;
  }
  const lead = P.reviewed
    ? '<div class="verdict">Plans that did better than the market by their day: ' + ofCount(P.better) + '. ' +
      chanceText(P.better) + '<br>At the middle plan you were ' + vsMarket(P.median_edge) + '.</div>' : '';
  $('plList').innerHTML = lead + rows.map(planRow).join('') +
    about('<p>A plan is matched to the first trade in that company, on that side, within ' + P.match_days +
      ' days of writing it, and scored from that trade to the day you chose: the shares against the S&amp;P 500 over the same ' +
      'closes. A purchase did better when the shares beat the market; a sale, when they then fell behind it. Before its day, ' +
      'a result is marked &ldquo;so far&rdquo; and not counted.</p><p>Why write it first: a reason written after a trade is ' +
      'rewritten by what happened next (Fischhoff 1975). Saying what would prove it wrong is the pre-mortem (Klein 2007). ' +
      'A plan sends no order.</p>', 'How plans are scored');
}
function openPlan(){
  const P = DATA.plans || {};
  $('plWhat').textContent = 'Written once: it cannot be edited or deleted. It is matched to your next trade in this company within ' +
    P.match_days + ' days, and scored against the S&P 500 on the day you choose.';
  ['plTicker', 'plWhy', 'plWrong', 'plReview'].forEach(id => { $(id).value = ''; });
  $('plSide').value = '';
  $('plWhy').maxLength = P.max_why; $('plWrong').maxLength = P.max_wrong;
  const day = n => { const t = new Date(DATA_INITIAL.today + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); };
  if (DATA_INITIAL.today){ $('plReview').min = day(1); $('plReview').max = day(P.longest_review_days); }
  $('plMsg').textContent = '';
  $('planDlg').showModal();
}
$('planNew').addEventListener('click', openPlan);
$('planForm').addEventListener('submit', async e => {
  if (e.submitter && e.submitter.value === 'cancel') return;
  e.preventDefault();
  $('plMsg').textContent = 'Saving…';
  try {
    const r = await fetch('/plan', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
      ticker: $('plTicker').value, side: $('plSide').value, why: $('plWhy').value, wrong_if: $('plWrong').value,
      review_by: $('plReview').value})});
    const res = await r.json();
    if (!res.ok) throw new Error(res.message || 'Could not save');
    DATA.plans = res.plans || DATA.plans;
    $('planDlg').close();
    safe(renderPlans);
  } catch(err){ $('plMsg').textContent = location.protocol === 'file:' ? 'Open the desk with ./desk.sh to write a plan' : err.message; }
});


/* ---------------- a trade checked before it is placed (trade_check.py) ----------------
   A ticker, buy or sell, an amount: the facts, from what the desk holds. Nothing to write,
   nothing sent. */
let ckSide = 'BUY';
function renderCheckCard(){
  $('checkCard').hidden = !!DATA.as_of;
  $('checkSub').textContent = 'the facts, before you place it with ' + brokerName();
}
function checkLines(c){
  const L = [], name = (c.name ? esc(c.name) + ' (' + esc(c.ticker) + ')' : esc(c.ticker));
  /* not a rate: an amount of money in a company */
  L.push('<b>' + (c.side === 'SELL' ? 'Selling ' : 'Buying ') + money(c.amount) + '</b> of ' + name +
    (c.price ? ' · last close $' + c.price.toFixed(2) : '') + '.');
  if (c.outside_us) L.push('<span class="faint">' + esc(c.ticker) + ' is the line you hold listed outside the US: the desk has no rating, ' +
    'industry, results or US figures for it.</span>');
  L.push('Your holding: ' + money(c.held_before) + ' → <b>' + money(c.held_after) + '</b>, ' + pct1(c.weight_before) + ' → <b>' +
    pct1(c.weight_after) + '</b> of the account.' +
    /* not a rate: the cash in the account, an amount */
    (c.over_cash ? ' <span class="warn-t">More than your cash of ' + money(c.cash) + '.</span>' : '') +
    (c.over_held ? ' <span class="warn-t">More than you hold.</span>' : ''));
  if (c.industry) L.push(esc(c.industry.label) + ': ' + pct1(c.industry.before) + ' → <b>' + pct1(c.industry.after) + '</b> of the account.');
  const r = c.rating;
  L.push(r && r.label ? 'Desk rating ' + ratingTag(r) + ' — ' + ratingPlace(r) + '.'
    : 'Desk rating: none' + (r && r.why_not ? ', because ' + esc(r.why_not) : '') + '.');
  if (c.covered){
    L.push(c.results && c.results.date ? 'Reports ' + fmtDay(c.results.date) + (c.results.when ? ' ' + esc(c.results.when) : '') +
      ', in ' + c.results.days + (c.results.days === 1 ? ' day.' : ' days.') : 'No results date announced.');
    /* not a rate: a place among the company's own months, every one of them counted */
    if (c.pe) L.push('Price to earnings ' + pePlace(c.pe.place, 'its months over its last ' + c.pe.years + ' years') + '.');
    if (c.year_vs_market != null) L.push(pct1(c.year_vs_market, true) + ' against the market over a year.');
  } else {
    L.push('<span class="faint">Not one you follow or hold, so no results date or news here: follow it for its card.</span>');
  }
  const f = c.fees || {};
  L.push(f.rate != null ? 'Your last ' + f.trades + (c.side === 'SELL' ? ' sales' : ' buys') + ' paid a median ' +
    (f.rate * 100).toFixed(f.rate < 0.01 ? 2 : 1) + '%' +
    ' in fees: about <b>' + money(f.amount) + '</b> on this.' : 'No ' + (c.side === 'SELL' ? 'sales' : 'buys') + ' on record to read fees from.');
  const d = c.dividend;
  /* not a rate: a yield and a share of money, each measured in full, not a count of cases */
  if (d) L.push('At its yield of ' + pct1(d.yield) + ', about <b>' + money(d.yearly) + '</b> a year in dividends' +
    (d.withheld_rate != null ? '; ' + pct1(d.withheld_rate) + ' of your dividends so far was withheld as tax: about ' + money(d.withheld) + ' of it.' : '.'));
  return L.map(t => '<div class="ck-line">' + t + '</div>').join('') +
    '<div class="ck-foot"><button class="linkish" data-plan-for="' + esc(c.ticker) + '" data-plan-side="' + esc(c.side) + '">Write a plan for it</button>' +
    ' <span class="faint">(optional)</span></div>';
}
async function runCheck(){
  const ticker = $('ckTicker').value.trim().toUpperCase(), amount = $('ckAmount').value;
  if (!ticker || !amount){ $('ckOut').innerHTML = '<div class="faint">A ticker and an amount.</div>'; return; }
  $('ckOut').innerHTML = '<div class="faint">Checking…</div>';
  try {
    const r = await fetch('/check', {method:'POST', headers:{'Content-Type':'application/json'},
                                     body: JSON.stringify({ticker, side: ckSide, amount})});
    const res = await r.json();
    if (!res.ok) throw new Error(res.message || 'Could not check it');
    $('ckOut').innerHTML = checkLines(res.check);
  } catch(err){
    $('ckOut').innerHTML = '<div class="faint">' + esc(location.protocol === 'file:' ? 'Open the desk with ./desk.sh to check a trade' : err.message) + '</div>';
  }
}
$('ckForm').addEventListener('submit', e => { e.preventDefault(); runCheck(); });
$('ckSide').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  ckSide = b.dataset.side;
  [...$('ckSide').children].forEach(x => x.setAttribute('aria-pressed', x === b));
});
$('ckOut').addEventListener('click', e => {
  const b = e.target.closest('[data-plan-for]'); if (!b) return;
  openPlan();
  $('plTicker').value = b.dataset.planFor; $('plSide').value = b.dataset.planSide;
});
/* from a company's card: its ticker in the check, the amount to type */
document.addEventListener('click', e => {
  const b = e.target.closest('[data-check]'); if (!b) return;
  showPage('journal');
  $('ckTicker').value = b.dataset.check;
  $('checkCard').scrollIntoView({block: 'start'});
  $('ckAmount').focus();
});

/* ---------------- the user's habits (habits.py) ----------------
   Each figure the user's own, with its interval, beside what its paper found. */
function renderHabits(){
  const H = DATA.habits || {}, P = H.published || {}, t = H.turnover || {}, d = H.disposition || {}, r = H.replaced || {};
  $('habitCard').hidden = !((DATA.trades || {}).count);
  const L = [];
  if (t.trades) L.push('<b>How much you trade.</b> In the last ' + t.months + ' months you bought ' + money(t.bought) + ' and sold ' + money(t.sold) +
    ' in ' + t.trades + (t.trades === 1 ? ' trade' : ' trades') +
    (t.yearly != null ? ': a turnover of <b>' + pct(t.yearly) + '</b> a year' +
      (t.basis === 'today' ? ' <span class="faint">(against what you hold today: the months before could not be rebuilt)</span>'
       : t.basis === 'us_month' ? ' <span class="faint">(of your US shares: the desk has no daily closes for the lines listed elsewhere)</span>' : '') : '') + '. ' +
    /* not a rate: a published figure quoted, not the user's count */
    '<span class="faint">Barber &amp; Odean (2000): the average household turned over ' + pct(P.turnover_yearly_average) +
    ' of its shares a year; those that traded most earned ' + pct1(P.return_most_active) + ' a year, the market ' +
    pct1(P.return_market) + '.</span>');
  if (d.pgr || d.plr) L.push('<b>Winners sold, losers kept.</b> On the days you sold: of the holdings at a gain, you sold ' +
    ofCount(d.pgr) + '; of those at a loss, ' + ofCount(d.plr) + '. ' +
    (d.difference ? (d.difference.distinguishable
      ? (d.difference.estimate > 0 ? 'You sold gains more readily than losses, beyond what chance would give.'
                                   : 'You sold losses more readily than gains, beyond what chance would give.')
      : 'The two cannot be told apart yet.') : '') +
    /* not a rate: published figures quoted, not the user's count */
    ' <span class="faint">Odean (1998): investors sold gains at ' + pct1(P.pgr) + ' of the chances and losses at ' + pct1(P.plr) + '.</span>');
  if (r.pairs || r.pending) L.push('<b>What replaced what you sold.</b> ' + (r.pairs
    ? (r.pairs === 1 ? 'For the one sale followed within ' : 'Across ' + r.pairs + ' sales each followed within ') + r.within_days +
      ' days by buying another share, the share bought did ' + medianMove(r.gap, v => pct1(v, true)) +
      ' against the one sold over the next year' + (r.pairs === 1 ? '. ' : ', at the middle pair. ') +
      (r.gap && r.gap.distinguishable ? 'That is beyond what chance would give.' : 'That cannot be told from no difference.')
    : r.pending + (r.pending === 1 ? ' sale was' : ' sales were') + ' followed by buying another share; each is measured once a year has passed.') +
    ' <span class="faint">Odean (1999): the shares investors bought did worse over the next year than those they sold.</span>');
  $('habitList').innerHTML = L.length ? L.map(x => '<div class="ck-line">' + x + '</div>').join('') +
    about('<p>Turnover is Barber &amp; Odean&rsquo;s: each month, half of what was bought and sold over what the shares held at the ' +
      'month&rsquo;s start were worth (rebuilt from your record, as the History tab does), averaged, and twelve months of it. The count of gains and losses is Odean&rsquo;s: on each day you sold, each US holding ' +
      'you held is a gain or a loss against its average cost, sold that day or kept. A holding is counted on every such day, so the ' +
      'counts are not independent draws, and their ranges are, if anything, narrower than they should be. Only US shares are ' +
      'priced; a buy before a split is counted in the later day&rsquo;s shares.</p>', 'How these are measured')
    : '<div class="empty">Once you have trades on record, how you trade is measured here.</div>';
}
