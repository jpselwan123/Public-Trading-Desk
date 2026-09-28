/* ---------------- news on the followed companies (headlines.py) ----------------
   Other people's words, as published, with a link to each: only stories about the company,
   each once however many outlets carried it (build_desk.build_headlines). Beside each
   trading day, how the shares moved that day against the market, whether that move was
   unusual for them, and the company's own important SEC filings of that day. No score:
   the rating does not use them. */
function localDay(iso){
  const d = new Date(iso), two = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate());
}
function newsWhere(){ const N = DATA.company_news || {}; return (N.sources || []).length ? ' · from ' + esc(N.sources.join(' and ')) : ''; }
function newsMove(d){
  if (d.move == null) return d.close_day ? 'no move measured' : 'no close yet';
  return 'shares ' + pct1(d.move, true) + ' vs the market ' +
    (d.close_day === d.session ? 'that day' : 'at the next close, ' + fmtDay(d.close_day));
}
/* unusual for these shares: build_desk.unusual decides, the page words it */
function unusualTag(d){
  return d && d.unusual ? '<span class="cn-flag">unusual: ' + d.times.toFixed(1) + ' times its usual daily move</span>' : '';
}
function storySources(s){
  const all = s.sources || [];
  return esc(all.slice(0, 2).join(', ')) + (all.length > 2 ? ' and ' + (all.length - 2) + ' more' : '');
}
function newsItem(s){
  return '<div class="cn-it"><a href="' + link(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.headline) + '</a>' +
    ' <span class="faint">' + storySources(s) + ' · ' + fmtStamp(s.at, '') + '</span></div>';
}
function filingItem(f){
  return '<div class="cn-it cn-sec"><span class="cn-src">SEC filing</span> <a href="' + link(f.url) + '" target="_blank" rel="noopener noreferrer">' +
    esc(f.headline || f.form) + '</a> <span class="faint">' + esc(f.form || '') + (f.at ? ' · ' + fmtStamp(f.at, '') : '') + '</span></div>';
}
const NEWS_DAYS_SHOWN = 7;      // the latest trading days in a company's news, the rest a click away: a presentation limit
/* The week's news in brief (brief.py): written when asked, from the headlines alone */
function briefInner(b){
  return '<div class="who">The week in brief · from ' + b.headlines + (b.headlines === 1 ? ' headline, ' : ' headlines, ') +
    fmtDay(b.from) + (b.to !== b.from ? ' to ' + fmtDay(b.to) : '') + ' · ' + esc(b.model || '') +
    (b.new_since ? ' · ' + b.new_since + (b.new_since === 1 ? ' story' : ' stories') + ' since' : '') + '</div>' + esc(b.text);
}
function briefBlock(ticker, n){
  const c = (DATA.companies || []).find(x => x.ticker === ticker), b = c && c.brief;
  if (DATA.as_of) return b ? '<div class="cn-brief"><div class="co-ai">' + briefInner(b) + '</div></div>' : '';
  if (!b && !n.week) return '';
  return '<div class="cn-brief"><div class="co-ai" id="br-' + esc(ticker) + '"' + (b ? '>' + briefInner(b) : ' hidden>') + '</div>' +
    (n.week ? '<div class="co-actions"><button class="btn" data-brief="' + esc(ticker) + '">' +
      (!b ? 'The week in brief' : b.new_since ? 'Brief it again' : 'Write it again') + '</button>' +
      '<span class="faint" id="brmsg-' + esc(ticker) + '" style="font-size:13.5px"></span></div>' : '') + '</div>';
}
function newsFold(ticker){
  const N = DATA.company_news || {}, n = (N.companies || {})[ticker];
  if (!n) return '';
  if (!n.days.length) return foldOpen('News', 'none in the last ' + N.keep_days + ' days') +
    '<div class="co-note faint">' + (DATA.as_of ? 'No news had been fetched for it by this day.'
      : 'Nothing about it in the last ' + N.keep_days + ' days' + newsWhere() + '.') + '</div></details>';
  const gist = [n.count ? n.count + (n.count === 1 ? ' story' : ' stories') : '',
                n.press ? n.press + ' from the press' : '',
                n.unusual_days ? n.unusual_days + (n.unusual_days === 1 ? ' unusual day' : ' unusual days') : '',
                n.latest ? 'latest ' + fmtStamp(n.latest, '') : ''].filter(Boolean).join(' · ');
  const day = (d, i) => '<div class="cn-day' + (i >= NEWS_DAYS_SHOWN ? ' cn-more' : '') + '"><div class="cn-dh"><b>' + fmtDay(d.session) + '</b><span>' +
      newsMove(d) + unusualTag(d) + '</span></div>' + (d.filings || []).map(filingItem).join('') + (d.items || []).map(newsItem).join('') + '</div>';
  return foldOpen('News', gist) + briefBlock(ticker, n) + n.days.map(day).join('') +
    (n.days.length > NEWS_DAYS_SHOWN ? '<button class="linkish" data-news-more="1">Show ' + (n.days.length - NEWS_DAYS_SHOWN) +
      (n.days.length - NEWS_DAYS_SHOWN === 1 ? ' earlier day' : ' earlier days') + '</button>' : '') +
    about('<p>Stories about ' + esc(ticker) + ' from the last ' + N.keep_days + ' days' + newsWhere() + ': ' + esc((N.outlets || []).join(', ')) +
      '. The FT&rsquo;s links open with your own FT account. A story counts only if it names the company in its headline or its first ' + N.lede_words + ' words, ' +
      'the rule of Tetlock, Saar-Tsechansky &amp; Macskassy (2008); one carried by several outlets is shown once, with each of them named.</p>' +
      '<p>Each story and filing is placed on the first trading day it could move the price: one published after the close (' + esc(N.close) +
      ' in New York), or at a weekend, on the next. Beside each day is how the shares moved from the close before to that day&rsquo;s close, ' +
      'less the S&amp;P 500&rsquo;s move. A move is marked unusual when it lies outside the ' + esc(N.level) + ' range of the shares&rsquo; own daily moves ' +
      'against the market over the ' + N.normal_days + ' trading days before it, as an event study measures it (MacKinlay 1997): about one ordinary day in ' + N.one_in + ' ' +
      'moves that far. A big move on a day with news does not show that the news caused it.</p><p>The news is not part of the desk&rsquo;s rating. ' +
      'Research on news finds its effect on prices within days: a company&rsquo;s negative news forecasts its next day&rsquo;s return and its coming ' +
      'earnings (Tetlock, Saar-Tsechansky &amp; Macskassy 2008), and a day&rsquo;s news its returns for a day or two (Heston &amp; Sinha 2017). ' +
      'The rating rests on findings about a year.</p><p>&ldquo;The week in brief&rdquo; is written when you ask, by OpenAI&rsquo;s model, from the last ' +
      N.week_days + ' days&rsquo; headlines, filings and moves shown here and nothing else: it has the headlines, not the articles, and is told never to ' +
      'say a story moved the shares, nor to say buy or sell.</p>', 'About this news') + '</details>';
}
let newsShown = 20, newsKind = 'all';         // the latest twenty, the rest a click away: a presentation limit
const NEWS_KINDS = {all: () => true, press: s => !!s.press, unusual: s => !!s.unusual};
function renderCompanyNews(){
  const N = DATA.company_news || {}, feed = (N.feed || []).filter(NEWS_KINDS[newsKind] || NEWS_KINDS.all);
  const followed = ((DATA.news || {}).tickers || []).length;
  $('cnSub').innerHTML = (N.feed || []).length ? esc((N.sources || []).join(' and ')) : '';
  if (!feed.length){
    $('cnList').innerHTML = '<div class="empty">' + (!followed ? 'Follow a company to see its news.'
      : DATA.as_of ? 'No news had been fetched by this day.'
      : newsKind === 'press' ? 'Nothing from the FT or the rest of the press in the last ' + N.keep_days + ' days.'
      : newsKind === 'unusual' ? 'No story fell on a day of an unusual move in the last ' + N.keep_days + ' days.'
      : 'No news yet: it comes with the next company update.') + '</div>';
    return;
  }
  const row = s =>
    '<div class="n-row">' +
      '<span class="n-when">' + fmtDay(localDay(s.at)) + '</span>' +
      '<span class="n-main"><div class="n-title"><button class="tk-btn" data-co-open="' + esc(s.ticker) + '"><span class="tk">' + esc(s.ticker) + '</span></button> ' +
        '<a class="cn-a" href="' + link(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.headline) + '</a></div>' +
        '<div class="n-what">' + storySources(s) + ' · ' +
          new Date(s.at).toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'}) +
          (s.unusual ? ' · <span class="cn-flag">on a day of an unusual move</span>' : '') + '</div></span>' +
      '<span class="n-form"></span>' +
    '</div>';
  $('cnList').innerHTML = feed.slice(0, newsShown).map(row).join('') +
    (feed.length > newsShown ? '<button class="btn wide" id="moreNews">Show ' + Math.min(20, feed.length - newsShown) + ' more</button>' : '');
}
$('cnList').addEventListener('click', e => {
  if (e.target.id === 'moreNews'){ newsShown += 20; return safe(renderCompanyNews); }
  const b = e.target.closest('[data-co-open]'); if (!b) return;
  showPage('companies'); pickCompany(b.dataset.coOpen);
});
$('cnFilter').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  newsKind = b.dataset.f; newsShown = 20;
  [...$('cnFilter').children].forEach(x => x.setAttribute('aria-pressed', x === b));
  safe(renderCompanyNews);
});
$('coList').addEventListener('click', e => {
  const more = e.target.closest('[data-news-more]'); if (!more) return;
  more.closest('details').querySelectorAll('.cn-more').forEach(d => d.classList.remove('cn-more'));
  more.remove();
});
/* The one path to the coverage list: {follow, replaces} or {unfollow}. The rules (the
   cap, the replacement) are news.py's; a refusal comes back as a message and is shown,
   never worked around here. */
