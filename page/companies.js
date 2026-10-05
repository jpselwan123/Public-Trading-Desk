/* ---------------- companies ---------------- */
function signedScore(v, places){ return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(places); }

function ratingBlock(a){
  if (!a) return '';
  const c = a.counts, total = a.analysts || 1;
  const seg = (cls, n) => n ? '<span class="' + cls + '" style="width:' + (n / total * 100).toFixed(1) + '%"></span>' : '';
  const key = (cls, name, n) => n ? '<span><i class="' + cls + '"></i>' + name + ' ' + n + '</span>' : '';
  const sells = c.sell + c.strongSell;
  const drift = a.direction && a.direction_months
    ? (a.direction === 'unchanged' ? 'unchanged from ' : esc(a.direction) + ' than ') + a.direction_months + ' months ago' : '';
  return foldOpen('What analysts say', a.analysts + ' analysts' + (drift ? ' · ' + drift : '')) +
    '<div class="rate-top"><span class="rate-verdict">' + esc(a.verdict) + '</span>' +
      '<span class="faint" style="font-size:13px">' + a.analysts + ' analysts · ' +
      (a.direction && a.direction_months
        ? (a.direction === 'unchanged' ? 'unchanged from ' : esc(a.direction) + ' than ') + a.direction_months + ' months ago' +
          (a.score_places != null && a.score != null && a.score_before != null
            ? ' (' + signedScore(a.score_before, a.score_places) + ' → ' + signedScore(a.score, a.score_places) + ' on a −2 to +2 scale)' : '') + ' · '
        : '') +
      fmtDay(a.as_of) + '</span></div>' +
    '<div class="rate-bar">' + seg('sb', c.strongBuy) + seg('b', c.buy) + seg('h', c.hold) + seg('s', c.sell) + seg('ss', c.strongSell) + '</div>' +
    '<div class="rate-key">' + key('sb','Strong buy',c.strongBuy) + key('b','Buy',c.buy) + key('h','Hold',c.hold) +
      key('s','Sell',c.sell) + key('ss','Strong sell',c.strongSell) + '</div>' +
    about(
      /* not a rate: a census of today's published ratings, not a sample */
      (sells === 0 ? 'Not one analyst says sell — ' : 'Only ' + sells + ' of ' + a.analysts + ' say sell — ') +
      'which is normal. Ratings skew to buy, and following the consensus did not beat the market after costs (Barber, Lehavy, McNichols &amp; Trueman, 2001). Watch the direction of change, not the label.',
      'Why analysts rarely say sell') +
  '</details>';
}

function pc(v, places){ return v == null ? '–' : (v * 100).toFixed(places == null ? 1 : places) + '%'; }
function nm(v, places){ return v == null ? '–' : v.toFixed(places == null ? 2 : places); }

/* ---------------- the desk's rating (rating.py; decided 25 Sep 2026) ----------------
   The label and every part of how it was reached come from rating.py; the page words it. */
/* the label with its place beside it (0 to 100; Buy from R.buy_from, Sell below R.sell_below),
   so a Hold near either edge reads as one */
function ratingN(r){ return r.place == null ? '' : ' <span class="rating-n">' + Math.round(r.place) + '</span>'; }
function ratingTag(r){ return r && r.label ? '<span class="rating-tag">' + esc(r.label) + ratingN(r) + '</span>' : ''; }
function ratingPill(r){ return r && r.label ? '<span class="pill rating-pill">Desk rating <b>' + esc(r.label) + '</b>' + ratingN(r) + '</span>' : ''; }
/* not a rate: a place in a ranking of every rated company */
function ratingPlace(r){ return 'ranks above ' + Math.round(r.place) + '% of ' + (r.rated_among || 0).toLocaleString() +
  (r.breakpoints === 'NYSE' ? ' NYSE companies' : ' US companies'); }
/* Where the rating's cut-offs fall and where this company sits between them: the cut-offs are
   rating.py's (R.buy_from, R.sell_below), the mark its place. One colour for every stretch: a
   place is a position, not a verdict on the company. */
