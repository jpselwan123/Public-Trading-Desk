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
  const whole = T.return ? (T.return.days >= 365 ? pct1(T.return.annual, true) + ' a year' : pct1(T.return.period, true)) : unknown;
  const wholeMarket = TM.return ? (TM.return.days >= 365 ? pct1(TM.return.annual, true) + ' a year' : pct1(TM.return.period, true)) : unknown;
  $('histBody').innerHTML =
    '<div class="scroll-x"><table class="hist-tbl"><thead><tr><th>Year</th><th>Put in</th><th>Taken out</th>' +
      '<th>Earned</th><th>Return</th><th>S&amp;P 500, same money</th><th>Against it</th></tr></thead><tbody>' +
    years.map(y => {
      const m = y.market || {};
      return '<tr>' + cell('Year', histYear(y)) + cell('Put in', money(y.deposited)) + cell('Taken out', money(y.withdrawn)) +
        cell('Earned', y.earned == null ? unknown : money(y.earned, {sign:true})) +
        cell('Return', y.return == null ? unknown : pct1(y.return, true)) +
        cell('S&P 500, same money', m.return == null ? unknown : pct1(m.return, true)) +
        cell('Against it', histAgainst(m.difference)) + '</tr>';
    }).join('') +
    '<tr class="hist-total">' + cell('Year', '<b>All years</b>') + cell('Put in', money(T.deposited)) +
      cell('Taken out', money(T.withdrawn)) + cell('Earned', T.earned == null ? unknown : money(T.earned, {sign:true})) +
      cell('Return', whole) + cell('S&P 500, same money', wholeMarket) +
      cell('Against it', histAgainst(TM.difference)) + '</tr>' +
    '</tbody></table></div>' +
    /* each year left without a figure, and why: history.py's own words */
    years.filter(y => y.why).map(y => '<div class="co-note"><b>' + y.year + ':</b> ' + esc(sentence(y.why)) + '</div>').join('') +
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
