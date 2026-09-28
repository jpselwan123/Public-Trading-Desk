/* ---------------- screener ---------------- */
let SCREEN = null;
/* Rows are shown a page at a time, and any column re-sorts every match, not only the
   rows on screen — the endpoint returns them all. The first sort is the user's own
   first condition; nothing here orders by desirability. */
const SC_PAGE = 50;
let scSort = null, scShown = SC_PAGE;

/* A condition reads in the measure's own terms: "Return on assets > 0.0%", not
   "return_on_assets>0". The threshold is a value of the measure, so it is formatted
   like one. */
const OPS = {'>=': '≥', '<=': '≤', '>': '>', '<': '<', '==': '='};
function conditionText(r){ return measureLabel(r.measure) + ' ' + (OPS[r.op] || r.op) + ' ' + formatMeasure(r.measure, r.value); }

function renderScreener(){
  const presets = (SCREEN && SCREEN.presets) || {};
  $('scPresets').innerHTML = Object.keys(presets).length
    ? Object.entries(presets).map(([key, p]) =>
        '<button class="btn" data-preset="' + esc(key) + '">' + esc(p.name) + '</button>').join('')
    : '<button class="btn" data-preset="graham">Load the published screens</button>';
  $('scMeasures').innerHTML = (SCREEN && SCREEN.measures)
    ? 'Measures: ' + SCREEN.measures.map(esc).join(', ')
    : '';

  const s = SCREEN && SCREEN.screen;
  if (!s) return;
  $('scTitle').textContent = s.name || 'Results';
  $('scSub').textContent = (s.rules || []).map(conditionText).join(' · ');
  $('scPresetNote').innerHTML = s.source
    ? esc(s.source) + (s.omits && s.omits.length
        ? '<br><b>Not applied:</b> ' + s.omits.map(esc).join('; ') : '')
    : '';

  // How many companies each condition could be judged for, stated FIRST and in body
  // text: without it the count reads as though every other company was tested and
  // failed, and most were not testable (Phase 4 — it sat below the count, in grey).
  const rows = Object.entries(s.evaluated || {}).sort((a, b) => a[1] - b[1]);
  /* not a rate: coverage of the whole stored universe, a census */
  const usable = s.usable != null ? ' of ' + s.usable.toLocaleString() : '';
  const key = scSort ? scSort.key : s.sorted_by;
  const words = ['ticker', 'name', 'sector'].includes(key);
  const sortWords = scSort
    ? 'sorted by ' + esc(sortLabel(key)).toLowerCase() + ', ' +
      (words ? (scSort.dir < 0 ? 'Z to A' : 'A to Z') : (scSort.dir < 0 ? 'highest' : 'lowest') + ' first')
    : 'sorted by ' + esc(measureLabel(s.sorted_by)).toLowerCase() + ', the first condition you set, highest first';
  $('scCoverage').innerHTML = rows.length
    ? '<div class="co-note" style="margin-bottom:12px;color:var(--ink)">Each condition could be judged for this many companies' +
      usable + ':<br>' +
      rows.map(([name, n]) => esc(measureLabel(name)) + ' <b>' + n.toLocaleString() + '</b>').join(' · ') +
      '<br>The rest are not failures — the figure is not in their filings as the SEC publishes them' +
      (s.financial_not_judged ? ', or, for ' + s.financial_not_judged.toLocaleString() +
        ' banks, insurers and property companies, not judged because ' + esc(s.financial_note) : '') + '.' +
      (s.excluded ? ' A further ' + s.excluded.toLocaleString() + ' were set aside: ' +
        (s.misfiled || 0).toLocaleString() + ' file a figure in the wrong unit, which their own filings show; ' +
        (s.suspected || 0).toLocaleString() + ' file one about a thousand or a million times off — a slip or a huge real move, which their filings cannot tell apart; and ' +
        (s.unconfirmed || 0).toLocaleString() + ' file figures that do not add up, or one too small to check.' : '') +
      '</div><div class="co-note" style="margin-bottom:12px"><b>' + s.matched.toLocaleString() +
      ' companies match</b>, ' + sortWords + '. Click a column to sort by it.</div>'
    : '';

  const columns = s.results.length ? Object.keys(s.results[0].measures) : [];
  const ordered = sortedResults(s.results, key, scSort ? scSort.dir : -1);
  const head = (label, sortKey, right) => '<th' + (right ? ' style="text-align:right"' : '') + '>' +
    '<button class="sort-h' + (sortKey === key ? ' on' : '') + '" data-sort="' + esc(sortKey) + '">' + esc(label) +
    (sortKey === key ? ((scSort ? scSort.dir : -1) < 0 ? ' ↓' : ' ↑') : '') + '</button></th>';
  $('scResults').innerHTML = s.results.length
    ? '<div class="scroll-x"><table class="sc-tbl"><thead><tr>' +
      head('Ticker', 'ticker') + head('Company', 'name') + head('Sector', 'sector') +
      head(measureLabel('public_float'), 'public_float', true) +
      columns.map(c => head(measureLabel(c), c, true)).join('') +
      '<th></th></tr></thead><tbody>' +
      ordered.slice(0, scShown).map(r =>
        '<tr><td class="tk">' + esc(r.ticker) + '</td><td>' + esc(r.name || '') + '</td>' +
        '<td class="sc-sector">' + esc(r.sector || '–') + '</td>' +
        '<td style="text-align:right">' + esc(formatMeasure('public_float', r.public_float)) + '</td>' +
        columns.map(c => '<td style="text-align:right">' + esc(formatMeasure(c, r.measures[c])) + '</td>').join('') +
        '<td>' + followButton(r.ticker) + '</td></tr>').join('') +
      '</tbody></table></div>' +
      (ordered.length > scShown
        ? '<div style="margin-top:12px"><button class="btn" id="scMore">Show ' +
          Math.min(SC_PAGE, ordered.length - scShown) + ' more</button> <span class="faint" style="font-size:13.5px">' +
          /* not a rate: paging */
          scShown.toLocaleString() + ' of ' + ordered.length.toLocaleString() + ' shown</span></div>'
        : '')
    : '<div class="empty">No company meets all of these conditions.</div>';
}

