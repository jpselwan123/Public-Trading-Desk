/* ---------------- research ---------------- */
const openRules = new Set();
// Each rule is a row that opens on click; which are open survives a redraw (the per-fund
// button redraws the list).
const openFolds = new Set();
const ruleOpen = (key, name, pill, gist) => '<details class="rule fold" data-fold="' + esc(key) + '"' +
  (openFolds.has(key) ? ' open' : '') + '><summary><span class="fold-t">' + name + '</span>' +
  '<span class="fold-g">' + pill + ' ' + gist + '</span></summary>';
function commonFails(rows){
  const counts = {};
  rows.forEach(({rule}) => (rule.failed || []).forEach(f => { counts[f] = (counts[f] || 0) + 1; }));
  return Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, 3);
}
function blocksLine(blocks){
  if (!blocks || !blocks.length) return '';
  return '<div class="blocks">' + blocks.map(b => '<span class="blk ' + (b.ahead ? 'up' : 'down') + '">' +
    fmtDay(b.from) + ' → ' + fmtDay(b.to) + ' · ' + (b.ahead ? 'ahead' : 'behind') + '</span>').join('') + '</div>';
}
function failLine(reasons){
  return (!reasons || !reasons.length) ? '' : '<div class="fails">Fails on: ' + esc(reasons.join(' · ')) + '</div>';
}
function renderResearch(){
  const R = DATA.research || {};
  const rules = R.by_rule || [];
  if (!rules.length){
    $('btVerdict').innerHTML = '<div class="empty">The rules are tested with the next company update.</div>';
    $('btRules').innerHTML = ''; $('btNote').textContent = ''; $('btSub').textContent = '';
    return;
  }
  const portfolioByKey = {};
  (R.portfolio || []).forEach(p => { portfolioByKey[p.key] = p; });
  /* Every figure in the method text comes from what research.py recorded. A missing
     one reads as not recorded — never as a number typed into this page (J-04). */
  const known = (v, show) => v == null ? 'not recorded' : show(v);
  const level = R.confidence != null ? Math.round(R.confidence * 100) + '% range' : 'range';
  const sectors = (R.sector_funds || []).length;
  $('btSub').textContent = R.tested + ' tests · ' + (R.universe || []).length + ' funds' +
    ((R.event_sample || []).length ? ' and ' + R.event_sample.join(', ') : '') + ' · held-out years only';
  const power = R.power || {};
  // the honest headline is the corrected figure: a rule has to clear its family's
  // threshold, not just p < 0.05, so that is the size this search would actually flag
  const mdeRow = Object.values(power.mde || {}).sort((a, b) => b.years - a.years)[0];
  const detectable = mdeRow && !mdeRow.corrected_above && mdeRow.corrected_edge
    ? pct(mdeRow.corrected_edge)
    : (power.largest_tested ? 'more than ' + pct(power.largest_tested) : null);
  $('btVerdict').innerHTML = '<div class="verdict">' + (R.clears
    /* not a rate: a count of tests, each already corrected for multiple testing (q-values) */
    ? '<b>' + R.clears + ' of ' + R.tested + ' tests</b> showed an edge this test could detect, in years never used to choose anything.'
    : '<b>No rule showed an edge this test could detect.</b> ' +
      (detectable
        ? 'An edge must be about <b>' + detectable + ' a year</b> before this search would ' +
          'flag it once the correction for testing many rules is applied. No plausible ' +
          'sector-rotation edge is that large, so this search could not have found one.'
        : 'How small an edge it could find has not been measured — run power.py.')) + '</div>';

  const kv2 = (k, v, cls) => '<div><div class="k">' + k + '</div><div class="v ' + (cls || '') + '">' + v + '</div></div>';

  $('btRules').innerHTML = rules.map(rule => {
    const pf = portfolioByKey[rule.key];
    const open = openRules.has(rule.key);

    if (pf){
      const t = pf.test;
      return ruleOpen(rule.key, esc(rule.name),
          '<span class="verdict-pill' + (pf.clears ? ' pass' : '') + '">' + (pf.clears ? 'clears' : 'does not clear') + '</span>',
          pct1(t.excess, true) + ' a year against holding all') +
        '<div class="rule-why">' + esc(rule.why) + ' One portfolio across the ' + sectors + ' sectors, changed monthly, against holding all of them.</div>' +
        '<div class="rule-why" style="margin-top:6px">Judged as a <b>' +
          (rule.claim === 'risk' ? 'risk-reducing' : 'return-improving') + '</b> rule, which is what its source claims.</div>' +
        '<div class="rule-grid">' +
          kv2('Edge over holding all', pct1(t.excess, true) + ' a year' +
              (t.excess_low != null ? '<div class="sv2" style="font-size:12.5px">' + level + ' ' +
                pct1(t.excess_low, true) + ' to ' + pct1(t.excess_high, true) + '</div>' : '')) +
          kv2('Return a year', pct1(t.annual, true) + ' vs ' + pct1(t.hold_annual, true)) +
          kv2('Return per unit of risk', (t.sharpe != null ? t.sharpe.toFixed(2) : '–') + ' vs ' + (t.hold_sharpe != null ? t.hold_sharpe.toFixed(2) : '–')) +
          kv2('Worst drop', pct1(t.worst_drop) + ' vs ' + pct1(t.hold_worst_drop)) +
          kv2('Trades', t.trades) +
          kv2('Luck check', t.q != null ? 'q ' + t.q.toFixed(2) : '–') +
        '</div>' + blocksLine(pf.blocks) + failLine(pf.failed) +
      '</details>';
    }

    const unit = rule.sample === 'event_sample' ? 'share' : 'fund';     // rule H runs on shares, not funds
    const rows = (R.results || []).map(res => ({res, rule: (res.rules || []).find(x => x.key === rule.key)}))
                                  .filter(x => x.rule && x.rule.test);
    return ruleOpen(rule.key, esc(rule.name),
        '<span class="verdict-pill' + (rule.clears ? ' pass' : '') + '">' +
          /* not a rate: a count of tests, each already corrected for multiple testing (q-values) */
          (rule.clears ? rule.clears + ' of ' + rule.tested + ' cleared' : 'does not clear') + '</span>',
        pct1(rule.median_excess, true) + ' a year against holding') +
        '<div class="rule-why">' + esc(rule.why) +
          (rule.sample === 'event_sample' && (R.event_sample || []).length ? ' Tested only on ' + esc(R.event_sample.join(', ')) +
            ', the share' + ((R.event_sample || []).length === 1 ? '' : 's') + ' it was first run on, fixed so that following a company ' +
            'cannot change the test. Not chosen in advance, so weaker evidence than the funds.' : '') +
        '</div>' +
      '<div class="rule-grid">' +
        kv2('Judged as', rule.claim === 'risk' ? 'Risk-reducing' : 'Return-improving') +
        kv2('Edge over holding', pct1(rule.median_excess, true) + ' a year') +
        /* not a rate: the sector funds move together, so this is not that many separate draws and an interval assuming it would be too narrow; each fund's uncertainty is its bootstrap interval and corrected q, shown per fund */
        kv2('Better than holding', rule.positive + ' of ' + rule.tested) +
        kv2('Return per unit of risk', rule.median_sharpe != null ? rule.median_sharpe.toFixed(2) : '–') +
        kv2('Holding it instead', rule.median_hold_sharpe != null ? rule.median_hold_sharpe.toFixed(2) : '–') +
        kv2('Best ' + unit, rule.best ? esc(rule.best.ticker) + ' ' + pct1(rule.best.excess, true) : '–') +
        kv2('Worst ' + unit, rule.worst ? esc(rule.worst.ticker) + ' ' + pct1(rule.worst.excess, true) : '–') +
      '</div>' +
      failLine(rule.clears ? [] : commonFails(rows)) +
      '<button class="btn detail-toggle" data-rule="' + esc(rule.key) + '">' +
        (open ? 'Hide every ' : 'Show every ') + unit + '</button>' +
      '<div class="per-ticker' + (open ? ' open' : '') + '">' +
        '<div class="pt-row head"><span>' + (unit === 'share' ? 'Share' : 'Fund') + '</span><span class="num">Held-out edge</span><span class="num">Earlier years</span>' +
          '<span class="num">Ups and downs</span><span class="num">Trades</span><span class="num">Luck check</span>' +
          '<span class="num">Stretches ahead</span></div>' +
        rows.map(({res, rule: r}) => {
          const t = r.test, tr = r.train, blocks = r.blocks || [];
          return '<div class="pt-row"><span><span class="tk">' + esc(res.ticker) + '</span> ' +
            '<span class="nm">' + esc(res.name || '') + '</span></span>' +
            '<span class="num"><span class="lbl">Held-out edge</span>' + pct1(t.excess, true) +
              (t.excess_low != null ? '<div class="faint" style="font-size:12px">' + pct1(t.excess_low, true) + ' to ' + pct1(t.excess_high, true) + '</div>' : '') + '</span>' +
            '<span class="num"><span class="lbl">Earlier years</span>' + (tr ? pct1(tr.excess, true) : '–') + '</span>' +
            '<span class="num"><span class="lbl">Ups and downs</span>' + (t.vol != null ? pct1(t.vol) : '–') + '</span>' +
            '<span class="num"><span class="lbl">Trades</span>' + t.trades + '</span>' +
            '<span class="num"><span class="lbl">Luck check</span>' + (t.q != null ? 'q ' + t.q.toFixed(2) : '–') + '</span>' +
            /* not a rate: the pre-registered consistency condition, judged as written */
            '<span class="num"><span class="lbl">Stretches ahead</span>' + (blocks.length ? blocks.filter(b => b.ahead).length + ' of ' + blocks.length : '–') + '</span>' +
          '</div>';
        }).join('') +
      '</div>' +
    '</details>';
  }).join('');

  $('btWindow').textContent = R.test_from ? 'held-out years: ' + fmtDay(R.test_from) + ' → ' + fmtDay(R.test_to) : '';
  $('btNote').innerHTML = [
    '<b>The funds are fixed in code</b> — the ' + sectors + ' sector funds plus the market — so no rule is judged on shares picked because they already rose. The set does change over time: the property fund was split out in 2015 and the communications fund in 2018, so this is today\'s map of the market applied backwards.',
    '<b>The rules were written down before the search</b> (PREREGISTRATION.md), with their parameters and the pass mark fixed in advance.',
    /* not a rate: a share of each history */
    '<b>Only the last ' + known(R.test_share, v => Math.round(v * 100) + '%') + ' of each history counts.</b> The earlier years are there to look at; the numbers reported come from years the rule was never inspected on.',
    '<b>Costs:</b> ' + known(R.cost, v => (v * 100).toFixed(2) + '%') + ' on the size of every change, and money out of the market earns the 3-month Treasury bill rate.',
    '<b>Luck check:</b> ' + known(R.bootstrap_rounds, v => v.toLocaleString()) + ' resamples in blocks averaging ' + known(R.block_days, v => v) +
      ' days (Politis &amp; Romano, 1994), then q-values within each family of tests (Benjamini &amp; Hochberg, 1995).',
    '<b>How many tests are really separate:</b> ' + (Object.entries(R.families || {}).length
      ? Object.entries(R.families).map(([name, f]) => esc(name.replace('_', ' ')) + ' ' + f.tests +
          ' tests \u2248 <b>' + f.effective + '</b> independent (average overlap ' + f.average_correlation + ')').join(' · ') +
        '. Sector funds move together and the trend rules are variations on one signal, so correcting as if all were separate would throw away power. '
        + 'These counts are what the correction divides by, not a note printed beside it.'
      : 'not measured.'),
    '<b>What this test can see:</b> ' + (detectable
      /* not a rate: the design's detection rate, from power.py */
      ? 'an edge of ' + detectable + ' a year is found about ' + known(power.target_power, v => Math.round(v * 100) + '%') +
        ' of the time on the longer window; smaller edges are missed more often than not, which is why every figure carries a ' + level + '.'
      : 'not yet measured — run power.py.') + (power.trials ? ' Measured over ' + power.trials + ' simulated runs per size.' : ''),
    '<b>Two kinds of rule, judged differently:</b> a return-improving rule must beat holding\'s return; a risk-reducing one (Faber\'s trend filter, volatility scaling) must cut the worst fall instead, because its source paper claims a smaller fall at a similar return, not a bigger one. Which track a rule is in comes from its paper, never from its results.',
    '<b>To clear, all of these must hold:</b> its own track\'s test, q below ' + known(R.q_limit, v => v.toFixed(2)) +
      ', ahead in more than half the funds, return per unit of risk at least matching holding, and ahead in at least ' +
      /* not a rate: the pre-registered consistency condition, judged as written */
      known(R.min_blocks_positive, v => v) + ' of ' + known(R.walk_blocks, v => v) + ' stretches.',
  ].map(t => '<div style="margin-bottom:7px">' + t + '</div>').join('');
}