function ratingScale(r){
  const R = DATA.rating || {};
  if (r.place == null || R.buy_from == null || R.sell_below == null) return '';
  const at = Math.max(0, Math.min(100, r.place)), buy = Math.round(R.buy_from), sell = Math.round(R.sell_below);
  return '<div class="rt-scale" role="img" aria-label="Ranks above ' + Math.round(r.place) + '%: Sell below ' + sell +
      '%, Buy from ' + buy + '%">' +
    '<div class="rt-bar"><span style="width:' + R.sell_below + '%"></span><span style="width:' + (R.buy_from - R.sell_below) + '%"></span>' +
      '<span style="width:' + (100 - R.buy_from) + '%"></span><i class="rt-mark" style="left:' + at.toFixed(1) + '%"></i></div>' +
    '<div class="rt-ticks faint"><span style="left:' + R.sell_below + '%">' + sell + '%</span>' +
      '<span style="left:' + R.buy_from + '%">' + buy + '%</span></div>' +
    '<div class="rt-cuts faint"><span style="width:' + R.sell_below + '%">Sell</span>' +
      '<span style="width:' + (R.buy_from - R.sell_below) + '%">Hold</span><span style="width:' + (100 - R.buy_from) + '%">Buy</span></div>' +
  '</div>';
}
/* Each theme's place, the four the rating averages with equal weights (rating.THEMES): what
   holds the average where it is. */
function ratingThemes(r){
  const R = DATA.rating || {}, T = r.themes || {};
  const known = (R.themes || []).filter(t => T[t] != null);
  if (!known.length) return '';
  return '<div class="co-note">Its themes: ' + (R.themes || []).map(t => esc(t) + ' ' +
    (T[t] == null ? '<span class="withheld">not read</span>' : Math.round(T[t]) + '%')).join(' · ') +
    '. Averaged with equal weights.</div>';
}
function deskRatingBlock(r){
  const R = DATA.rating || {};
  if (!r) return '';
  if (!r.label) return foldOpen('The desk&rsquo;s rating', 'not rated') +
    '<div class="co-note faint">' + esc(sentence('Not rated: ' + r.why_not)) + '</div></details>';
  const S = R.sample, waiting = !!(S && !S.ready);
  return foldOpen('The desk&rsquo;s rating: ' + esc(r.label), ratingPlace(r)) +
    ratingScale(r) + ratingThemes(r) +
    '<table class="sc-tbl peer-tbl rating-tbl"><thead><tr><th style="text-align:left">Measure</th>' +
      ['This company', 'Ranks above', 'Better when', 'Theme'].map(h => '<th style="text-align:right">' + h + '</th>').join('') +
      '<th style="text-align:left">Found by</th></tr></thead><tbody>' +
      (R.factors || []).map(f => {
        const v = (r.factors || {})[f.name] || {};
        return '<tr><td style="text-align:left" data-label="Measure">' + esc(f.label) + '</td>' +
          '<td style="text-align:right" data-label="This company">' + formatMeasure(f.name, v.value) + '</td>' +
          '<td style="text-align:right" data-label="Ranks above">' + (v.place == null ? (f.needs_price ? (v.value == null ? 'no price' : waiting ? 'sample being priced' : 'no sample yet') : 'not filed')
            : Math.round(v.place) + '%') + '</td>' +
          '<td style="text-align:right" data-label="Better when">' + esc(f.better) + '</td>' +
          '<td style="text-align:right" data-label="Theme">' + esc(f.theme) + '</td>' +
          '<td class="sc-sector" data-label="Found by">' + esc(f.source) + '</td></tr>';
      }).join('') + '</tbody></table>' +
    /* not a rate: how many of the sample are priced so far against the count it waits for, a census */
    (waiting ? '<div class="co-note faint">Value and momentum are placed once ' + S.ready_at + ' of the sample&rsquo;s ' + S.size +
      ' companies are priced; ' + S.priced + ' are so far. Tiingo&rsquo;s free key prices about ' + S.per_hour +
      ' companies an hour while the desk is open, the companies you follow first.</div>' : '') +
    about('<p>The measures are grouped into the themes ' + esc(R.theme_source || '') + ' found the published findings fall into; ' +
      'of their thirteen themes, these four carry significant weight in the best combination of all of them, and each measure ' +
      'here also held when Hou, Xue &amp; Zhang (2020) re-tested 452 findings. ' + (R.breakpoints === 'NYSE'
        ? 'Each place is against the NYSE-listed companies, as the papers set their breakpoints, so thousands of tiny companies do not crowd the ends (Fama &amp; French 2008)' +
          /* not a rate: the date of a list, not a count */
          (R.exchange_list && R.exchange_list.updated_at ? '; the SEC&rsquo;s exchange list of ' + fmtDay(R.exchange_list.updated_at.slice(0, 10)) : '') + '. '
        : 'Each place is against every US filer: the exchange list, which would set the breakpoints on NYSE companies as the papers do, is not stored yet (it comes with the next company update). ') +
      'A theme&rsquo;s place is its measures&rsquo; average; the themes are averaged with equal weights, and the average placed once more against the companies resting on as many themes: ' +
      'above ' + Math.round(R.buy_from) + '% is Buy, below ' + Math.round(R.sell_below) + '% is Sell, and between is Hold; the number beside a label is that place. ' +
      'Thirds, because the study builds every factor from the top third of companies against the bottom third. ' +
      /* not a rate: the rule for rating a company at all, not a sample */
      'A company needs ' + R.min_themes + ' of the ' + (R.themes || []).length + ' themes to be rated.</p>' +
      ((R.left_out || []).length ? '<p>Left out: ' + R.left_out.map(x => esc(x.name) + ', because ' + esc(x.why)).join('; ') + '.</p>' : '') +
      '<p>Value and momentum need a share price, and the desk can price a few hundred companies a month, not every NYSE one. ' +
      'So they are placed against a fixed random sample of NYSE companies, drawn once' +
      /* not a rate: how many of the sample have a price yet, a census */
      (R.sample && R.sample.size ? ' (' + R.sample.size + ' of them, ' + R.sample.priced + ' priced so far)' : ' with the next company update') +
      '. A company without a price is rated on the filing measures alone.</p><p>' + esc(R.limits) +
      ' The record so far is on the Research tab.</p>', 'How it is made, and its limits') + '</details>';
}

