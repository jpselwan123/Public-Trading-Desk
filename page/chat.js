/* ---------------- Ask: the chat beside the page (chat.py) ---------------- */
// A question goes to the desk, which answers it with the owner's OpenAI model from the figures it holds for the company on show.
// The page draws the conversation and decides nothing: what the model is told, and what it may say, are chat.py's. It sends no
// order and changes nothing but its own conversation. The "include my holdings" box is the owner's, per question, remembered here.
let chatCtx = null, chatBusy = false, chatLoaded = false, chatTurns = [];

function chatContext(){
  if (currentPage === 'chart' && pcx.ticker) return {ticker: pcx.ticker, range: pcx.range, what: 'chart'};
  if (currentPage === 'companies' && typeof coPick !== 'undefined' && coPick) return {ticker: coPick, what: 'company'};
  return null;
}
function chatSuggestions(){
  const t = chatCtx && chatCtx.ticker;
  if (!t) return [{q: 'What should I look at today?', mine: true}, {q: 'What does P/E mean?'}];
  return (chatCtx.what === 'chart' ? [{q: 'Explain this chart'}] : [{q: 'How is it doing against the market?'}])
    .concat([{q: 'What changed lately?'}, {q: 'What should I check next?'}]);
}
// the answer as text, safely: paragraphs, and lines that start with a dash as a list
function chatHtml(text){
  const out = [];
  let list = null;
  String(text || '').split('\n').forEach(line => {
    const m = line.match(/^\s*[-•*]\s+(.*)$/);
    if (m){ if (!list){ list = []; out.push(list); } list.push(m[1]); }
    else { list = null; if (line.trim()) out.push(line.trim()); }
  });
  return out.map(x => Array.isArray(x) ? '<ul>' + x.map(i => '<li>' + esc(i) + '</li>').join('') + '</ul>' : '<p>' + esc(x) + '</p>').join('');
}
function chatDraw(){
  const log = $('chatLog');
  $('chatCtx').textContent = chatCtx && chatCtx.ticker ? chatCtx.ticker + (chatCtx.what === 'chart' ? ' · ' + chatCtx.range + ' chart' : '') : '';
  log.innerHTML = chatTurns.length ? chatTurns.map(t => t.role === 'user'
    ? '<div class="cb cb-u">' + esc(t.text) + '</div>'
    : '<div class="cb cb-a' + (t.error ? ' cb-err' : '') + '">' + (t.pending ? '<span class="faint">Thinking…</span>' : chatHtml(t.text)) + '</div>').join('')
    : '<div class="cb cb-a"><p class="faint">Ask about the company on show, or how something works. I answer from the figures the dashboard holds, and I don’t advise.</p></div>';
  log.scrollTop = log.scrollHeight;
  $('chatSugg').innerHTML = chatTurns.length > 1 ? '' : chatSuggestions().map((s, i) =>
    '<button type="button" class="chat-chip" data-sugg="' + i + '">' + esc(s.q) + '</button>').join('');
  $('chatSend').disabled = chatBusy;
}
async function chatPost(body){
  if (location.protocol === 'file:') return {ok: false, message: 'Open the desk through its server to ask.'};
  try {
    const r = await fetch('/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    return await r.json();
  } catch(e){ return {ok: false, message: 'Could not reach the desk.'}; }
}
async function chatLoad(){
  chatLoaded = true;
  const res = await chatPost({op: 'history'});
  if (res.ok) chatTurns = res.turns || [];
  chatDraw();
}
function openChat(ctx){
  if (DATA.as_of) return;
  chatCtx = ctx && ctx.ticker ? Object.assign({what: ctx.range ? 'chart' : 'company'}, ctx) : chatContext();
  try { $('chatMine').checked = localStorage.getItem('deskChatMine') === '1'; } catch(e){}
  $('chat').hidden = false;
  chatDraw();
  if (!chatLoaded) chatLoad();
  $('chatInput').focus();
}
function closeChat(){ $('chat').hidden = true; }
async function chatSend(text){
  text = String(text || $('chatInput').value).trim();
  if (!text || chatBusy) return;
  chatBusy = true;
  $('chatInput').value = '';
  chatTurns = chatTurns.concat([{role: 'user', text}, {role: 'assistant', text: '', pending: true}]);
  chatDraw();
  const res = await chatPost({message: text, ticker: chatCtx && chatCtx.ticker, range: chatCtx && chatCtx.range, mine: $('chatMine').checked});
  chatBusy = false;
  if (res.ok) chatTurns = res.turns || [];
  else chatTurns = chatTurns.slice(0, -1).concat([{role: 'assistant', text: res.message || 'No answer.', error: true}]);
  chatDraw();
  $('chatInput').focus();
}
function renderAsk(){
  const off = !!DATA.as_of;
  $('askBtn').hidden = off;
  if (off) closeChat();
}
$('askBtn').addEventListener('click', () => { if ($('chat').hidden) openChat(); else closeChat(); });
$('chatClose').addEventListener('click', closeChat);
$('chatForm').addEventListener('submit', ev => { ev.preventDefault(); chatSend(); });
$('chatMine').addEventListener('change', () => { try { localStorage.setItem('deskChatMine', $('chatMine').checked ? '1' : '0'); } catch(e){} });
$('chatClear').addEventListener('click', async () => {
  const res = await chatPost({op: 'clear'});
  if (res.ok){ chatTurns = []; chatDraw(); }
});
$('chatSugg').addEventListener('click', ev => {
  const b = ev.target.closest('[data-sugg]');
  if (!b) return;
  const s = chatSuggestions()[+b.dataset.sugg];
  if (s.mine){ $('chatMine').checked = true; }
  chatSend(s.q);
});
document.addEventListener('click', ev => {
  const b = ev.target.closest('[data-ask]');
  if (b){ ev.preventDefault(); openChat({ticker: b.dataset.ask}); }
});
document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !$('chat').hidden && $('chat').contains(document.activeElement)) closeChat(); });
