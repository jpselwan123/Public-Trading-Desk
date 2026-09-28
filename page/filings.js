/* ---------------- filings ---------------- */
let newsFilter = 'material';            // the important ones first; All is one click away
/* How the shares moved against the market after past events of one kind: the median
   with its interval, and the count of ups against half. Both come from one sign test
   in uncertainty.py, so the verdict is one sentence. */
function reactionLine(r, events, cls){
  const m = r && (r.moves || {})[r.window], up = r && (r.ups || {})[r.window];
  if (!m || !up) return '';
  return '<div class="' + (cls || 'co-note') + '">After ' + r.n + ' ' + events + ', the median move over the next ' + r.window +
    ' days against the market was ' + medianMove(m, v => pct1(v, true)) + '; up after ' + ofCount(up) + '. ' +
    (up.distinguishable ? 'More consistent than chance would give.' : 'This cannot be told from no reaction.') + '</div>';
}
/* Said once per page rather than on every line: why the past-reaction ranges are
   wider than the usual level (S-13). Every figure comes from build_desk.reaction_family. */
function reactionNote(){
  const f = (DATA.news || {}).reaction_family;
  const text = !f || f.records < 2 ? ''
    : 'Past reactions: ' + f.records + ' records of how shares moved after a kind of filing are compared at once. At ' +
      f.usual_level + ' each, about ' + Math.round(f.by_luck_at_usual) + ' would look like patterns by luck alone, so every range is set at ' +
      f.level + ' instead: the level of Benjamini &amp; Yekutieli (2005), the correction the research page applies to its rules. ' +
      'Their method widens only the records it picks out; the desk widens every one, so none is read at a narrower range than another.';
  ['coNote', 'reactNote'].forEach(id => { $(id).innerHTML = text; });
}
function afterLine(i){
  const kind = (i.category || '').replace(/^Announcement: /, '');
  return reactionLine(i.reaction, 'past "' + esc(kind) + '" filings', 'n-after');
}
function renderNews(){
  const N = DATA.news || {tickers:[], items:[]};
  $('newsSub').textContent = N.count
    ? N.count + ' filings · ' + N.material + ' important · ' + N.insider + ' insider'
    : '';
  if (!N.tickers || !N.tickers.length){
    $('newsList').innerHTML = '<div class="empty">' + (DATA.as_of ? ('No company was followed on this day. ' + notPlaced()).trim()
      : 'Follow a company at the top of this tab to see its filings.') + '</div>';
    return;
  }
  if (!N.count){ $('newsList').innerHTML = '<div class="empty">' + (DATA.as_of ? 'No filing had been received by this day.'
    : 'No filings yet: they come with the next company update.') + '</div>'; return; }
  const rows = N.items.filter(i => newsFilter === 'all' ? true : newsFilter === 'material' ? i.material : i.form === '4');
  if (!rows.length){ $('newsList').innerHTML = '<div class="empty">Nothing matches this filter.</div>'; return; }
  $('newsList').innerHTML = rows.slice(0, 60).map(i =>
    '<div class="n-row' + (i.material ? ' material' : '') + '">' +
      '<span class="n-when">' + fmtDay(i.date) + '</span>' +
      '<span class="n-main"><div class="n-title"><span class="tk">' + esc(i.ticker) + '</span> ' +
        '<a href="' + link(i.url) + '" target="_blank" rel="noopener noreferrer">' + esc(i.label) + '</a></div>' +
        '<div class="n-what">' + esc(i.what) + '</div>' + afterLine(i) + '</span>' +
      '<span class="n-form">' + esc(i.form) + '</span>' +
    '</div>').join('');
}
$('newsFilter').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  newsFilter = b.dataset.f;
  [...$('newsFilter').children].forEach(x => x.setAttribute('aria-pressed', x === b));
  safe(renderNews);
});
