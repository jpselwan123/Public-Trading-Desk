/* ---------------- pages ---------------- */
// Seven tabs over the eleven sections: each tab one subject, its sections in reading order.
// An old address (#journal, #filings) opens the tab that holds it, at that section.
const TABS = [
  {id:'overview',  label:'Overview',  pages:['overview']},
  {id:'portfolio', label:'Portfolio', pages:['portfolio'], count: () => DATA.positions && DATA.positions.count},
  {id:'history',   label:'History',   pages:['history']},
  {id:'companies', label:'Companies', pages:['companies', 'news', 'filings'], count: () => (DATA.companies || []).length},
  {id:'chart',     label:'Chart',     pages:['chart']},
  {id:'research',  label:'Research',  pages:['research', 'screener']},
  {id:'trades',    label:'Trades',    pages:['journal', 'practice'], count: () => DATA.trades && DATA.trades.count},
];
let currentPage = 'overview';
function renderNav(){
  $('nav').innerHTML = TABS.map(p => {
    const n = p.count ? p.count() : null;
    return '<button role="tab" data-page="' + p.id + '"' + (p.id === currentPage ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' +
      p.label + (n ? '<span class="count">' + n + '</span>' : '') + '</button>';
  }).join('');
}
function showPage(id, push){
  const tab = TABS.find(t => t.id === id) || TABS.find(t => t.pages.includes(id)) || TABS[0];
  const section = tab.pages.includes(id) && id !== tab.pages[0] ? id : null;
  currentPage = tab.id;
  TABS.forEach(t => t.pages.forEach(p => $('page-' + p).classList.toggle('on', t === tab)));
  renderNav();
  const hash = section || tab.id;
  if (push !== false && location.hash !== '#' + hash) location.hash = hash;
  if (section) $('page-' + section).scrollIntoView({block: 'start'});
  else window.scrollTo({top: 0, behavior: 'instant'});
  if (tab.id === 'chart' && typeof renderChart === 'function') safe(renderChart);       // it draws and loads when it comes on show
}
$('nav').addEventListener('click', e => {
  const b = e.target.closest('button[data-page]');
  if (b) showPage(b.dataset.page);
});
$('nav').addEventListener('keydown', e => {
  const i = TABS.findIndex(p => p.id === currentPage);
  if (e.key === 'ArrowRight') showPage(TABS[(i + 1) % TABS.length].id);
  if (e.key === 'ArrowLeft') showPage(TABS[(i - 1 + TABS.length) % TABS.length].id);
});
window.addEventListener('hashchange', () => showPage(location.hash.slice(1), false));

