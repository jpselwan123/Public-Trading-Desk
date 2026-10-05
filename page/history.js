/* ---------------- history (history.py) ----------------
   The account year by year, asked for on 28 Sep 2026 in place of the Overview's "put in, taken
   out since". Every figure is history.py's; a year whose value is not known says why, in
   history.py's words, never a guess. */
function histYear(y){
  const part = y.current ? 'to ' + fmtDay(y.end) : (y.part ? 'from ' + fmtDay(y.start) : '');
  return '<b>' + y.year + '</b>' + (part ? ' <span class="faint hist-part">' + part + '</span>' : '');
}
function histAgainst(diff){
  return diff == null ? '<span class="withheld">not known</span>'
    : money(Math.abs(diff)) + ' ' + (diff >= 0 ? 'ahead' : 'behind');
}
function renderHistory(){
  const H = DATA.history;
  $('histSub').textContent = H ? 'since ' + fmtDay(H.since) : '';
  $('histIncomeSub').textContent = H ? 'as ' + brokerName() + ' records them, each on its day' : '';
  if (!H){
    const none = '<div class="empty">' + (DATA.connected ? 'No money put in yet: each year shows here from the first deposit.'
      : 'Connect your account to see it year by year.') + '</div>';
    $('histBody').innerHTML = none; $('histIncome').innerHTML = ''; return;
  }
  const unknown = '<span class="withheld">not known</span>';
  const cell = (label, html) => '<td data-label="' + label + '">' + html + '</td>';
  const years = H.years.slice().reverse();                        // the latest first
  const T = H.total || {}, TM = T.market || {};
  // build_desk.money_weighted_return says which figure may be stated (`shown`); where none may, the note below says why
  const notStated = '<span class="withheld">not stated</span>';
  const stated = r => !r ? unknown : r.shown === 'annual' ? pct1(r.annual, true) + ' a year'
    : r.shown === 'period' ? pct1(r.period, true) : notStated;
  const whole = stated(T.return), wholeMarket = stated(TM.return);
  const wholeWhy = T.return && !T.return.shown ? '<div class="co-note"><b>All years:</b> ' +
    esc(sentence('no rate is stated, because ' + (T.return.why || 'not recorded'))) + '</div>' : '';
  $('histBody').innerHTML =
    '<div class="scroll-x"><table class="hist-tbl"><thead><tr><th>Year</th><th>Put in</th><th>Taken out</th>' +
      '<th>Earned</th><th>Return</th><th>S&amp;P 500, same money</th><th>Against it</th></tr></thead><tbody>' +
    years.map(y => {
      const m = y.market || {};
      return '<tr>' + cell('Year', histYear(y)) + cell('Put in', money(y.deposited)) + cell('Taken out', money(y.withdrawn)) +
        cell('Earned', y.earned == null ? unknown : money(y.earned, {sign:true})) +
        cell('Return', y.return != null ? pct1(y.return, true) : y.earned == null ? unknown : notStated) +
        cell('S&P 500, same money', m.return != null ? pct1(m.return, true) : m.value == null ? unknown : notStated) +
        cell('Against it', histAgainst(m.difference)) + '</tr>';
    }).join('') +
    '<tr class="hist-total">' + cell('Year', '<b>All years</b>') + cell('Put in', money(T.deposited)) +
      cell('Taken out', money(T.withdrawn)) + cell('Earned', T.earned == null ? unknown : money(T.earned, {sign:true})) +
      cell('Return', whole) + cell('S&P 500, same money', wholeMarket) +
      cell('Against it', histAgainst(TM.difference)) + '</tr>' +
    '</tbody></table></div>' +
    /* each year left without a figure, and why: history.py's own words */
    years.filter(y => y.why).map(y => '<div class="co-note"><b>' + y.year + ':</b> ' + esc(sentence(y.why)) + '</div>').join('') +
    wholeWhy +
    about('<p>Each year&rsquo;s return is money-weighted, the same way as the Overview&rsquo;s: what the year began with ' +
      'counts as put in on its first day, and each deposit and withdrawal on its own day. A part year is its own period, ' +
      'never stretched to a year. &ldquo;Earned&rdquo; is the value at the year&rsquo;s end, less its value at the start ' +
      'and what was put in: fees, taxes, dividends and currency moves are all in it.</p>' +
      '<p>The S&amp;P 500 column is what the same money would have done: what the year began with, and each deposit and ' +
      'withdrawal on its day, in and out of the S&amp;P 500 with its dividends, and no fees.</p>' +
      '<p>' + esc(brokerName().charAt(0).toUpperCase() + brokerName().slice(1)) + ' gives the account&rsquo;s value today, not on past days. So each past year&rsquo;s end is rebuilt from your ' +
      'record: the shares held that day, at that day&rsquo;s close, and the cash from every deposit, withdrawal, trade, ' +
      'dividend, interest payment and fee before it. Only US shares have daily closes in the desk.' +
      (H.check ? ' Rebuilt the same way to today, the account comes to ' + money(H.check.rebuilt) + ', and ' + esc(brokerName()) + ' says ' +
        money(H.check.actual) + (H.check.ok ? '.' : ': ' + esc(sentence(H.check.why || ''))) : '') + '</p>',
      'How each year is worked out');
  const years2 = years.map(y => '<tr>' + cell('Year', histYear(y)) + cell('Dividends', money(y.dividends)) +
      cell('Interest', money(y.interest)) + cell('Fees', money(y.fees)) +
      cell('Closed gain', money(y.closed_gain, {sign:true})) + cell('Trades', y.trades.toLocaleString()) + '</tr>').join('');
  $('histIncome').innerHTML =
    '<div class="scroll-x"><table class="hist-tbl"><thead><tr><th>Year</th><th>Dividends</th><th>Interest</th><th>Fees</th>' +
      '<th>Closed gain</th><th>Trades</th></tr></thead><tbody>' + years2 +
    '<tr class="hist-total">' + cell('Year', '<b>All years</b>') + cell('Dividends', money(T.dividends)) +
      cell('Interest', money(T.interest)) + cell('Fees', money(T.fees)) + cell('Closed gain', money(T.closed_gain, {sign:true})) +
      cell('Trades', (T.trades || 0).toLocaleString()) + '</tr></tbody></table></div>' +
    '<div class="co-note faint">Closed gain is ' + ((DATA.broker || {}).states_gains ? esc(brokerName()) + '&rsquo;s own figure'
      : 'worked out by the desk, as Trading 212 states it,') + ' on each sale, against your average cost.</div>';
}