/* The follow box's line. A company just followed carries an Unfollow beside it, while it loads
   and once it has. */
let wlJust = null;
const wlSay = text => {
  if (!$('wlMsg')) return;
  $('wlMsg').innerHTML = esc(text) + (wlJust && !DATA.as_of
    ? (text ? ' · ' : '') + '<button class="linkish wl-undo" data-unfollow="' + esc(wlJust) + '">Unfollow ' + esc(wlJust) + '</button>' : '');
};
async function saveWatchlist(body){
  wlJust = null;
  wlSay('Saving…');
  try {
    const r = await fetch('/watchlist', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const res = await r.json();
    if (!res.ok) throw new Error(res.message || 'Could not save');
    // the server rebuilt the whole page: the company cards, the tab counts and the
    // Filings list all follow the one coverage list, so all of it is read again
    if (body.follow) coPick = String(body.follow).toUpperCase();        // the new company is the one shown
    await reloadData();
    wlSay('');
    return '';
  } catch(err){ wlSay(err.message); return err.message; }
}
/* A company just followed is loaded at once (server.fetch_company): nothing to press. */
async function loadCompany(ticker){
  wlJust = ticker;
  // unfollowed while it loads: the loading goes on at the desk, and says nothing more here
  const say = text => { if (wlJust === ticker) wlSay(text); };
  say('Loading ' + ticker + '…');
  try {
    const r = await fetch('/fetch', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ticker})});
    if (!r.ok){ say((await r.json()).message || 'Could not load ' + ticker); return; }
    const res = await readLines(r, ev => {
      if (ev.built) reloadData();                     // its figures and price are in: shown before the rest
      else if (ev.step && ev.state === 'running') say('Loading ' + ticker + ': ' + ev.step[0].toLowerCase() + ev.step.slice(1) + '…');   // "the FT" kept
    });
    if (!res) throw new TypeError('no result');
    await reloadData();
    say(res.message || ticker + ' loaded');
  } catch(err){ say('Could not load ' + ticker + ' now: it loads with the next company update'); }
}
/* Unfollow straight after following, from the follow box or where a Follow button was: no
   question asked, since following again is one click and the dates are kept either way. */