$('btRules').addEventListener('toggle', e => {
  const key = e.target.dataset && e.target.dataset.fold;
  if (key) e.target.open ? openFolds.add(key) : openFolds.delete(key);
}, true);                                       // toggle does not bubble; caught on the way down
$('btRules').addEventListener('click', e => {
  const b = e.target.closest('[data-rule]'); if (!b) return;
  const key = b.dataset.rule;
  openRules.has(key) ? openRules.delete(key) : openRules.add(key);
  safe(renderResearch);
});

/* The rating's own record: every rating logged for a covered or held company, scored
   against the market once the time has passed (rating.record). */
function recordLines(rec){
  const scored = (rec.rows || []).filter(x => x.n);
  if (!scored.length) return '';
  return scored.map(x => '<div class="finding" style="margin-top:10px"><b>' + esc(x.label) + '</b>, after ' + esc(x.after) + ': ' +
    'beat the market ' + ofCount(x.beat) + ' ' + chanceText(x.beat) + ' At the middle rating it was ' + vsMarket(x.lead) + '.</div>').join('');
}
function renderRatingRecord(){
  const R = DATA.rating || {}, rec = R.record || {}, yours = R.record_yours || {};
  $('rtSub').textContent = R.rated ? R.rated.toLocaleString() + ' US companies rated' +
    (R.built ? ' · on the SEC filings stored ' + fmtDay(R.built) : '') : '';
  if (!R.rated){
    $('rtBody').innerHTML = '<div class="empty">Nothing rated yet: ' + esc(R.why_none || 'no universe of SEC filers is stored') + '.</div>';
    return;
  }
  const first = ((rec.rows || yours.rows || [])[0] || {}).after || '';
  const anyScored = [rec, yours].some(r => (r.rows || []).some(x => x.n));
  $('rtBody').innerHTML =
    '<div class="wd-h">The fixed sample: companies nobody chose</div>' +
    '<div class="co-note">' + (rec.logged ? rec.logged + ' ratings logged since ' + fmtDay(rec.first) + '.'
      : 'None logged yet: the sample is drawn, priced and rated with the company updates.') + '</div>' +
    recordLines(rec) +
    '<div class="wd-h" style="margin-top:16px">The companies you cover or hold</div>' +
    '<div class="co-note">' + (yours.logged ? yours.logged + ' logged since ' + fmtDay(yours.first) + '.'
      : 'None logged yet: the first are logged with the next company update.') + '</div>' +
    recordLines(yours) +
    (anyScored ? '' : '<div class="empty">Nothing scored yet: a rating is first scored ' + esc(first) + ' after it is given.</div>') +
    ((yours.recent || []).length ? '<div class="wd-h" style="margin-top:14px">Logged most recently</div>' +
      yours.recent.map(e => '<div class="br-row"><span>' + fmtDay(e.date) + ' · <b>' + esc(e.ticker) + '</b> ' + esc(e.label) + '</span>' +
        '<span class="num">last close ' + usd2(e.close) + '</span></div>').join('') : '') +
    about('<p>Each rating is logged on the day it is given or changes, with the latest close, and compared with the S&amp;P 500 ' +
      'from the first close after that day. The fixed sample is the fair test: companies drawn at random from the NYSE once, ' +
      'so the record is not about the ones you chose. Only ratings given under the rating&rsquo;s present definition are scored' +
      /* not a rate: a count of log entries kept apart, not a sample */
      ((rec.earlier || yours.earlier) ? '; ' + ((rec.earlier || 0) + (yours.earlier || 0)) + ' given under an earlier one stay in the log, unscored' : '') + '.' +
      (rec.level ? ' Every range is at ' + esc(rec.level) + ', because these records are read side by side.' : '') +
      ' A premium measured over years in thousands of companies shows slowly in a few hundred: expect the ranges to stay wide for a long time.' +
      '</p><p>' + esc(R.limits || '') + '</p>', 'How the record is kept, and its limits');
}