/* ---------------- the price against the company's own history (value.own_history) ---------------- */
function peLine(points, now){
  if (!points || points.length < 2) return '';
  const vs = points.map(p => p.pe).concat([now]), lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs);
  const W = 600, H = 70, x = i => i / (points.length - 1) * W, y = v => H - 4 - (v - lo) / ((hi - lo) || 1) * (H - 8);
  const month = m => MONTHS[+m.slice(5, 7) - 1] + ' ' + m.slice(2, 4);
  return '<svg class="pe-line" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' +
    '<line class="pe-now" x1="0" x2="' + W + '" y1="' + y(now).toFixed(1) + '" y2="' + y(now).toFixed(1) + '"/>' +
    '<polyline points="' + points.map((p, i) => x(i).toFixed(1) + ',' + y(p.pe).toFixed(1)).join(' ') + '"/></svg>' +
    '<div class="pe-axis faint"><span>' + month(points[0].month) + '</span><span>the dashed line is today</span>' +
    '<span>' + month(points[points.length - 1].month) + '</span></div>';
}
/* Where a price to earnings sits among its own months, in words: at the ends, "at its lowest"
   or "at its highest", never "higher than 0%". `span` names the months, or is left out. */
/* not a rate: a place among the company's own months, every one of them counted */
function pePlace(place, span){
  const p = Math.round(place);
  if (p <= 0) return 'at its lowest' + (span ? ' in ' + span : '');
  if (p >= 100) return 'at its highest' + (span ? ' in ' + span : '');
  /* not a rate: a place among the company's own months, every one of them counted */
  return 'higher than ' + p + '%' + (span ? ' of ' + span : '');
}
function peHistoryBlock(h){
  if (!h) return '';
  const F = v => formatMeasure('price_to_eps_12m', v), title = 'Price against its own history';
  if (h.why_not) return foldOpen(title, 'not available') + '<div class="co-note faint">' + esc(sentence(h.why_not)) + '</div></details>';
  /* not a rate: a place among the company's own months, every one of them counted */
  return foldOpen(title, F(h.now) + ' now · ' + pePlace(h.place, 'its last ' + h.years + ' years')) +
    peLine(h.points, h.now) +
    /* not a rate: the company's own months, every one of them counted */
    '<div class="co-note" style="margin-top:10px">' + esc(measureLabel('price_to_eps_12m')) + ', month by month over the last ' +
      h.years + ' years: from <b>' + F(h.low) + '</b> to <b>' + F(h.high) + '</b>, with a median of <b>' + F(h.median) +
      '</b>. Today&rsquo;s <b>' + F(h.now) + '</b> is ' + pePlace(h.place, 'those ' + h.months + ' months') + '.</div>' +
    about('Each month: that day&rsquo;s close over the earnings per share for the twelve months ' +
      'filed by then, never figures filed later, so every month is measured the same way. A month without a profit is left out. ' +
      'The price to earnings under &ldquo;Price compared with profit and assets&rdquo; divides the market value by the latest full ' +
      'year&rsquo;s profit instead, so the two can differ. The ' + h.years + ' years are the desk&rsquo;s choice: long enough for a ' +
      'run of results, short enough to be the company it is now.') + '</details>';
}

/* Everything the desk knows about one company, from context.py. Each block is
   skipped rather than faked when the filings do not support it. */
function contextBlock(x){
  if (!x) return '';
  if (x.why_not) return foldOpen('Compared with other companies', 'not available') +
    '<div class="co-note faint">' + esc(sentence(x.why_not)) + '</div></details>';
  return scoreBlock(x) + peerBlock(x) + valueBlock(x) + forecastBlock(x);
}

