/* ---------------- quick jump ----------------
   Ctrl/⌘+K, "/" or the Jump button: type a few letters, go to a tab, a section, a company, or run the two
   refreshes. It only moves around the page (or presses a button that is already there); it reads nothing
   new and sends nothing. The rows are built from what the page has, so nothing here is a second list. */
const JUMP_SECTIONS = [
  {page:'news', label:'News'}, {page:'filings', label:'Filings'}, {page:'screener', label:'Screener'},
  {page:'practice', label:'Practice'}, {page:'orders', label:'Orders'},
];
let jumpRows = [], jumpAt = 0, jumpBack = null;
function jumpEntries(){
  const rows = TABS.map(t => ({label: t.label, hint: 'Tab', go: () => showPage(t.id)}));
  JUMP_SECTIONS.forEach(s => {
    const el = $('page-' + s.page);
    if (el && !el.hidden) rows.push({label: s.label, hint: 'Section', go: () => showPage(s.page)});
  });
  (DATA.companies || []).forEach(c => rows.push({
    label: c.ticker, note: c.name || '', hint: 'Company', mono: true,
    go: () => { showPage('companies'); pickCompany(c.ticker);
                const card = document.querySelector('#coList .co[data-co="' + c.ticker + '"]'); if (card) card.scrollIntoView({block: 'start'}); }}));
  if (typeof openChat === 'function' && !DATA.as_of) rows.push({label: 'Ask a question', hint: 'Action', go: () => openChat()});
  [['refreshBtn', 'Sync your account'], ['marketAt', 'Update the companies now']].forEach(([id, label]) => {
    const b = $(id); if (b && !b.disabled && b.offsetParent !== null) rows.push({label, hint: 'Action', go: () => b.click()});
  });
  return rows;
}
// how well a typed word fits a row: a start beats a word's start beats anywhere; 0 is no fit
function jumpScore(row, q){
  const text = (row.label + ' ' + (row.note || '')).toLowerCase();
  if (!q) return 1;
  return q.split(/\s+/).reduce((sum, w) => {
    if (!sum) return 0;
    const i = text.indexOf(w);
    return i < 0 ? 0 : sum + (i === 0 ? 3 : text[i - 1] === ' ' ? 2 : 1);
  }, 1);
}
function jumpDraw(){
  const q = $('jumpInput').value.trim().toLowerCase();
  jumpRows = jumpEntries().map(r => [jumpScore(r, q), r]).filter(x => x[0]).sort((a, b) => b[0] - a[0]).map(x => x[1]).slice(0, 12);
  jumpAt = Math.min(jumpAt, Math.max(0, jumpRows.length - 1));
  $('jumpList').innerHTML = jumpRows.length ? jumpRows.map((r, i) =>
    '<li role="option" id="jump-' + i + '" data-jump="' + i + '"' + (i === jumpAt ? ' aria-selected="true"' : ' aria-selected="false"') + '>' +
      '<span class="j-main' + (r.mono ? ' j-tk' : '') + '">' + esc(r.label) + '</span>' +
      (r.note ? '<span class="j-note">' + esc(r.note) + '</span>' : '') +
      '<span class="j-hint">' + esc(r.hint) + '</span></li>').join('')
    : '<li class="j-none" role="presentation">Nothing here matches</li>';
  $('jumpInput').setAttribute('aria-activedescendant', jumpRows.length ? 'jump-' + jumpAt : '');
}
function jumpOpen(){
  if ($('jump').hidden === false) return;
  jumpBack = document.activeElement;
  $('jump').hidden = false; document.body.classList.add('jumping');
  $('jumpInput').value = ''; jumpAt = 0; jumpDraw(); $('jumpInput').focus();
}
function jumpClose(){
  if ($('jump').hidden) return;
  $('jump').hidden = true; document.body.classList.remove('jumping');
  if (jumpBack && jumpBack.focus) jumpBack.focus();
}
function jumpGo(i){
  const row = jumpRows[i]; if (!row) return;
  jumpClose(); row.go();
}
document.addEventListener('keydown', e => {
  if (document.querySelector('dialog[open]')) return;              // a dialog is in front: its keys are its own
  const typing = /^(input|textarea|select)$/i.test((e.target.tagName || '')) || e.target.isContentEditable;
  if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)){ e.preventDefault(); $('jump').hidden ? jumpOpen() : jumpClose(); return; }
  if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && !e.altKey && $('jump').hidden){ e.preventDefault(); jumpOpen(); return; }
  if ($('jump').hidden) return;
  if (e.key === 'Escape'){ e.preventDefault(); jumpClose(); }
  else if (e.key === 'ArrowDown' || e.key === 'ArrowUp'){
    e.preventDefault();
    if (!jumpRows.length) return;
    jumpAt = (jumpAt + (e.key === 'ArrowDown' ? 1 : -1) + jumpRows.length) % jumpRows.length;
    jumpDraw();
    const on = $('jump-' + jumpAt); if (on && on.scrollIntoView) on.scrollIntoView({block: 'nearest'});
  }
  else if (e.key === 'Enter'){ e.preventDefault(); jumpGo(jumpAt); }
  else if (e.key === 'Tab'){ e.preventDefault(); $('jumpInput').focus(); }       // the one field holds the focus
});
$('jumpInput').addEventListener('input', () => { jumpAt = 0; jumpDraw(); });
$('jumpList').addEventListener('click', e => { const li = e.target.closest('[data-jump]'); if (li) jumpGo(+li.dataset.jump); });
$('jump').addEventListener('click', e => { if (e.target === $('jump')) jumpClose(); });      // the dim space around it
$('jumpBtn').addEventListener('click', jumpOpen);
