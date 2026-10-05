/* ---------------- refresh ---------------- */
async function reloadData(){
  const d = await fetch('/data', {cache:'no-store'});
  DATA = await d.json();
  keepPlace(renderAll);
}
// A re-draw keeps the rows that were open and the place on the page: the company data
// now arrives by itself, and must not close what is being read.
function keepPlace(draw){
  const key = d => { const s = d.closest('section'), c = d.closest('[data-co]'), t = d.querySelector('summary');
                     return [s ? s.id : '', c ? c.dataset.co : '', t ? (t.querySelector('.fold-t') || t).textContent : ''].join('|'); };
  const open = new Set([...document.querySelectorAll('main details[open]')].map(key)), y = window.scrollY;
  draw();
  document.querySelectorAll('main details').forEach(d => { if (!d.open && open.has(key(d))) d.open = true; });
  window.scrollTo(0, y);
}

// The server answers as it goes: one JSON line per step, blank lines while a step
// runs (so the connection never looks idle), and the result, {ok, message}, last.
async function readLines(r, onEvent){
  const reader = r.body.getReader(), decoder = new TextDecoder();
  let buffer = '', result = null;
  const take = line => { if (!line.trim()) return; const ev = JSON.parse(line);
                         if ('ok' in ev) result = ev; else onEvent(ev); };
  for (;;){
    const {value, done} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(0), {stream: !done});
    const lines = buffer.split('\n');
    buffer = lines.pop();
    lines.forEach(take);
    if (done) break;
  }
  take(buffer);
  return result;
}

$('refreshBtn').addEventListener('click', async () => {
  const btn = $('refreshBtn'), msg = $('msg');
  if (location.protocol === 'file:'){ msg.textContent = 'Open the desk with ./desk.sh to sync the account'; return; }
  btn.disabled = true; btn.classList.add('spinning'); msg.textContent = '';
  msg.classList.add('progress');
  $('synced').textContent = 'syncing…';
  let reached = false, built = null;
  try {
    const r = await fetch('/refresh', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({part: 'account'})});
    reached = true;
    const res = await readLines(r, ev => {
      if (ev.step && ev.state === 'running') msg.textContent = 'Syncing the account: ' + ev.step + '…';
      if (ev.built) built = reloadData().then(() => { $('synced').textContent = 'syncing…'; });
    });
    if (built) await built;
    if (!res) throw new TypeError('no result');                  // the stream ended early
    if (!res.ok) throw new Error(res.message || 'The account sync failed');
    await reloadData();
    msg.classList.toggle('progress', !res.message);
    msg.textContent = [res.message, res.timing].filter(Boolean).join(' · ');
  } catch(err){
    msg.classList.remove('progress');
    msg.textContent = !reached ? 'Desk server not running: start it with ./desk.sh'
      : err instanceof TypeError ? 'The connection to the desk dropped partway through the account sync. It carries on by itself; reload the page in a minute.'
      : err.message;
    $('synced').textContent = DATA.synced_at ? 'account ' + fmtStamp(DATA.synced_at) : 'account not synced yet';
  } finally { btn.disabled = false; btn.classList.remove('spinning'); }
});

/* ---------------- company data, by itself ----------------
   Filings, prices, financials, results, ratings and research update on opening and every
   DATA.market_every_minutes while the desk is open. None of it
   reaches Trading 212: the account syncs only on its own button. Not for a past day or
   the demo, never twice at once, and the new data waits while something is being typed. */
let marketRunning = false, marketWaiting = false;
let marketLast = DATA.market_updated_at ? Date.parse(DATA.market_updated_at) : 0;
function renderMarketAt(){
  $('marketAt').textContent = marketRunning ? 'companies updating…'
    : DATA.market_updated_at ? 'companies ' + fmtStamp(DATA.market_updated_at, 'updated') : 'companies not updated yet';
  $('marketAt').hidden = !!DATA.as_of || !!DATA.demo;
}
function typing(){
  const el = document.activeElement, add = $('wlAdd');
  return !!(editing || (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) || (add && add.value) ||
            [...document.querySelectorAll('dialog')].some(d => d.open));
}
async function showMarket(){
  if (typing() || DATA.as_of){ marketWaiting = true; return; }  // a past day stays as it is
  marketWaiting = false;
  await reloadData();
}
async function updateMarket(pressed){
  if (marketRunning || DATA.as_of || DATA.demo || location.protocol === 'file:') return;
  marketRunning = true; marketLast = Date.now();
  const say = t => { $('marketMsg').textContent = t; };
  safe(renderMarketAt);
  try {
    const r = await fetch('/refresh', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({part: 'market', pressed: !!pressed})});
    if (!r.ok){ if (pressed) say((await r.json()).message || ''); return; }
    // the prices, then the filings, are shown as they come in, one reload after another and not while something is being typed
    let shown = Promise.resolve();
    const res = await readLines(r, ev => {
      if (ev.built) shown = shown.then(showMarket).catch(() => {});
      else if (pressed && ev.step && ev.state === 'running') say('Updating companies: ' + ev.step.toLowerCase() + '…');
    });
    await shown;
    if (!res) throw new TypeError('no result');
    // keys not added yet are said apart from what failed: the desk is waiting for them, not broken
    const setup = res.setup || [];
    $('marketMsg').classList.toggle('progress', !res.message);
    say((res.message ? 'Companies updated, except ' + res.message + (setup.length ? '. Also to do: ' : '') : '') +
        (!res.message && setup.length ? 'Company data is waiting for a few free keys. ' : '') +
        setup.join('; ') +
        (pressed && res.timing ? ((res.message || setup.length) ? ' · ' : '') + res.timing : ''));   // pressed: how long it took
    marketRunning = false;
    await showMarket();
  } catch(err){
    $('marketMsg').classList.remove('progress');
    say(pressed ? 'Could not update the companies: is the desk running?' : '');
  } finally { marketRunning = false; safe(renderMarketAt); }
}
function marketDue(){
  const every = DATA.market_every_minutes;
  return !!every && Date.now() - marketLast >= every * 60000;
}
$('marketAt').addEventListener('click', () => updateMarket(true));
document.addEventListener('focusout', () => setTimeout(() => { if (marketWaiting) showMarket(); }, 300));

/* ---------------- boot ---------------- */
function renderAll(){
  // by name, so one missing renderer can never blank the whole page
  ['renderAsOf','renderHeader','renderHero','renderPerformance','renderChart','renderAsk','renderDigest','renderHealth','renderChecks','renderHeadlines','renderUpcoming',
   'renderHoldings','renderExposure','renderTilt','renderCosts','renderDividends','renderHistory','renderRisk','renderCompanies','renderCompanyNews','renderNews','reactionNote',
   'renderMix','renderCheckCard','renderPlans','renderClosed','renderHabits','renderTheses','renderTrades','renderPaper','renderBuyList','renderResearch','renderRatingRecord','renderScreener','renderNav'].forEach(name => {
    const fn = window[name];
    if (typeof fn !== 'function'){ console.error('missing renderer', name); return; }
    safe(fn);
  });
}
renderAll();
showPage((location.hash || '#overview').slice(1), false);
if (marketDue()) updateMarket(false);                          // on opening
// the page's one timer, ticking every few seconds: company data when it is due and a live chart on show when it is, never the account
setInterval(() => { chartTick(); if (marketWaiting) showMarket(); else if (marketDue()) updateMarket(false); }, 5000);