function scoreBlock(x){
  const f = x.piotroski, a = x.altman;
  if (!f && !a) return '';
  const mark = v => v === true ? '<span style="color:var(--ink)">yes</span>'
                  : v === false ? '<span style="color:var(--ink-faint)">no</span>'
                  : '<span class="faint">unknown</span>';
  /* not a rate: Piotroski's score is a count of signals, not a sample of anything */
  const gist = x.models_apply === false ? 'not used for this kind of company'
    : [f ? 'Piotroski ' + f.score + ' of ' + f.signals.length : '',
       a && a.score != null ? 'Altman ' + nm(a.score) + (a.band ? ', ' + esc(a.band) + ' zone' : '') : ''].filter(Boolean).join(' · ');
  let html = foldOpen('Financial health scores', gist) +
    (x.models_apply === false
      ? '<div class="co-note" style="margin-bottom:10px;color:var(--warn)">' + esc(x.models_note) + '</div>'
      : '');
  /* Out of all nine, always: "5 of 8" made the score incomparable between companies
     that could compute different numbers of signals (J-08). */
  /* not a rate: Piotroski's score is a count of signals, not a sample of anything */
  if (f) html += '<div class="co-note"><b>Piotroski F-score ' + f.score + ' of ' + f.signals.length + '</b>' +
    (f.complete ? '' : ' <span class="faint">· ' + f.unknown.length + ' unknown</span>') +
    (f.prior_year ? '<div class="faint" style="margin-top:4px">' + esc(sentence(f.prior_year)) + '.</div>' : '') +
    '<div style="margin-top:8px;line-height:1.9">' +
    f.signals.map(s => mark(s.passed) + ' &middot; ' + esc(s.says)).join('<br>') + '</div></div>';
  if (a && a.score != null) html += '<div class="co-note" style="margin-top:10px">' +
    '<b>Altman Z&Prime; ' + nm(a.score) + '</b>' +
    (a.band ? ' — ' + esc(a.band) + ' zone' : ' — <span class="faint">no band</span>') +
    (a.why_not ? '<br><span class="faint">' + esc(sentence(a.why_not)) + '</span>' : '') + '</div>';
  else if (a && a.missing && a.missing.length) html += '<div class="co-note faint" style="margin-top:10px">' +
    'Altman Z&Prime; needs ' + a.missing.map(esc).join(' and ') + ', which this company does not file.</div>';
  return html + '</details>';
}

/* Under sectors.RANK_BELOW companies a percentile claims more precision than the data
   has, so the position is stated instead (J-06). Highest is a position, not praise. */
function standing(m, rankBelow){
  if (rankBelow != null && m.of != null && m.of < rankBelow){
    /* not a rate: a rank among every peer */
    if (m.rank === 1) return 'highest of ' + m.of;
    if (m.rank === m.of) return 'lowest of ' + m.of;
    return ordinal(m.rank) + ' highest of ' + m.of;
  }
  return ordinal(Math.round(m.percentile)) + ' percentile';
}
function ordinal(n){ const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }

function peerBlock(x){
  const ind = x.industry, st = x.peer_standing;
  if (!ind) return '';
  let html = foldOpen('Compared with its industry', esc(ind.division || 'No industry assigned') + ' · ' + ind.peers + ' peers') +
    '<div class="co-note">' + esc(ind.division || 'No industry assigned') +
    (ind.sic ? ' &middot; SIC ' + ind.sic : '') + ' &middot; ' + ind.peers + ' peers</div>';
  if (!st) return html + '<div class="co-note faint" style="margin-top:8px">' + esc(ind.why) + '</div></details>';
  const rows = Object.entries(st).filter(([, m]) => m.percentile != null);
  if (!rows.length) return html + '</details>';
  html += '<div style="margin-top:10px"><table class="sc-tbl peer-tbl"><thead><tr>' +
    '<th style="text-align:left">Measure</th>' +
    ['This company', 'Peer median', 'Where it stands', 'Reported by'].map(h => '<th style="text-align:right">' + h + '</th>').join('') +
    '</tr></thead><tbody>' +
    rows.map(([name, m]) =>
      '<tr><td style="text-align:left" data-label="Measure">' + esc(measureLabel(name)) +
        (ind.figures_from ? ' <span class="faint">(' + esc(ind.figures_from.replace(/^CY/, '')) + ' filing)</span>' : '') + '</td>' +
      '<td style="text-align:right" data-label="This company">' + formatMeasure(name, m.value) + '</td>' +
      '<td style="text-align:right" data-label="Peer median">' + formatMeasure(name, m.median) + '</td>' +
      '<td style="text-align:right" data-label="Where it stands">' + standing(m, ind.rank_below) + '</td>' +
      '<td style="text-align:right" data-label="Reported by">' + m.reported_by + '</td></tr>').join('') +
    '</tbody></table></div>' +
    (ind.note ? '<div class="co-note faint" style="font-size:12.5px;margin-top:8px">' + esc(ind.note) + '</div>' : '');
  return html + '</details>';
}

