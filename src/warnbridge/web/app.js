'use strict';
const $ = id => document.getElementById(id);
let offset = 0, timezone = 'America/Chicago';
async function get(path) { const r = await fetch(path); if (!r.ok) throw new Error(`Local API: ${r.status}`); return r.json(); }
function stamp(v) { return v ? new Intl.DateTimeFormat('en-US', {dateStyle:'medium',timeStyle:'medium',timeZone:timezone}).format(new Date(v)) : 'Arrival unknown'; }
function observation(id, sourceId, value) {
  $(id).textContent = value ? stamp(value.received_at) : 'No observation';
  $(sourceId).textContent = value ? `${value.source} · processed ${stamp(value.processed_at)}` : 'No observation';
}
async function inspect(id) {
  try {
    const detail = await get(`/api/v1/messages/${id}`);
    const part = detail.classification === 'heartbeat' ? 'body' : 'xml';
    const url = `/api/v1/messages/${id}/raw?part=${part}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error('Original bytes unavailable');
    $('raw').textContent = await response.text(); // text only: never HTML/XML execution
    $('fields').textContent = JSON.stringify(detail, null, 2);
    $('detailStatus').textContent = `${detail.classification} · ${detail.delivery_count} deliveries · ${detail.sources.join(', ')} · lifecycle ${detail.lifecycle}${detail.conflict ? ' · IDENTITY CONFLICT' : ''}`;
    $('download').href = url;
    $('detail').hidden = false;
    $('detail').scrollIntoView({behavior:'smooth',block:'start'});
  } catch (e) { $('connection').textContent = e.message; }
}
async function refresh() {
  try {
    const source = encodeURIComponent($('source').value);
    const [health, metrics, messages] = await Promise.all([get('/api/v1/health'),get('/api/v1/metrics'),get(`/api/v1/messages?limit=20&offset=${offset}${source ? '&source='+source : ''}`)]);
    timezone = health.display_timezone;
    $('timezone').textContent = timezone;
    observation('heartbeat','heartbeatSource',health.last_observed.heartbeat);
    observation('linktest','linkSource',health.last_observed.link_test);
    $('count').textContent = metrics.messages;
    $('failureCount').textContent = `${metrics.retained_rejections} retained transport failures`;
    $('sessions').textContent = JSON.stringify(metrics.sessions, null, 2);
    $('messages').replaceChildren();
    for (const m of messages.items) {
      const tr = document.createElement('tr'), first = document.createElement('td');
      const button = document.createElement('button'); button.textContent = m.classification.replaceAll('_',' '); button.onclick = () => inspect(m.id);
      const code = document.createElement('small'); code.textContent = m.id.slice(0,16);
      first.append(button,code); tr.append(first);
      for (const text of [m.sources.join(', '),m.delivery_count,'CRC passed',`${m.validation.schema} / ${m.validation.signature}`]) { const td=document.createElement('td');td.textContent=text;tr.append(td); }
      $('messages').append(tr);
    }
    if (!messages.items.length) {const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='No messages yet. Import a capture or replay the included fixture.';tr.append(td);$('messages').append(tr);}
    $('page').textContent = `${messages.total ? offset+1 : 0}–${Math.min(offset+20,messages.total)} of ${messages.total}`;
    $('previous').disabled = offset===0; $('next').disabled=offset+20>=messages.total;
    $('connection').textContent='Local archive connected · reception health is reported separately';
  } catch(e) { $('connection').textContent = `Disconnected · ${e.message}`; }
}
$('refresh').onclick=refresh;
$('source').onchange=()=>{offset=0;refresh();};
$('previous').onclick=()=>{offset=Math.max(0,offset-20);refresh();};
$('next').onclick=()=>{offset+=20;refresh();};
$('close').onclick=()=>{$('detail').hidden=true;};
refresh();setInterval(refresh,15000);