/* ---------------- the desk's Buy list (rating.buy_list) ----------------
   The companies the rating places in its top third, highest first, each a click from being
   followed. A list to look through; what the papers measured is how such a group did on
   average, held for a year, not how any one company will. */
let blShown = 25;                  // the first twenty-five, the rest a click away: a presentation limit
function renderBuyList(){
  const R = DATA.rating || {}, list = R.buy_list || [];
  $('buyCard').hidden = !!DATA.as_of || !list.length;
  if (!list.length) return;
  /* not a rate: a count of companies in a ranking, every one of them counted */
  $('blSub').textContent = list.length.toLocaleString() + ' companies rated Buy, highest place first';
  const row = c => '<tr><td><span class="tk">' + esc(c.ticker) + '</span> <span class="nm">' + esc(c.name) + '</span>' +
      /* not a rate: how many of the rating's themes this company rests on, a census */
      '<span class="bl-ind">' + (c.industry ? esc(c.industry) + ' · ' : '') + 'on ' + c.measures + ' of ' + (R.themes || []).length + ' themes</span></td>' +
    '<td>' + ratingTag({label: 'Buy', place: c.place}) + '</td>' +
    '<td>' + followButton(c.ticker) + '</td></tr>';
  $('blList').innerHTML = '<div class="scroll-x"><table class="sc-tbl bl-tbl"><thead><tr><th>Company</th>' +
      '<th>Place</th><th></th></tr></thead><tbody>' +
      list.slice(0, blShown).map(row).join('') + '</tbody></table></div>' +
    (list.length > blShown ? '<button class="btn wide" id="blMore">Show ' + Math.min(25, list.length - blShown) + ' more</button>' : '') +
    about('<p>The companies the desk&rsquo;s rating places in its top third: each ranked on the published measures ' +
      'against NYSE-listed companies, each theme&rsquo;s places averaged, the themes averaged with equal weights, and the ' +
      'average placed once more. A company without a price in the desk rests on the filing measures alone; the line under ' +
      'each name says on how many themes. What the papers found is that groups ' +
      'of companies ranked this way did better on average than those ranked low, held for a year. It is not a forecast for one ' +
      'company, and published effects shrink.</p><p>' + esc(R.limits || '') + '</p>', 'How the list is made, and its limits');
}
$('blList').addEventListener('click', e => {
  if (e.target.id === 'blMore'){ blShown += 25; return safe(renderBuyList); }
  const pick = e.target.closest('[data-follow]');
  if (pick) follow(pick.dataset.follow, () => safe(renderBuyList));
});