/* An explanation, one closed row away: what a figure is and its limits, never in the way
   of the figures. */
function about(html, title){
  return html ? '<details class="about"><summary>' + (title || 'About this') + '</summary><div class="about-body">' +
    html + '</div></details>' : '';
}

/* A section of a company's card, closed until clicked: its title in plain words and, when
   there is one, a line saying what is inside. The card opens on the key figures alone. */
function foldOpen(title, gist){
  return '<details class="co-sec fold"><summary><span class="fold-t">' + title + '</span>' +
    (gist ? '<span class="fold-g">' + gist + '</span>' : '') + '</summary>';
}

/* Notes from the Python side start in lower case so the command line can prefix them;
   on the page each stands as its own sentence. */
/* A module's reason, which is a clause ("fewer than two annual reports stored"), as a
   sentence: capitalised and closed (S-27). */
function sentence(t){ t = String(t || '').trim(); return t && (t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? '' : '.')); }

function valueBlock(x){
  const v = x.valuation;
  const title = 'Price compared with profit and assets';
  if (!v) return foldOpen(title, 'no price yet') +
    '<div class="co-note faint">No stored price for this company yet: it comes with the next company update.</div></details>';
  const fc = v.float_check || {};
  /* value.value_company withholds every figure built on the market value when the
     share basis fails its check, so those arrive empty and print as dashes. */
  const age = fc.years_old > 0 ? ' Checked against the float filed ' + fc.years_old +
    (fc.years_old === 1 ? ' year' : ' years') + ' earlier; no newer one is usable.' : '';
  return foldOpen(title, v.price_to_earnings != null
      ? esc(measureLabel('price_to_earnings')) + ' ' + formatMeasure('price_to_earnings', v.price_to_earnings) : '') +
    '<div class="stats">' +
      ['price', 'market_cap', 'price_to_earnings', 'price_to_book', 'price_to_sales', 'dividend_yield']
        .map(name => kv(measureLabel(name), withReason(formatMeasure(name, v[name]), v.why, name, v.withheld))).join('') +
    '</div>' +
    (fc.plausible === false
      ? '<div class="co-note" style="margin-top:10px;color:var(--warn)"><b>Check the share basis.</b> ' + esc(sentence(fc.note)) + '</div>'
      : '') +
    about((fc.plausible === false ? '' : esc(sentence(((fc.note || '') + age).trim())) + ' ') +
      'The price is today&rsquo;s; the profit is from ' + esc(v.figures_from || '') +
      '. Share count: ' + esc(v.share_count_basis || 'not filed') + '.', 'Where these figures come from') + '</details>';
}

function forecastBlock(x){
  const r = x.forecast_record;
  if (!r) return '';
  return foldOpen('How accurate analysts&rsquo; forecasts have been', r.quarters + ' quarters measured') +
    '<div class="stats">' +
      kv('Quarters measured', r.quarters) +
      kv('Beat the estimate', ofCount(r.beats) + (chanceText(r.beats) ? '<div class="dash-why">' + chanceText(r.beats) + '</div>' : '')) +
      kv('Median error', pc(r.median_error)) +
      kv('Median bias', (r.median_bias > 0 ? '+' : '') + pc(r.median_bias)) +
    '</div>' +
    '<div class="co-note faint" style="font-size:12.5px;margin-top:10px">' + esc(r.finding) + '</div></details>';
}

/* The same measure can appear at the top of a card and in its peer table with two
   values: the top is the company's latest figures, the table one filed year shared by
   every peer. Each label says which (J-07). The period comes from how fundamentals.py
   built the figure — four quarters, or the last annual report when the company stopped
   tagging quarters — never assumed. */
function topPeriod(c, name){
  const own = {eps: 'eps', cash: 'cash', debt_to_equity: 'equity'}[name] || 'revenue';
  const asof = c[own + '_asof'], basis = c[own + '_basis'];
  if (name === 'cash' || name === 'debt_to_equity')
    return (name === 'cash' && c.cash_includes_restricted ? 'incl. restricted, ' : '') + (asof ? 'at ' + fmtDay(asof) : 'latest');
  if (basis === 'quarters') return 'last 12 months';
  if (basis === 'annual') return 'year to ' + fmtDay(asof);
  return asof ? '12 months to ' + fmtDay(asof) : 'latest';
}

