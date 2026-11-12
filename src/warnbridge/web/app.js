'use strict';
const $ = id => document.getElementById(id);
let offset = 0, mode = 'alerts', view = 'deliveries', timezone = 'America/Chicago';
let failureOffset = 0, cancellationOffset = 0;
let refreshPending = false;
let refreshSerial = 0, inspectSerial = 0, historySerial = 0;
let selectedMessage = null, historyOffset = 0, selectedDelivery = null, selectedAlertState = '';
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
let heartbeatSnapshot = null, heartbeatAt = 0, heartbeatOnline = false, heartbeatId = null;
const lifecycleNames = {active:'Active',non_actual:'Non-Actual message',scheduled:'Future effective time',expired:'Expired',cancellation:'Cancellation message',cancelled:'Cancelled',superseded:'Superseded by update',identity_conflict:'Identity conflict · review',reference_review:'References need review',provenance_review:'Select a source to review',unverified_cmac:'CMAC · needs field review',acknowledgement:'Acknowledgement',error_message:'Error message',unknown:'Status unknown'};
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}
function badge(text, tone = '') { return node('span',text,`badge ${tone}`); }
function renderHeartbeat(snapshot) {
  if (snapshot) { heartbeatSnapshot=snapshot;heartbeatAt=performance.now();heartbeatOnline=true; }
  const dot=$('heartbeatDot'), h=heartbeatSnapshot;
  let state=heartbeatOnline ? (h?.state || 'waiting') : 'unavailable';
  const age=h?.age_seconds === null || !h ? null : h.age_seconds+(performance.now()-heartbeatAt)/1000;
  if (state==='recent' && (age===null || age>h.stale_after_seconds)) state='stale';
  const labels={recent:'Live heartbeat',stale:'Heartbeat overdue',stopped:'Receiver stopped',waiting:'Waiting for heartbeat',unavailable:'Connection unknown'};
  $('heartbeat').textContent=labels[state];
  dot.classList.toggle('recent',state==='recent');
  dot.classList.toggle('stale',state==='stale');
  if (state!=='recent') dot.classList.remove('beat');
  if (state==='recent' && h.last_heartbeat.id!==heartbeatId) {
    heartbeatId=h.last_heartbeat.id;
    dot.classList.remove('beat');void dot.offsetWidth;dot.classList.add('beat');
    dot.dataset.observation=String(heartbeatId);
  }
  $('heartbeatSource').textContent=h?.last_heartbeat
    ? `${sourceName(h.last_heartbeat.source)} · ${stamp(h.last_heartbeat.received_at)} · ${Math.floor(age || 0)}s ago${state==='unavailable' ? ' · API unavailable' : ''}`
    : 'Live reception only · replay does not affect this indicator';
}
function metadata(parent, entries) {
  const dl=node('dl',null,'alert-meta');
  for (const [key,value] of entries) {const group=node('div');group.append(node('dt',key),node('dd',value || 'Not supplied'));dl.append(group);}
  parent.append(dl);
}
function alertBadges(parent, item) {
  const a=item.alert, badges=node('div',null,'badges');
  badges.append(badge(a.status || 'Unknown',a.status==='Actual' ? 'actual' : ''),badge(a.message_type || 'Type unknown'),badge(a.protocol));
  for (const source of item.sources) badges.append(badge(sourceName(source),source.startsWith('live_') ? '' : 'review'));
  badges.prepend(badge(lifecycleNames[a.lifecycle] || a.lifecycle,`lifecycle ${a.lifecycle}`));
  parent.append(badges);
}
function renderAlerts(data) {
  $('alertCards').replaceChildren();
  for (const item of data.items) {
    const a=item.alert, info=a.infos[0], card=node('article',null,`alert-card ${a.status==='Actual' ? '' : 'non-actual'} ${a.protocol==='unknown' || item.conflict ? 'review' : ''}`);
    alertBadges(card,item);
    const title=node('button',a.headline,'alert-title');title.onclick=()=>inspect(item.id);card.append(title);
    if (info) {
      card.append(node('p',[info.severity,info.urgency,info.certainty].filter(Boolean).join(' · ')));
      if (info.description) card.append(node('p',info.description,'alert-preview'));
    } else if (a.protocol==='CMAC' && a.preview) card.append(node('p',a.preview,'alert-preview'));
    if(item.validation.xml==='invalid' || a.protocol==='unknown') card.append(node('p','Content needs review. Original bytes are available in the inspector.','state-warning'));
    card.append(node('p',`${a.sender || 'Sender unknown'} · ${a.identifier || 'Identifier unknown'}`,'content-identity'));
    metadata(card,[['Received',item.last_received_at ? stamp(item.last_received_at) : 'Arrival unknown'],['XML sent',a.sent ? stamp(a.sent) : 'Not supplied'],['Expires',info?.expires || a.expires?.[0] ? stamp(info?.expires || a.expires[0]) : 'Not supplied'],['Deliveries',String(item.delivery_count)]]);
    $('alertCards').append(card);
  }
  if (!data.items.length) {
    const empty=node('div',null,'empty');empty.append(node('h3','No matching alerts received'),node('p',$('source').value==='live' ? 'Live alerts will appear here when received. Heartbeats and Link Tests check the path; they are available in Diagnostics. Choose replay to explore the synthetic alert demo.' : 'No alert content matches this source and status. Check Diagnostics for heartbeat and Link Test traffic.'));
    $('alertCards').append(empty);
  }
}
function renderInfo(parent, info) {
  window.WarnBridgeMap.clear();
  parent.replaceChildren();
  metadata(parent,[['Event',info.event],['Severity',info.severity],['Urgency',info.urgency],['Certainty',info.certainty],['Effective',info.effective ? stamp(info.effective) : 'Not supplied'],['Onset',info.onset ? stamp(info.onset) : 'Not supplied'],['Expires',info.expires ? stamp(info.expires) : 'Not supplied'],['Sender name',info.senderName],['Response',info.responseType.join(', ')]]);
  if(info.headline) parent.append(node('h3',info.headline));
  if(info.description) parent.append(node('p',info.description,'message-text'));
  if(info.instruction) {const box=node('div',null,'instructions');box.append(node('h4','Instructions'),node('p',info.instruction,'message-text'));parent.append(box);}
  if(info.parameters.length) {parent.append(node('h4','Message parameters / wireless alert text'));const dl=node('dl',null,'field-list');for(const p of info.parameters)dl.append(node('dt',p.name || 'Unnamed parameter'),node('dd',p.value));parent.append(dl);}
  parent.append(node('h4','Affected areas'));
  window.WarnBridgeMap.render(parent,info.areas);
  const list=node('div',null,'area-list');
  for(const [i,area] of info.areas.entries()) {const box=node('div',null,'area');box.append(node('h4',`${i+1}. ${area.description || 'Unnamed area'}`));for(const code of area.geocodes)box.append(node('p',`${code.name || 'Geocode'}: ${code.value}`));for(const p of area.polygons)box.append(node('p',`Polygon (lat,lon): ${p}`));for(const c of area.circles)box.append(node('p',`Circle (lat,lon; radius km): ${c}`));if(area.altitude)box.append(node('p',`Altitude: ${area.altitude} ft${area.ceiling ? ` · ceiling ${area.ceiling} ft` : ''}`));for(const issue of area.geometry.issues)box.append(node('p',`Plot omitted: ${issue}`,'state-warning'));list.append(box);}
  parent.append(list);
  if(info.event_codes.length) parent.append(node('p',`Event codes: ${info.event_codes.map(p=>`${p.name}: ${p.value}`).join(' · ')}`,'muted'));
  if(info.web) parent.append(node('p',`Web reference (not fetched): ${info.web}`,'muted'));
}
function renderAlertDetail(item) {
  window.WarnBridgeMap.clear();
  selectedAlertState=JSON.stringify([item.alert,item.relationships,item.conflict]);
  const target=$('alertDetail');target.replaceChildren();
  if(!item.alert) {$('evidence').open=true;return;}
  $('evidence').open=false;
  const a=item.alert,body=node('div',null,'alert-body');
  alertBadges(body,item);
  metadata(body,[['Sender / gateway',a.sender],['Identifier',a.identifier],['XML sent',a.sent ? stamp(a.sent) : 'Not supplied'],['Scope',a.scope || 'Not supplied'],['Last receipt',item.last_received_at ? stamp(item.last_received_at) : 'Arrival unknown'],['Timing / references',lifecycleNames[a.lifecycle] || a.lifecycle]]);
  if(a.infos.length) {
    const label=node('label','Language / information block','language-label'),select=node('select');select.id='alertLanguage';
    for(const [i,info] of a.infos.entries()) {const option=node('option',`${info.language} · ${info.event || `block ${i+1}`}`);option.value=String(i);select.append(option);}
    label.append(select);body.append(label);
    const content=node('div');body.append(content);renderInfo(content,a.infos[0]);select.onchange=()=>renderInfo(content,a.infos[Number(select.value)]);
  } else if(a.protocol==='CMAC') {
    if(a.preview)body.append(node('h3','Message text'),node('p',a.preview,'message-text'));
    const fields=node('details');fields.append(node('summary','Original CMAC fields'));
    const dl=node('dl',null,'field-list');for(const segment of a.segments)dl.append(node('dt',segment.field),node('dd',segment.value));fields.append(dl);body.append(fields);
  } else body.append(node('p','No information blocks supplied. A cancellation can refer to an earlier alert without repeating its text.'));
  if(a.cancellations?.length) {
    const section=node('section',null,'cancellation-content');section.append(node('h3','Cancellation details'));
    for(const cancellation of a.cancellations) {
      section.append(node('p',`Cancelled · ${stamp(cancellation.sent)}`));
      for(const info of cancellation.infos) {
        const block=node('div',null,'cancellation-info');
        block.append(node('h4',`${info.language} · ${info.headline || info.event || 'Cancellation'}`));
        if(info.description)block.append(node('p',info.description,'message-text'));
        if(info.instruction)block.append(node('p',info.instruction,'instructions message-text'));
        for(const parameter of info.parameters)block.append(node('p',`${parameter.name}: ${parameter.value}`,'message-text'));
        for(const area of info.areas)block.append(node('p',area.description));
        section.append(block);
      }
      const button=node('button','Inspect full cancellation');button.onclick=()=>inspect(cancellation.message_id);section.append(button);
    }
    body.append(section);
  }
  const relationships=node('div',null,'relationships');
  if(a.references)relationships.append(node('h4','Declared references'),node('p',a.references,'message-text'));
  if(item.relationships?.length) for(const ref of item.relationships) {
    const matches=ref.resolved_message_ids || [];const row=node('p',`${ref.kind}: ${matches.length===1 ? 'one matching message' : matches.length ? 'ambiguous identity' : 'referenced message not received in this source group'}`);for(const mid of matches) {const b=node('button','Inspect referenced message');b.onclick=()=>inspect(mid);row.append(b);}relationships.append(row);
  }
  if(a.relationships.length) {relationships.append(node('h4','Later references in this source group'));for(const ref of a.relationships) {const b=node('button',`${ref.type} · ${stamp(ref.sent)}`);b.onclick=()=>inspect(ref.message_id);relationships.append(b);}}
  for(const issue of a.issues)relationships.append(node('p',issue,'state-warning'));
  body.append(relationships);target.append(body);
}

