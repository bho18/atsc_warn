'use strict';
const $ = id => document.getElementById(id);
let offset = 0, view = 'deliveries', timezone = 'America/Chicago';
let refreshPending = false;
let refreshSerial = 0, inspectSerial = 0, historySerial = 0;
let selectedMessage = null, historyOffset = 0;
const sourceNames = {live_hdhomerun:'Live HDHomeRun',live_udp:'Live UDP',replay:'Replay',file:'File import',stdin:'Stdin'};
const sourceName = source => sourceNames[source] || source;
async function get(path, format = 'json') {
  const controller = new AbortController();
  const deadline = setTimeout(()=>controller.abort(),8000);
  try {
    const r = await fetch(path,{signal:controller.signal});
    if (!r.ok) throw new Error(`Local API: ${r.status}`);
    return format==='text' ? await r.text() : await r.json();
  } finally { clearTimeout(deadline); }
}
function stamp(value) {
  if (!value) return 'Arrival unknown';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('en-US', {
    dateStyle:'medium',timeStyle:'medium',timeZone:timezone
  }).format(parsed);
}
function observation(id, sourceId, value) {
  $(id).textContent = value ? stamp(value.received_at) : 'No observation';
  $(sourceId).textContent = value ? `${sourceName(value.source)} · processed ${stamp(value.processed_at)}` : 'No observation';
}
function renderRF(health) {
  const receiver = health.receiver;
  const labels = {not_checked:'Not checked',no_lock:'No RF lock',locked:'RF locked',stale:'Status stale',unavailable:'Status unavailable',stopped:'Receiver stopped'};
  const state = health.rf_tuner;
  $('rf').textContent = state === 'locked' && receiver?.fields?.lock === '8vsb' ? '8-VSB locked' : (labels[state] || state);
  $('rf').className = state === 'locked' ? 'state-ok' : ['stale','unavailable','no_lock'].includes(state) ? 'state-warning' : '';
  if (!receiver) {
    $('rfMeta').textContent = 'Start the listener to poll tuner status';
    $('rfSignal').textContent = '';
    return;
  }
  const f = receiver.fields;
  const value = key => /^\d+$/.test(f[key] || '') ? `${f[key]}%` : '—';
  $('rfMeta').textContent = `${receiver.host} · tuner ${receiver.tuner} · ${f.ch || 'channel unknown'}`;
  const age = receiver.age_seconds === null ? 'time unknown' : `${Math.round(receiver.age_seconds)}s ago`;
  $('rfSignal').textContent = receiver.error ? `Checked ${age} · ${receiver.error}` : `Strength ${value('ss')} · Quality ${value('snq')} · Symbol ${value('seq')} · checked ${age}`;
}
function query(extra = {}) {
  const params = new URLSearchParams(extra);
  if ($('source').value) params.set('source',$('source').value);
  return params;
}
function cell(row, text, small) {
  const td = document.createElement('td');
  td.textContent = String(text);
  if (small) { const hint=document.createElement('small'); hint.textContent=small;td.append(hint); }
  row.append(td);
  return td;
}
function messageCell(row, item, delivery = null) {
  const td = document.createElement('td'), button = document.createElement('button');
  button.textContent = item.classification.replaceAll('_',' ');
  button.onclick = () => inspect(delivery ? item.message_id : item.id, delivery);
  const identity=document.createElement('small');
  identity.textContent = item.protocol_identifier || (delivery ? item.message_id : item.id).slice(0,16);
  td.append(button,identity);
  if (item.declared_sent) {const sent=document.createElement('small');sent.textContent=`XML sent ${stamp(item.declared_sent)}`;td.append(sent);}
  row.append(td);
}
async function loadHistory() {
  if (!selectedMessage) return;
  const serial = ++historySerial, mid = selectedMessage;
  const params = query({message_id:mid,limit:10,offset:historyOffset});
  const data = await get(`/api/v1/deliveries?${params}`);
  if (serial !== historySerial || mid !== selectedMessage) return;
  $('history').replaceChildren();
  for (const d of data.items) {
    const row = document.createElement('tr');
    const first = cell(row,'');
    const button=document.createElement('button');button.textContent=`#${d.id}`;
    button.onclick=()=>inspect(d.message_id,d,false);
    first.append(button);
    cell(row,d.received_at ? stamp(d.received_at) : 'Arrival unknown',`Processed ${stamp(d.processed_at)}`);
    cell(row,sourceName(d.source),d.source_identity);
    cell(row,d.transport_id_hex || 'Unknown');
    cell(row,d.stored_crc === d.calculated_crc ? 'CRC passed' : 'CRC mismatch');
    $('history').append(row);
  }
  $('historyPage').textContent = `${data.total ? historyOffset+1 : 0}–${Math.min(historyOffset+10,data.total)} of ${data.total} deliveries`;
  $('historyPrevious').disabled=historyOffset===0;
  $('historyNext').disabled=historyOffset+10>=data.total;
}
async function inspect(id, delivery = null, resetHistory = true) {
  const serial = ++inspectSerial;
  selectedMessage=id;
  if (resetHistory) historyOffset=0;
  try {
    const detail = await get(`/api/v1/messages/${id}`);
    const part=detail.classification==='heartbeat' ? 'body' : 'xml';
    const params = new URLSearchParams({part});
    if (delivery) params.set('observation',delivery.id);
    const url=`/api/v1/messages/${id}/raw?${params}`;
    const raw=await get(url,'text');
    if (serial!==inspectSerial) return;
    $('raw').textContent=raw;
    $('fields').textContent=JSON.stringify({content_id:id,classification:detail.classification,validation:detail.validation,
      fields:detail.fields,selected_delivery:delivery,identity:detail.identity,conflict:detail.conflict},null,2);
    $('detailStatus').textContent=`${detail.classification.replaceAll('_',' ')} · ${detail.delivery_count} deliveries across all sources · ${delivery ? `selected #${delivery.id}` : 'grouped content'}${detail.conflict ? ' · IDENTITY CONFLICT' : ''}`;
    $('download').href=url;
    $('detail').hidden=false;
    await loadHistory();
    if (resetHistory) $('detail').scrollIntoView({behavior:'smooth',block:'start'});
  } catch (error) { $('connection').textContent=error.message; }
}
async function refresh(force = false) {
  if (refreshPending && !force) return;
  refreshPending=true;
  const serial=++refreshSerial;
  try {
    const params=query({limit:20,offset});
    if ($('classification').value) params.set('classification',$('classification').value);
    const [health,metrics,data]=await Promise.all([get('/api/v1/health'),get('/api/v1/metrics'),get(`/api/v1/${view==='deliveries' ? 'deliveries' : 'messages'}?${params}`)]);
    if (serial!==refreshSerial) return;
    timezone=health.display_timezone;
    $('timezone').textContent=timezone;
    renderRF(health);
    observation('heartbeat','heartbeatSource',health.last_observed.heartbeat);
    observation('linktest','linkSource',health.last_observed.link_test);
    $('count').textContent=`${metrics.messages} contents`;
    $('failureCount').textContent=`${metrics.deliveries} deliveries · ${metrics.retained_rejections} retained failures`;
    $('sessions').textContent=JSON.stringify(metrics.sessions,null,2);
    $('messages').replaceChildren();
    $('viewHelp').textContent=view==='deliveries' ? 'Every reception gets a row, including repeated heartbeats and Link Tests.' : 'Identical content is grouped. Repeated broadcasts increase the delivery count; heartbeat content is constant.';
    $('timeHeading').textContent=view==='deliveries' ? 'Received / source' : 'Last receipt / source';
    $('countHeading').textContent=view==='deliveries' ? 'Delivery' : 'Deliveries';
    for (const item of data.items) {
      const row=document.createElement('tr');
      const delivery=view==='deliveries';
      messageCell(row,item,delivery ? item : null);
      const received=delivery ? item.received_at : item.last_received_at;
      const processed=delivery ? item.processed_at : item.last_processed_at;
      const sources=delivery ? sourceName(item.source) : item.sources.map(sourceName).join(', ');
      cell(row,received ? stamp(received) : 'Arrival unknown',`${sources} · processed ${stamp(processed)}`);
      cell(row,delivery ? `#${item.id}` : item.delivery_count,delivery ? (item.repeated_content ? 'Repeated content' : 'First content observation') : (item.first_received_at ? `First receipt ${stamp(item.first_received_at)}` : `First imported ${stamp(item.first_processed_at)}`));
      cell(row,'CRC passed');
      cell(row,`${item.validation.schema} / ${item.validation.signature}`);
      $('messages').append(row);
    }
    if (!data.items.length) {const row=document.createElement('tr'),td=cell(row,'No matching messages yet.');td.colSpan=5;$('messages').append(row);}
    $('page').textContent=`${data.total ? offset+1 : 0}–${Math.min(offset+20,data.total)} of ${data.total} ${view==='deliveries' ? 'deliveries' : 'contents'}`;
    $('previous').disabled=offset===0;
    $('next').disabled=offset+20>=data.total;
    $('connection').textContent='Local archive connected · status refreshes every 5 seconds';
    if (!$('detail').hidden) await loadHistory();
  } catch (error) {
    if (serial===refreshSerial) {
      $('connection').textContent=`Disconnected · ${error.message}`;
      $('rf').textContent='Status unavailable';
      $('rf').className='state-warning';
      $('rfSignal').textContent='Cannot refresh receiver status';
    }
  } finally { if (serial===refreshSerial) refreshPending=false; }
}
function changeView(next) {
  view=next;offset=0;
  $('deliveriesTab').setAttribute('aria-selected',String(view==='deliveries'));
  $('contentTab').setAttribute('aria-selected',String(view==='content'));
  refresh(true);
}
$('deliveriesTab').onclick=()=>changeView('deliveries');
$('contentTab').onclick=()=>changeView('content');
$('refresh').onclick=()=>refresh(true);
for (const id of ['source','classification']) $(id).onchange=()=>{offset=0;selectedMessage=null;++inspectSerial;++historySerial;$('detail').hidden=true;refresh(true);};
$('previous').onclick=()=>{offset=Math.max(0,offset-20);refresh(true);};
$('next').onclick=()=>{offset+=20;refresh(true);};
$('historyPrevious').onclick=()=>{historyOffset=Math.max(0,historyOffset-10);loadHistory().catch(e=>{$('connection').textContent=e.message;});};
$('historyNext').onclick=()=>{historyOffset+=10;loadHistory().catch(e=>{$('connection').textContent=e.message;});};
$('close').onclick=()=>{selectedMessage=null;++inspectSerial;++historySerial;$('detail').hidden=true;};
refresh();setInterval(()=>refresh(),5000);