// The company shown: one at a time, chosen from the row of buttons above the card.
let coPick = null;
const usd2 = v => '$' + v.toFixed(2);
const priceText = p => p.close != null ? usd2(p.close) : '–';
// A price taken since the close (pre-market, the session, after hours), with the
// session New York's clock puts it in and the time on this computer's clock.
function quoteTime(iso){
  const d = new Date(iso), time = d.toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'});
  return d.toDateString() === new Date().toDateString() ? time
    : d.toLocaleDateString(undefined, {day:'numeric', month:'short'}) + ', ' + time;
}
function latestCol(p){
  const q = (p || {}).latest;
  if (!q) return '';
  return '<span class="co-pxcol"><span class="co-px-k">' + esc(q.session) + ' · ' + quoteTime(q.at) + '</span>' +
    '<span class="co-px">' + usd2(q.price) + '</span>' +
    '<span class="co-px-sub">' + pct1(q.change, true) + ' on the close' +
    (q.check ? ' · <b>check it in ' + esc(brokerName()) + '</b>: a move this size may be a split the closes do not have yet' : '') +
    '</span></span>';
}
const resultsPill = c => c.next_earnings
  ? '<span class="pill' + (c.days_to_earnings <= 14 ? ' soon' : '') + '">results ' + fmtDay(c.next_earnings.date) + '</span>' : '';

/* Every company covered, followed or held, in one table: the figures to scan, each a
   click from its card below. Any column
   sorts; the first order is the desk's list, followed then held. */