async function unfollow(ticker){
  const failed = await saveWatchlist({unfollow: ticker});
  wlSay(failed || 'Stopped following ' + ticker);
}
document.addEventListener('click', e => {
  const u = e.target.closest('[data-unfollow]');
  if (u && !DATA.as_of) unfollow(u.dataset.unfollow);
});
/* Following is the ticker alone; only at the cap does it ask which company it replaces. */
let followDone = null;
async function follow(ticker, done){
  // only the companies followed count toward the cap: one held and not followed is covered besides
  const N = DATA.news || {}, mine = N.followed || N.tickers || [], full = mine.length >= (N.max_coverage || Infinity);
  followDone = done || null;
  if (!full){
    if (!(await saveWatchlist({follow: ticker}))){ if (followDone) followDone(); loadCompany(ticker); }
    return;
  }
  $('fwTitle').textContent = 'Follow ' + ticker;
  $('followForm').dataset.ticker = ticker;
  $('fwMsg').textContent = '';
  /* no company is pre-chosen: dropping one must be a decision, not a default */
  $('fwOut').innerHTML = '<option value="" disabled selected>Choose the company it replaces</option>' +
    mine.map(t => '<option>' + esc(t) + '</option>').join('');
  $('fwOut').required = true;
  $('fwReplace').querySelector('label').textContent =
    'You follow ' + N.max_coverage + ' companies, the most the desk covers. Which one does ' + ticker + ' replace?';
  $('followDlg').showModal();
}
$('followForm').addEventListener('submit', async e => {
  if (e.submitter && e.submitter.value === 'cancel') return;
  e.preventDefault();
  const ticker = $('followForm').dataset.ticker;
  const failed = await saveWatchlist({follow: ticker, replaces: $('fwOut').value});
  if (failed){ $('fwMsg').textContent = failed; return; }
  $('followDlg').close();
  if (followDone) followDone();
  loadCompany(ticker);
});
$('coList').addEventListener('click', async e => {
  const w = e.target.closest('[data-brief]');
  if (w){
    const ticker = w.dataset.brief, box = $('br-' + ticker), msg = $('brmsg-' + ticker);
    const card = (DATA.companies || []).find(c => c.ticker === ticker);
    w.disabled = true; msg.textContent = 'Writing…';
    try {
      const r = await fetch('/brief', {method:'POST', headers:{'Content-Type':'application/json'},
                                       body: JSON.stringify({ticker, refresh: !!(card && card.brief)})});
      const res = await r.json();
      if (!res.ok) throw new Error(res.message || 'Could not write it');
      if (card) card.brief = res.brief;
      box.hidden = false; box.innerHTML = briefInner(res.brief);
      msg.textContent = ''; w.textContent = 'Write it again';
    } catch(err){ msg.textContent = err.message; }
    finally { w.disabled = false; }
    return;
  }
  const f = e.target.closest('[data-follow-held]');
  if (f) return follow(f.dataset.followHeld);
  const x = e.target.closest('[data-remove]'); if (!x) return;
  if (confirm('Stop following ' + x.dataset.remove + '?'))
    saveWatchlist({unfollow: x.dataset.remove});
});
$('watchlist').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.target.id !== 'wlAdd') return;
  const t = e.target.value.trim().toUpperCase();
  if (t){ e.target.value = ''; follow(t); }
});