function sortLabel(key){ return {ticker: 'Ticker', name: 'Company', sector: 'Sector'}[key] || measureLabel(key); }
function sortValue(r, key){
  if (key === 'ticker' || key === 'name' || key === 'sector') return r[key] || null;
  return key === 'public_float' ? r.public_float : (r.measures || {})[key];
}
function sortedResults(results, key, dir){
  return results.slice().sort((a, b) => {
    const x = sortValue(a, key), y = sortValue(b, key);
    if (x == null || y == null) return x == null && y == null ? a.ticker.localeCompare(b.ticker) : (x == null ? 1 : -1);
    const c = typeof x === 'string' ? x.localeCompare(y) : x - y;
    return c ? c * dir : a.ticker.localeCompare(b.ticker);
  });
}

/* Following a company from a screen opens the same dialog the Filings page uses, and
   saves through the same saveWatchlist call — one path, not two, and loads it at once
   (loadCompany). Following is not endorsing: it means "show me
   this company's card", nothing more. */
// the companies followed: one held and not followed can still be followed
function watched(){ const N = DATA.news || {}; return (N.followed || N.tickers || []).map(t => String(t).toUpperCase()); }

function followButton(ticker){
  const on = watched().includes(String(ticker).toUpperCase());
  return on ? '<span class="faint" style="font-size:12.5px">following</span>' +
              (DATA.as_of ? '' : ' <button class="linkish fb-undo" data-unfollow="' + esc(ticker) + '">Unfollow</button>')
            :'<button class="btn" style="padding:3px 9px;font-size:12.5px" data-follow="' + esc(ticker) + '">Follow</button>';
}

/* "ahead of" or "behind", never "beat it by −11%" — the middle trade, with its interval */
function vsMarket(m){
  if (!m) return 'level with';
  const side = v => pct1(Math.abs(v)) + (v >= 0 ? ' ahead' : ' behind');
  /* no range, so no bar to set the text apart: as S-32 found for medianMove */
  if (m.low == null) return '<b>' + pct1(Math.abs(m.estimate)) + '</b> ' + (m.estimate >= 0 ? 'ahead of' : 'behind') +
    ' the market <span class="iv-txt">(' + rangeText(m, side) + ')</span>';
  return '<b>' + pct1(Math.abs(m.estimate)) + '</b> ' + (m.estimate >= 0 ? 'ahead of' : 'behind') +
    '<span class="ivn"> the market' + moveBar(m) + '</span><span class="iv-txt">' + rangeText(m, side) + '</span>';
}


async function runScreen(body){
  $('scResults').innerHTML = '<div class="empty">Working…</div>';
  try {
    const r = await fetch('/screen', {method:'POST', headers:{'Content-Type':'application/json'},
                                      body: JSON.stringify(body)});
    const res = await r.json();
    if (!res.ok){
      $('scResults').innerHTML = '<div class="empty">' + esc(res.message || 'That screen could not run') + '</div>';
      return;
    }
    SCREEN = res;
    scSort = null;
    scShown = SC_PAGE;
    renderScreener();
  } catch (e) {
    $('scResults').innerHTML = '<div class="empty">The desk server is not running — start it with ./desk.sh</div>';
  }
}

document.addEventListener('click', async e => {
  const preset = e.target.closest('[data-preset]');
  if (preset) runScreen({preset: preset.dataset.preset});
  if (e.target.id === 'scRun') runScreen({where: $('scWhere').value});
  const sortBy = e.target.closest('[data-sort]');
  if (sortBy){
    const s = SCREEN && SCREEN.screen, current = scSort ? scSort.key : s && s.sorted_by;
    const key = sortBy.dataset.sort, words = ['ticker', 'name', 'sector'].includes(key);
    scSort = {key, dir: key === current ? -((scSort ? scSort.dir : -1)) : (words ? 1 : -1)};
    safe(renderScreener);
  }
  if (e.target.id === 'scMore'){ scShown += SC_PAGE; safe(renderScreener); }
  const pick = e.target.closest('[data-follow]');
  if (pick) follow(pick.dataset.follow, () => safe(renderScreener));
});