/* ---------------- how rough the ride was (history.risk) ----------------
   Three plain figures over the weekly line, each beside the S&P 500's over the same weeks. Nothing here is a threshold
   and no figure is coloured as good or bad. A figure history.py could not stand behind says why, in its words. */
function renderRisk(){
  const H = DATA.history, R = H && H.risk;
  $('riskCard').hidden = !R || !!DATA.as_of;                       // a past day has no weekly line to speak of: the years above say why
  if (!R || DATA.as_of) return;
  if (R.why){
    $('riskSub').textContent = '';
    $('riskBody').innerHTML = '<div class="co-note faint">Not shown: ' + esc(sentence(R.why)) + '</div>';
    return;
  }
  $('riskSub').textContent = R.weeks.toLocaleString() + ' whole weeks, ' + fmtDay(R.since) + ' to ' + fmtDay(R.until);
  const F = R.fall, A = F.account, M = F.market, B = R.beta;
  const n2 = v => (v < 0 ? '−' : '') + Math.abs(v).toFixed(2);            // the page's minus, not a hyphen
  const fall = f => f.depth > 0 ? '−' + (f.depth * 100).toFixed(1) + '%' : 'none';
  const when = f => f.depth > 0 ? fmtDay(f.peak) + ' to ' + fmtDay(f.trough) + (f.back ? ', back to that level ' + fmtDay(f.back) : ', not back to that level yet') : 'never below an earlier week';
  const stat = (k, v, sub) => '<div class="stat"><div class="k">' + k + '</div><div class="v">' + v + '</div><div class="sv2">' + sub + '</div></div>';
  $('riskBody').innerHTML = '<div class="stats">' +
    stat('Worst fall', fall(A), esc(when(A)) + '<br>S&amp;P 500, same weeks: ' + fall(M) + ' (' + esc(when(M)) + ')') +
    stat('Weekly swing, as a year', (R.swing.account * 100).toFixed(1) + '%', 'S&amp;P 500, same weeks: ' + (R.swing.market * 100).toFixed(1) + '%') +
    stat('Moves with the S&amp;P 500', n2(B.slope), esc(B.level) + ' range ' + n2(B.low) + ' to ' + n2(B.high) +
         (B.explained == null ? '' : '<br>it explains ' + Math.round(B.explained * 100) + '% of the weekly moves')) +
    '</div>' +
    about('<p>Each week&rsquo;s return is the change in the account&rsquo;s value, less what was put in that week, over its value at the start ' +
      'plus what was put in, counted at ' + pct(R.flow_weight) + ' (Modified Dietz, a method the GIPS standards allow): a deposit lands on some day of the week, ' +
      'and that is the average share of it that was there. The S&amp;P 500 is the same money in the same index, treated the same way. Only whole weeks count, ' +
      'and a week whose deposits come to more than ' + pct(R.max_flow) + ', against its opening value, is left out, since the assumption matters most there.</p>' +
      '<p><b>Worst fall</b> is the deepest drop from a high to a later low in the weekly values; a fall inside a week is not seen. ' +
      '<b>Weekly swing</b> is the spread of the weekly returns, scaled to a year the usual way. <b>Moves with the S&amp;P 500</b> is the slope ' +
      'from the account&rsquo;s weekly returns against the S&amp;P 500&rsquo;s (a beta): 1 moves with it, 0.5 half as much, 0 not with it at all; ' +
      'the range is Student&rsquo;s t. These describe the weeks that were. They say nothing about which was better, and nothing about the weeks to come.</p>',
      'How these are worked out');
}