let coSort = null;
const CO_COLUMNS = [
  {key: 'company', label: 'Company', value: c => c.ticker},
  {key: 'price', label: 'Price', value: c => (c.price || {}).close},
  {key: 'day', label: 'Last day vs market', value: c => (c.price || {}).day_vs_market},
  {key: 'year', label: '1 year vs market', value: c => (c.price || {}).year_vs_market},
  {key: 'rating', label: 'Desk rating', value: c => (c.rating || {}).place},
  {key: 'pe', label: 'P/E vs its own 5 years', value: c => (c.pe_history || {}).place},
  {key: 'results', label: 'Next results', value: c => c.days_to_earnings, low: true},
  {key: 'news', label: 'Latest news', value: c => ((DATA.company_news || {}).companies || {})[c.ticker] &&
                                               DATA.company_news.companies[c.ticker].latest},
];
function coCell(key, c){
  const p = c.price || {}, n = ((DATA.company_news || {}).companies || {})[c.ticker] || {};
  if (key === 'company') return '<span class="tk">' + esc(c.ticker) + '</span> <span class="nm">' + esc(c.name) + '</span>' +
    (c.held ? ' <span class="co-held">' + (c.followed ? 'held' : 'held, not followed') + '</span>' : '');
  if (key === 'price') return priceText(p) + (p.latest ? '<div class="faint co-sub">' + esc(p.latest.session) + ' ' + usd2(p.latest.price) + '</div>' : '');
  if (key === 'day') return pct1(p.day_vs_market, true);
  if (key === 'year') return pct1(p.year_vs_market, true);
  if (key === 'rating') return ratingTag(c.rating) || '–';
  /* not a rate: a place among the company's own months, every one of them counted */
  if (key === 'pe') return c.pe_history && c.pe_history.place != null ? pePlace(c.pe_history.place) : '–';
  if (key === 'results') return c.next_earnings ? fmtDay(c.next_earnings.date) + '<div class="faint co-sub">in ' + c.days_to_earnings +
    (c.days_to_earnings === 1 ? ' day' : ' days') + '</div>' : '–';
  if (key === 'news') return n.latest ? fmtDay(localDay(n.latest)) + (n.unusual_days ? '<div class="faint co-sub">' + n.unusual_days +
    (n.unusual_days === 1 ? ' unusual day' : ' unusual days') + '</div>' : '') : '–';
  return '';
}
function coTable(C, pick){
  let rows = C.slice();
  if (coSort){
    const col = CO_COLUMNS.find(x => x.key === coSort.key);
    rows.sort((a, b) => {
      const x = col.value(a), y = col.value(b);
      if (x == null || y == null) return x == null && y == null ? 0 : (x == null ? 1 : -1);
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * coSort.dir;
    });
  }
  const head = col => '<th' + (col.key === 'company' ? ' style="text-align:left"' : '') + '><button class="sort-h' +
    (coSort && coSort.key === col.key ? ' on' : '') + '" data-co-sort="' + col.key + '">' + esc(col.label) +
    (coSort && coSort.key === col.key ? (coSort.dir < 0 ? ' ↓' : ' ↑') : '') + '</button></th>';
  // a phone stacks the table and hides its headings: the same sort, as a menu
  const menu = '<label class="co-sort-menu">Sort by <select id="coSortSel" aria-label="Sort the companies by">' +
    CO_COLUMNS.map(col => '<option value="' + col.key + '"' + ((coSort ? coSort.key : 'company') === col.key ? ' selected' : '') + '>' +
      esc(col.label) + '</option>').join('') + '</select></label>';
  return menu + '<div class="co-table scroll-x"><table class="sc-tbl peer-tbl co-tbl"><thead><tr>' + CO_COLUMNS.map(head).join('') + '</tr></thead><tbody>' +
    rows.map(c => '<tr data-co-pick="' + esc(c.ticker) + '" aria-selected="' + (c.ticker === pick) + '" tabindex="0">' +
      CO_COLUMNS.map(col => '<td data-label="' + esc(col.label) + '"' + (col.key === 'company' ? ' style="text-align:left"' : '') + '>' +
        '<span class="co-v">' + coCell(col.key, c) + '</span></td>').join('') + '</tr>').join('') + '</tbody></table></div>';
}
function renderCompanies(){
  const C = DATA.companies || [], unplaced = notPlaced();
  if (!C.length){
    $('coList').innerHTML = '<div class="empty">' + (DATA.as_of ? ('No company was followed on this day. ' + unplaced).trim()
      : 'Type a ticker above to follow a company. The US shares you hold appear here by themselves.') + '</div>';
    return;
  }
  const pick = C.some(c => c.ticker === coPick) ? coPick : C[0].ticker;
  $('coList').innerHTML = (unplaced ? '<div class="co-note faint" style="margin-bottom:12px">' + unplaced + '</div>' : '') +
    coTable(C, pick) +
    C.map(c => {
    const p = c.price || {}, r = c.results_reaction;
    const surprises = (c.surprises || []).map(s =>
      '<span>' + (s.beat ? 'beat' : 'missed') +
      (s.surprise_pct != null ? ' ' + pct1(Math.abs(s.surprise_pct)) : '') + '</span>').join(' · ');
    return '<div class="co" data-co="' + esc(c.ticker) + '"' + (c.ticker === pick ? '' : ' hidden') + '>' +
      '<div class="co-head">' +
        '<span class="co-id"><span class="row1"><span class="tk">' + esc(c.ticker) + '</span>' + ratingPill(c.rating) +
          /* the count only: "Buy" beside the ticker reads as the desk's verdict, and it
             lives in "What analysts say", where its known skew is stated beside it (Q4) */
          (c.analysts ? '<span class="pill">' + c.analysts.analysts + ' analysts</span>' : '') +
          resultsPill(c) +
        '</span><span class="nm">' + esc(c.name) + '</span>' + coverageLine(c.coverage, c.ticker, c) +
        '<span class="co-acts"><button type="button" class="btn" data-chart="' + esc(c.ticker) + '">Chart</button>' +
        '<button type="button" class="btn" data-ask="' + esc(c.ticker) + '">Ask</button></span></span>' +
        '<span class="co-price"><span class="co-prices">' +
          '<span class="co-pxcol"><span class="co-px-k">Close' + (p.as_of ? ' ' + fmtDay(p.as_of) : '') + '</span>' +
            '<span class="co-px">' + priceText(p) + '</span></span>' + latestCol(p) + '</span>' +
          (p.year_vs_market != null
            ? '<div class="co-px-sub"><span>' + pct1(p.year_vs_market, true) + '</span> vs market over 1 year</div>'
            : '') + '</span>' +
      '</div>' +

      '<div class="co-sec"><div class="eyebrow">Key figures</div>' +
        '<div class="co-grid">' +
          (DATA.card_top || []).map(name => kv(measureLabel(name) + ' <span class="faint">(' + esc(topPeriod(c, name)) + ')</span>',
            (c[name] == null ? withReason('–', c.why, name, c.withheld) : formatMeasure(name, c[name])) +
            sparkline(name, (c.context || {}).history, DATA.card_top))).join('') +
        '</div>' +
        '<div class="co-note faint" style="font-size:12.5px;margin-top:10px">SEC filings' +
          (c.revenue_asof ? ' · year to ' + fmtDay(c.revenue_asof) : '') + '</div>' +
      '</div>' +

      deskRatingBlock(c.rating) +
      newsFold(c.ticker) +
      peHistoryBlock(c.pe_history) +
      bridgeBlock((c.context || {}).bridge) +

      contextBlock(c.context) +

      ratingBlock(c.analysts) +

      ((surprises || r) ? foldOpen('Past results', c.surprises && c.surprises.length
          ? (c.surprises.length === 1 ? 'the last report' : 'the last ' + c.surprises.length + ' reports') : '') +
        (surprises ? '<div class="co-note">' + (c.surprises.length === 1 ? 'Last report' : 'Last ' + c.surprises.length + ' reports') +
          ': ' + surprises + '.</div>' : '') +
        reactionLine(r, 'past results announcements') + '</details>' : '') +

      thesisBlock(c.ticker) +

      wordingBlock(c.wording) +

      '<div class="co-sec">' +
        (c.summary ? '<div class="co-ai" id="ai-' + esc(c.ticker) + '"><div class="who">Written from the figures above · ' +
          esc(c.summary.model || '') +
          (c.summary.as_of && c.revenue_asof && c.summary.as_of < c.revenue_asof
            ? ' · written from figures to ' + fmtDay(c.summary.as_of) + ', before the latest; rewrite it for them' : '') +
          '</div>' + esc(c.summary.text) + '</div>'
          : '<div class="co-ai" id="ai-' + esc(c.ticker) + '" hidden></div>') +
        '<div class="co-actions"><button class="btn" data-explain="' + esc(c.ticker) + '">' +
          (c.summary ? 'Rewrite summary' : 'Explain in plain English') + '</button>' +
          (DATA.as_of ? '' : '<button class="btn" data-check="' + esc(c.ticker) + '">Check a trade</button>') +
          '<span class="faint" id="aimsg-' + esc(c.ticker) + '" style="font-size:13.5px"></span></div>' +
      '</div>' +
    '</div>';
  }).join('');
}