function query(extra = {}) {
  const params = new URLSearchParams(extra);
  if ($('source').value) params.set('source',$('source').value);
  return params;
}
function renderFailures(data) {
  $('failureItems').replaceChildren();
  for(const item of data.items) {
    const row=node('div',null,'diagnostic-row');
    row.append(node('p',`#${item.id} · ${item.reason} · ${stamp(item.received_at || item.processed_at)} · ${item.bytes} TS bytes`));
    for(const [part,label] of [['raw_ts','Download packets'],['assembled','Download assembled message'],['header','Download header']]) {
      const link=node('a',label);link.href=`/api/v1/diagnostics/${item.id}/raw?part=${part}`;row.append(link);
    }
    $('failureItems').append(row);
  }
  if(!data.total)$('failureItems').append(node('p','No retained failures.'));
  $('failurePage').textContent=`${data.total ? failureOffset+1 : 0}–${Math.min(failureOffset+10,data.total)} of ${data.total}`;
  $('failurePrevious').disabled=failureOffset===0;
  $('failureNext').disabled=failureOffset+10>=data.total;
}
function renderCancellations(data) {
  $('cancellationSummary').textContent=`Cancellation history · ${data.total}`;
  $('cancellationItems').replaceChildren();
  for(const item of data.items) {
    const row=node('div',null,'diagnostic-row'),button=node('button',`Inspect cancellation · ${stamp(item.alert.sent)}`);
    button.onclick=()=>inspect(item.id);
    row.append(button,node('p',`${item.alert.sender || 'Sender unknown'} · ${item.alert.identifier || 'Identifier unknown'}`));
    $('cancellationItems').append(row);
  }
  if(!data.total)$('cancellationItems').append(node('p','No cancellations received in this source group.'));
  $('cancellationPage').textContent=`${data.total ? cancellationOffset+1 : 0}–${Math.min(cancellationOffset+10,data.total)} of ${data.total}`;
  $('cancellationPrevious').disabled=cancellationOffset===0;
  $('cancellationNext').disabled=cancellationOffset+10>=data.total;
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
  selectedMessage=id;selectedDelivery=delivery;
  if (resetHistory) historyOffset=0;
  try {
    const detail = await get(`/api/v1/messages/${id}?${query()}`);
    const part=detail.classification==='heartbeat' ? 'body' : 'xml';
    const params = new URLSearchParams({part});
    if (delivery) params.set('observation',delivery.id);
    const url=`/api/v1/messages/${id}/raw?${params}`;
    const raw=await get(`/api/v1/messages/${id}/text?${params}`,'text');
    if (serial!==inspectSerial) return;
    $('raw').textContent=raw;
    $('fields').textContent=JSON.stringify({content_id:id,classification:detail.classification,validation:detail.validation,
      fields:detail.fields,selected_delivery:delivery,identity:detail.identity,conflict:detail.conflict},null,2);
    $('detailStatus').textContent=`${detail.classification.replaceAll('_',' ')} · ${detail.delivery_count} deliveries in this source filter · ${delivery ? `selected #${delivery.id}` : 'grouped content'}${detail.conflict ? ' · IDENTITY CONFLICT' : ''}`;
    $('download').href=url;
    renderAlertDetail(detail);
    $('detail').hidden=false;
    await loadHistory();
    if (resetHistory) $('detail').scrollIntoView({behavior:'smooth',block:'start'});
  } catch (error) { $('connection').textContent=error.message; }
}
async function refreshInspection() {
  const mid=selectedMessage, serial=inspectSerial;
  if(!mid) return;
  const item=await get(`/api/v1/messages/${mid}?${query()}`);
  if(mid!==selectedMessage || serial!==inspectSerial) return;
  const signature=JSON.stringify([item.alert,item.relationships,item.conflict]);
  if(signature!==selectedAlertState) {
    const language=$('alertLanguage')?.value, evidenceOpen=$('evidence').open;
    renderAlertDetail(item);
    const select=$('alertLanguage');
    if(select && language!==undefined && Number(language)<select.options.length) {select.value=language;select.onchange();}
    $('evidence').open=evidenceOpen;
  }
  $('detailStatus').textContent=`${item.classification.replaceAll('_',' ')} · ${item.delivery_count} deliveries in this source filter · ${selectedDelivery ? `selected #${selectedDelivery.id}` : 'grouped content'}${item.conflict ? ' · IDENTITY CONFLICT' : ''}`;
  await loadHistory();
}
async function refresh(force = false) {
  if (refreshPending && !force) return;
  refreshPending=true;
  const serial=++refreshSerial;
  try {
    const params=query({limit:20,offset});
    if ($('classification').value) params.set('classification',$('classification').value);
    if (mode==='alerts') {params.set('source',$('source').value || 'all');if ($('alertStatus').value) params.set('status',$('alertStatus').value);params.delete('classification');}
    const endpoint=mode==='alerts' ? 'alerts' : view==='deliveries' ? 'deliveries' : 'messages';
    const cancelParams=query({cancellations:true,limit:10,offset:cancellationOffset});
    if(!cancelParams.has('source'))cancelParams.set('source','all');
    const [health,metrics,data,failures,cancellations]=await Promise.all([get('/api/v1/health'),get('/api/v1/metrics'),get(`/api/v1/${endpoint}?${params}`),get(`/api/v1/diagnostics?limit=10&offset=${failureOffset}`), mode==='alerts' ? get(`/api/v1/alerts?${cancelParams}`) : Promise.resolve(null)]);
    if (serial!==refreshSerial) return;
    timezone=health.display_timezone;
    $('storageNotice').hidden=!health.storage || health.storage.state==='ok';
    if(health.storage && health.storage.state!=='ok') $('storageNotice').textContent=`Archive ${health.storage.state==='full' ? 'limit reached — reception stops' : 'nearing its limit'}: ${Math.round(health.storage.bytes/1048576)} of ${Math.round(health.storage.limit_bytes/1048576)} MiB. Archive data or increase the configured archive limit.`;
    $('timezone').textContent=timezone;
    renderRF(health);
    renderHeartbeat(health.connection);
    observation('linktest','linkSource',health.last_observed.link_test);
    $('countLabel').textContent=mode==='alerts' ? `ALERT CONTENT · ${$('source').value==='live' ? 'LIVE' : 'FILTERED'}` : 'ARCHIVE TOTAL';
    $('count').textContent=mode==='alerts' ? data.total : `${metrics.messages} contents`;
    $('failureCount').textContent=`${metrics.deliveries} deliveries · ${metrics.retained_rejections} retained failures`;
    renderFailures(failures);
    if(cancellations)renderCancellations(cancellations);
    $('sessions').textContent=JSON.stringify(metrics.sessions,null,2);
    $('messages').replaceChildren();
    if (mode==='alerts') renderAlerts(data);
    $('viewHelp').textContent=mode==='alerts' ? 'Received messages and their current status. Heartbeats and Link Tests are in Diagnostics.' : view==='deliveries' ? 'Every reception gets a row, including repeated heartbeats and Link Tests.' : 'Identical content is grouped. Repeated broadcasts increase the delivery count; heartbeat content is constant.';
    $('timeHeading').textContent=view==='deliveries' ? 'Received / source' : 'Last receipt / source';
    $('countHeading').textContent=view==='deliveries' ? 'Delivery' : 'Deliveries';
    for (const item of mode==='diagnostics' ? data.items : []) {
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
    $('page').textContent=`${data.total ? offset+1 : 0}–${Math.min(offset+20,data.total)} of ${data.total} ${mode==='alerts' ? 'alert contents' : view==='deliveries' ? 'deliveries' : 'contents'}`;
    $('previous').disabled=offset===0;
    $('next').disabled=offset+20>=data.total;
    $('connection').textContent='Local archive connected · status refreshes every 5 seconds';
    if (!$('detail').hidden) await refreshInspection();
  } catch (error) {
    if (serial===refreshSerial) {
      $('connection').textContent=`Disconnected · ${error.message}`;
      $('rf').textContent='Status unavailable';
      $('rf').className='state-warning';
      $('rfSignal').textContent='Cannot refresh receiver status';
      heartbeatOnline=false;renderHeartbeat();
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
$('failureCount').onclick=()=>{$('failurePanel').open=true;$('failurePanel').scrollIntoView({behavior:'smooth'});};
for(const [id,delta] of [['failurePrevious',-10],['failureNext',10]]) $(id).onclick=()=>{failureOffset=Math.max(0,failureOffset+delta);refresh(true);};
for(const [id,delta] of [['cancellationPrevious',-10],['cancellationNext',10]]) $(id).onclick=()=>{cancellationOffset=Math.max(0,cancellationOffset+delta);refresh(true);};
for (const id of ['source','classification','alertStatus']) $(id).onchange=()=>{offset=0;cancellationOffset=0;selectedMessage=null;++inspectSerial;++historySerial;window.WarnBridgeMap.clear();$('detail').hidden=true;refresh(true);};
$('previous').onclick=()=>{offset=Math.max(0,offset-20);refresh(true);};
$('next').onclick=()=>{offset+=20;refresh(true);};
$('historyPrevious').onclick=()=>{historyOffset=Math.max(0,historyOffset-10);loadHistory().catch(e=>{$('connection').textContent=e.message;});};
$('historyNext').onclick=()=>{historyOffset+=10;loadHistory().catch(e=>{$('connection').textContent=e.message;});};
$('close').onclick=()=>{selectedMessage=null;++inspectSerial;++historySerial;window.WarnBridgeMap.clear();$('detail').hidden=true;};
function changeMode(next) {
  mode=next;offset=0;selectedMessage=null;++inspectSerial;++historySerial;window.WarnBridgeMap.clear();$('detail').hidden=true;
  $('alertsTab').setAttribute('aria-selected',String(mode==='alerts'));
  $('diagnosticsTab').setAttribute('aria-selected',String(mode==='diagnostics'));
  $('diagnosticArchive').hidden=mode!=='diagnostics';$('typeFilter').hidden=mode!=='diagnostics';
  $('cancellationHistory').hidden=mode!=='alerts';
  $('alertCards').hidden=mode!=='alerts';$('statusFilter').hidden=mode!=='alerts';$('alertNotice').hidden=mode!=='alerts';
  $('viewTitle').textContent=mode==='alerts' ? 'Alert inbox' : 'Diagnostic archive';refresh(true);
}
$('alertsTab').onclick=()=>changeMode('alerts');$('diagnosticsTab').onclick=()=>changeMode('diagnostics');
refresh();setInterval(()=>refresh(),5000);setInterval(()=>renderHeartbeat(),1000);
