/* ---------------- journal ---------------- */
let tradeFilter = 'all', tradeShown = 25, editing = null;
/* A note is the user's own, when they want one: nothing asks for it. */
const NOTE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
function renderTrades(){
  const T = DATA.trades;
  $('tradeSub').textContent = T.count
    ? T.count + ' trades · ' + T.buys + ' buys, ' + T.sells + ' sells' +
      ' · fees ' + money(T.fees)
    : '';
  if (!T.count){ $('tradeList').innerHTML = '<div class="empty">' + (DATA.connected ? 'No trades yet.' : 'Your trades appear here once connected.') + '</div>'; return; }
  const rows = T.rows.filter(r => tradeFilter === 'all' ? true : r.side === tradeFilter);
  let html = '';
  rows.slice(0, tradeShown).forEach(r => {
    const open = editing === r.id;
    html += '<div class="t-row">' +
      '<span class="t-date">' + (r.date && r.date < (DATA_INITIAL.today || '')
        ? '<button class="t-asof" data-asof="' + esc(r.date) + '" title="Show the desk as it was that day">' + fmtDay(r.date) + '</button>'
        : fmtDay(r.date)) + '</span>' +
      '<span class="side ' + esc(r.side) + '">' + (r.side === 'SELL' ? 'SELL' : 'BUY') + '</span>' +
      '<span class="t-what"><span class="tk">' + esc(r.ticker) + '</span> <span class="q">' + qty(r.quantity) + ' @ ' + pricePer(r.price, r.price_currency) + '</span></span>' +
      '<span class="t-val r num">' + money(r.value) + (r.fees > 0.004 ? '<div class="faint" style="font-size:12.5px">fees ' + money(r.fees) + '</div>' : '') + '</span>' +
      '<span class="t-pl r num">' +
        (r.side === 'SELL' && r.realized != null ? money(r.realized, {sign:true}) + '<div class="faint" style="font-size:12.5px">closed gain</div>' : '') + '</span>' +
      '<button class="note-btn' + (r.note ? ' has' : '') + '" data-id="' + esc(r.id) + '" aria-label="' + (r.note ? 'Edit' : 'Add') + ' note" aria-expanded="' + open + '">' + NOTE_ICON + '</button>' +
      (open
        ? '<div class="editor"><textarea id="noteText" maxlength="2000" aria-label="Note">' +
            esc(r.note || '') + '</textarea>' +
          '<label class="look">Look at this trade again on <input type="date" id="noteLook" value="' + esc(r.look_again || '') + '"></label>' +
          '<div class="row"><button class="btn primary" data-save="' + esc(r.id) + '">Save note</button><button class="btn" data-cancel="1">Cancel</button><span class="faint" id="noteMsg" style="font-size:13.5px"></span></div></div>'
        : '<div class="t-note">' + esc(r.note) + (r.look_again ? (r.note ? '\n' : '') + 'Look again on ' + fmtDay(r.look_again) : '') + '</div>') +
      (r.plan ? '<div class="t-plan">Planned ' + fmtStamp(r.plan.written, '') + ': ' + esc(r.plan.why) + '</div>' : '') +
      '</div>';
  });
  if (!rows.length) html = '<div class="empty">No trades match this filter.</div>';
  if (rows.length > tradeShown) html += '<button class="btn wide" id="moreTrades">Show more (' + (rows.length - tradeShown) + ' left)</button>';
  $('tradeList').innerHTML = html;
  if (editing && $('noteText')) $('noteText').focus();
}
$('tradeFilter').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  tradeFilter = b.dataset.f; tradeShown = 25;
  [...$('tradeFilter').children].forEach(x => x.setAttribute('aria-pressed', x === b));
  safe(renderTrades);
});
$('tradeList').addEventListener('click', async e => {
  if (e.target.closest('#moreTrades')){ tradeShown += 25; return safe(renderTrades); }
  const nb = e.target.closest('.note-btn');
  if (nb){ editing = editing === nb.dataset.id ? null : nb.dataset.id; return safe(renderTrades); }
  if (e.target.closest('[data-cancel]')){ editing = null; return safe(renderTrades); }
  const sv = e.target.closest('[data-save]');
  if (sv){
    const id = sv.dataset.save, note = $('noteText').value.trim(), look_again = $('noteLook').value || null;
    sv.disabled = true; $('noteMsg').textContent = 'Saving…';
    try {
      const r = await fetch('/journal', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, note, look_again})});
      const res = await r.json().catch(() => ({}));
      if (!r.ok || !res.ok) throw new Error(res.message || '');        // refused: say why, keep what was typed
      const row = DATA.trades.rows.find(x => x.id === id);
      if (row){ row.note = note; row.look_again = look_again; }
      DATA.trades.noted = DATA.trades.rows.filter(x => x.note).length;
      editing = null; safe(renderTrades);
      reloadData().catch(() => {});      // the server rebuilt the page: the digest's trade lines with it
    } catch(err){
      sv.disabled = false;
      $('noteMsg').textContent = err.message ? err.message
        : location.protocol === 'file:' ? 'Open through ./desk.sh to save notes' : 'Could not save; is the desk running?';
    }
  }
});