function pickCompany(ticker){
  coPick = ticker;
  document.querySelectorAll('#coList .co[data-co]').forEach(card => { card.hidden = card.dataset.co !== ticker; });
  document.querySelectorAll('#coList [data-co-pick]').forEach(b => b.setAttribute('aria-selected', b.dataset.coPick === ticker));
}

// a column's first sort: names and the days to results from the lowest, every other figure from the highest
const coFirstDir = key => key === 'company' || CO_COLUMNS.find(x => x.key === key).low ? 1 : -1;
$('coList').addEventListener('change', e => {
  if (e.target.id !== 'coSortSel') return;
  coSort = {key: e.target.value, dir: coFirstDir(e.target.value)};
  keepPlace(() => safe(renderCompanies));
});
$('coList').addEventListener('click', e => {
  const sort = e.target.closest('[data-co-sort]');
  if (sort){
    const key = sort.dataset.coSort;
    coSort = coSort && coSort.key === key ? {key, dir: -coSort.dir} : {key, dir: coFirstDir(key)};
    return keepPlace(() => safe(renderCompanies));
  }
  const choice = e.target.closest('[data-co-pick]');
  if (choice){
    pickCompany(choice.dataset.coPick);
    const card = document.querySelector('#coList .co[data-co="' + choice.dataset.coPick + '"]');
    if (card && window.innerWidth <= 900) card.scrollIntoView({block: 'start'});
  }
  const th = e.target.closest('[data-thesis]');
  if (th) openThesis(th.dataset.thesis);
  const text = e.target.closest('.wd-text');
  if (text) text.classList.toggle('wd-full');
  const all = e.target.closest('[data-wd-all]');
  if (all){
    all.closest('.br-block').querySelectorAll('.wd-p[data-wd="' + all.dataset.wdAll + '"]').forEach(p => p.classList.add('wd-open'));
    all.remove();
  }
});
$('coList').addEventListener('keydown', e => {
  const row = e.target.closest('tr[data-co-pick]');
  if (row && (e.key === 'Enter' || e.key === ' ')){ e.preventDefault(); pickCompany(row.dataset.coPick); }
});
$('coList').addEventListener('click', async e => {
  const b = e.target.closest('[data-explain]'); if (!b) return;
  const ticker = b.dataset.explain, msg = $('aimsg-' + ticker), box = $('ai-' + ticker);
  const rewrite = b.textContent.startsWith('Rewrite');
  b.disabled = true; msg.textContent = 'Writing…';
  try {
    const r = await fetch('/summary', {method:'POST', headers:{'Content-Type':'application/json'},
                                       body: JSON.stringify({ticker, refresh: rewrite})});
    const res = await r.json();
    if (!res.ok) throw new Error(res.message || 'Could not write the summary');
    const card = (DATA.companies || []).find(c => c.ticker === ticker);
    if (card) card.summary = res.summary;
    box.hidden = false;
    box.innerHTML = '<div class="who">Written from these figures · ' + esc(res.summary.model || '') + '</div>' + esc(res.summary.text);
    msg.textContent = '';
    b.textContent = 'Rewrite summary';
  } catch(err){ msg.textContent = err.message; }
  finally { b.disabled = false; }
});

