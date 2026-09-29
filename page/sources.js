/* ---------------- data sources (health.py) ----------------
   What each step did at the last company update and account sync: a source that has
   stopped working shows here the day it stops. Today's only. */
function renderHealth(){
  const H = DATA.health || [];
  $('healthCard').hidden = !H.length || !!DATA.as_of;
  if (!H.length) return;
  const failed = H.reduce((n, p) => n + p.failed, 0), waiting = H.reduce((n, p) => n + (p.waiting || 0), 0);
  const gist = [failed ? failed + ' failed at the last update' : '', waiting ? waiting + ' waiting for a key' : '']
    .filter(Boolean).join(' · ') || 'all working at the last update';
  $('healthRow').innerHTML = foldOpen('Data sources', gist) +
    H.map(p => '<div class="br-block"><div class="br-h">' + esc(p.label) + ' · ' + fmtStamp(p.at, '') + '</div>' +
      p.steps.map(st => '<div class="br-row"><span>' + esc(st.name) + '</span><span>' +
        (st.ok ? 'working' + (st.seconds != null ? ' · ' + st.seconds + ' s' : '')
               : st.setup ? '<b>waiting for a key</b>: ' + esc(st.why || '')
               : '<b>failed</b>: ' + esc(st.why || '') + ' · last worked ' + (st.last_ok ? fmtStamp(st.last_ok, '') : 'never')) +
        '</span></div>').join('') + '</div>').join('') +
    about('<p>Each source the desk reads, as it went the last time it was asked. For a full check of the keys, ' +
      'the sources and the stored data, run <code>python3 doctor.py</code> in the desk&rsquo;s folder: its report ' +
      'holds nothing private and can be pasted into a chat.</p>', 'About this') + '</details>';
}


/* ---------------- checks against the broker (checks.py) ----------------
   The desk's figures rebuilt from the account's records, set beside the broker's own: a check
   that fails says the desk has read something wrongly, before a decision rests on it. */
function renderChecks(){
  const C = DATA.checks, source = esc((C && C.source) || brokerName());
  $('checksCard').hidden = !C || (!(C.checks || []).length && !C.none_because) || !!DATA.as_of;
  if ($('checksCard').hidden) return;
  if (!(C.checks || []).length){          // an export: the desk's totals are its own, nothing to set them beside
    $('checksRow').innerHTML = foldOpen('Checks against the broker', 'none') +
      '<p class="co-note">' + esc(sentence(C.none_because)) + '</p></details>';
    return;
  }
  const failed = C.checks.filter(c => !c.ok);
  $('checksRow').innerHTML = foldOpen('Checks against ' + source, failed.length
      ? failed.map(c => c.label.toLowerCase()).join('; ') + ': ' + (failed.length > 1 ? 'do not agree' : 'does not agree')
      : 'all agree') +
    '<div class="br-block">' + C.checks.map(c => '<div class="br-row"><span>' + esc(c.label) + '</span><span>' +
      (c.ok ? 'agrees' : '<b>does not agree</b>') + ' · ' + esc(c.detail) + '</span></div>').join('') + '</div>' +
    about('<p>At every build the desk rebuilds what it can from the account&rsquo;s records (each trade, deposit, ' +
      'dividend, fee and split) and sets it beside what ' + source + ' states itself. When one does not agree, a figure ' +
      'built on that part of the record may be wrong: check it in ' + source + ' before relying on it.</p>', 'About this') +
    '</details>';
}
