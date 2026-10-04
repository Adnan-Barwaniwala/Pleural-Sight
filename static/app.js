'use strict';
const $=id=>document.getElementById(id);
const node=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined&&text!==null)el.textContent=text;if(className)el.className=className;return el;};
let state,selected,pollToken=0,activeScope='prior',currentSet='demo',flickerTimer=null;
const view={sync:true,prior:{scale:1,x:0,y:0},current:{scale:1,x:0,y:0}};
const STATES={present:'Fluid detected',absent:'No fluid detected',uncertain:'Uncertain',not_assessable:'Could not determine',indeterminate:'Could not determine'};
const CLAIMS={present:'Says fluid is present',absent:'Says no fluid is present',uncertain:'Hedged or unclear statement',no_relevant_claim:'No relevant statement'};
const LABELS={new:'Possible new fluid in the current X-ray.',resolved:'Previously visible fluid is no longer detected.',persistent:'Fluid is detected in both X-rays.',absent:'No fluid around the lungs in either X-ray.'};
const STATUS={
  disagreement:{chip:'review',icon:'!',lead:'The images and the written report disagree.'},
  cannot_compare:{chip:'error',icon:'⊘',lead:'These films cannot be compared reliably.'},
  unstable:{chip:'review',icon:'≈',lead:'The blind read was not stable.'},
  image_only:{chip:'running',icon:'◐',lead:null},
  agrees:{chip:'complete',icon:'✓',lead:null},
};
const human=v=>String(v??'').replaceAll('_',' ');
async function api(path,options={}){const response=await fetch(path,{...options,headers:{'X-TimeLens-Request':'local-ui',...options.headers}});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'The request could not be completed.');return data;}
const post=(path,body)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function statusClass(el,type){el.className='status-chip'+(type?' status-'+type:'');}
const statusText=s=>s?(state.status_text[s]||human(s)):'Not run';
const shownRun=c=>c.last_run?.status==='complete'?c.last_run:(c.replay||null);
const rank=c=>c.status?state.status_order[c.status]:9;

// ---------- Image desk (synced pan/zoom, flicker, swipe) ----------
function resetView(){for(const scope of ['prior','current'])view[scope]={scale:1,x:0,y:0};applyViews();}
function applyViews(){for(const scope of ['prior','current']){const v=view[scope],t=`translate(${v.x}px, ${v.y}px) scale(${v.scale})`;$(scope+'-image').style.transform=t;$('stack-'+scope).style.transform=`translate(${view.prior.x}px, ${view.prior.y}px) scale(${view.prior.scale})`;}$('zoom-value').textContent=Math.round(view[activeScope].scale*100)+'%';}
function setScale(delta){const targets=view.sync||$('viewer').dataset.mode!=='side'?['prior','current']:[activeScope];for(const scope of targets)view[scope].scale=Math.min(3,Math.max(1,view[scope].scale+delta));applyViews();}
function setMode(mode){
  clearInterval(flickerTimer);flickerTimer=null;$('viewer').dataset.mode=mode;
  document.querySelectorAll('.mode-button').forEach(b=>{const on=b.dataset.mode===mode;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
  const stacked=mode!=='side';
  document.querySelectorAll('#viewer>figure[data-scope], #viewer>.time-axis').forEach(el=>el.hidden=stacked);
  $('stack').hidden=!stacked;$('swipe').hidden=mode!=='swipe';
  if(mode==='flicker'){let earlier=true;const tick=()=>{$('swipe-top').style.clipPath=earlier?'none':'inset(0 0 0 100%)';$('stack-label').replaceChildren(node('b',earlier?'01':'02'),node('span',earlier?'Earlier study':'Current study'));$('stack-meta').textContent=$(earlier?'prior-meta':'current-meta').textContent;earlier=!earlier;};tick();flickerTimer=setInterval(tick,700);$('stack-hint').textContent='Flicker alternates the films every 0.7 s; change is easiest to see by flipping.';}
  if(mode==='swipe'){$('stack-label').replaceChildren(node('b','01 ◀ ▶ 02'),node('span','Earlier | Current'));$('stack-meta').textContent='Drag the slider';$('stack-hint').textContent='';updateSwipe();}
}
function updateSwipe(){$('swipe-top').style.clipPath='inset(0 '+(100-$('swipe').value)+'% 0 0)';}

// ---------- Case rail (worklist) ----------
function renderRail(){
  const items=state.cases.filter(c=>(c.set||'upload')===currentSet).sort((a,b)=>rank(a)-rank(b)||a.id.localeCompare(b.id));
  $('count').textContent=items.length;$('cases').replaceChildren();
  document.querySelectorAll('.rail-filter button').forEach(b=>{const on=b.dataset.set===currentSet;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
  if(!items.length)$('cases').append(node('p',currentSet==='upload'?'No uploads yet.':'No cases.','report-empty'));
  for(const c of items){
    const button=node('button',undefined,'case-button');button.dataset.id=c.id;button.setAttribute('aria-current',String(c.id===selected));
    const running=['queued','running'].includes(c.last_run?.status);
    const run=shownRun(c);
    const chip=node('span',running?'Analyzing':statusText(c.status)+(run?.replay?' · replay':''),'case-state'+(c.status?' tone-'+c.status:''));
    button.append(node('strong',c.name),node('small',(c.prior.view||'?')+' → '+(c.current.view||'?')+(c.reports.length?' · report':'')+(c.signoff?' · '+human(c.signoff.action):'')),chip);
    button.onclick=()=>{location.hash=encodeURIComponent(c.id);};
    $('cases').append(button);
  }
}

// ---------- Selection ----------
function select(id){
  const c=state.cases.find(item=>item.id===id);if(!c)return;
  const changed=selected!==c.id;selected=c.id;pollToken++;
  if(changed){resetView();for(const scope of ['prior','current']){const url='/api/cases/'+encodeURIComponent(c.id)+'/images/'+scope;$(scope+'-image').src=url;$('stack-'+scope).src=url;$(scope+'-open').href=url;$(scope+'-name').textContent=c[scope].image;const f=c[scope];$(scope+'-meta').textContent=[f.view||'view unknown',f.order!=null?'follow-up '+f.order:null,f.derived?'derived control':null].filter(Boolean).join(' · ');}setMode($('viewer').dataset.mode);}
  document.querySelectorAll('.case-button').forEach(b=>b.setAttribute('aria-current',String(b.dataset.id===c.id)));
  $('viewer').closest('.viewer-shell').classList.remove('analyzing');
  $('case-name').textContent=c.name;
  $('case-context').textContent=[c.source,c.patient_id?'patient '+c.patient_id:null,c.purpose].filter(Boolean).join(' · ');
  $('assertions').textContent=c.purpose||'';
  renderReference(c);renderReports(c);renderSignoff(c);
  $('hashes').replaceChildren();for(const scope of ['prior','current']){const hash=c[scope].sha256||state.provenance.find(p=>p.image===c[scope].image)?.sha256;if(hash)$('hashes').append(node('p',(scope==='prior'?'EARLIER':'CURRENT')+' SHA-256 · '+hash,'hash'));}
  const busy=['queued','running'].includes(c.last_run?.status);
  $('analyze').disabled=busy||!state.integration.ready;$('analyze-headless').disabled=busy||!state.integration.gemini;
  const run=shownRun(c);
  if(busy){pollRun(c.last_run.id,c.id);return;}
  if(run?.result)showResult(run,c);else showEmpty(c);
  $('announcement').textContent=c.name+' selected. '+(run?'Status: '+statusText(c.status)+'.':'Not yet investigated.');
}
function showEmpty(c){
  $('assessment-status').textContent='Not run';statusClass($('assessment-status'));
  const wrap=node('div',undefined,'empty-state');wrap.append(node('span','','empty-orbit'));const copy=node('div');
  copy.append(node('h3','Ready for an independent look.'),node('p',c.gate.comparable?'Run it live to watch the OpenSwarm agents work, or run the same tools headless.':'The comparability gate will stop this case before any model call: '+c.gate.reasons[0]));
  wrap.append(copy);const content=$('assessment-content');content.replaceChildren(wrap);
  if(['failed','interrupted'].includes(c.last_run?.status))content.append(node('p','Last attempt '+c.last_run.status+': '+(c.last_run.error||'unknown error'),'error'));
}
function renderReference(c){
  const box=$('reference');box.replaceChildren();if(!c.reference)return;
  box.append(node('p','NIH reference label (noisy, report-mined): '+human(c.reference.nih_label)+(c.reference.expected_status?' · expected status: '+human(c.reference.expected_status):'')+'. Earlier findings: '+(c.prior.findings||'—')+'. Current findings: '+(c.current.findings||'—')+'.'));
}

// ---------- Reports ----------
function highlighted(text,quote){const q=node('blockquote');const i=quote?text.indexOf(quote):-1;if(i<0){q.textContent=text;return q;}q.append(text.slice(0,i),node('mark',quote),text.slice(i+quote.length));return q;}
function renderReports(c){
  const content=$('report-content');content.replaceChildren();$('report-count').textContent=c.reports.length?c.reports.length+' attached':'None attached';
  if(!c.reports.length){content.append(node('p','No report is attached. The images are compared independently and the result is image only.','report-empty'));return;}
  const claims=shownRun(c)?.result?.verdict?.claims||[];
  c.reports.forEach((report,i)=>{const card=node('article',undefined,'report-card');const head=node('h3',report.scope==='prior'?'Earlier study report':'Current study report');if(report.synthetic)head.append(node('span','Synthetic','status-chip status-review inline-chip'));const claim=claims.find(x=>x.report_index===i);card.append(head,highlighted(report.text,claim?.quote),node('p',claim?'Report Reader: '+(CLAIMS[claim.state]||human(claim.state))+' · '+human(claim.verdict):report.synthetic?'Written by the team for this demo · not yet analyzed':'Stored locally · not yet analyzed'));content.append(card);});
}

// ---------- Result ----------
function sourceRow(label,value){const row=node('div',undefined,'source-row');row.append(node('span',label),node('b',value));return row;}
function evidenceDetails(summary,items){const details=node('details');details.append(node('summary',summary));const evidence=node('div',undefined,'evidence-copy');for(const [label,obs] of items){evidence.append(node('p',label+': '+(obs.evidence||'No explanation returned.')+(obs.side&&!['none','unclear'].includes(obs.side)?' (side: '+obs.side+')':'')));if(obs.limitations?.length)evidence.append(node('p','Limitations: '+obs.limitations.join(' · ')));}details.append(evidence);return details;}
function readingCard(title,reading,tone){const card=node('article',undefined,'source-card');card.dataset.tone=tone;const head=node('div',undefined,'source-card-header');head.append(node('strong',title),node('span',human(reading.label),tone==='warning'?'tone-warning':'tone-ok'));const rows=node('div',undefined,'source-rows');rows.append(sourceRow('Earlier image',STATES[reading.prior.state]),sourceRow('Current image',STATES[reading.current.state]));card.append(head,rows,evidenceDetails('Why did the blind reader say this?',[['Earlier',reading.prior],['Current',reading.current]]));return card;}
function claimCard(claim,stateText){const contradiction=claim.verdict==='contradiction',agreement=claim.verdict==='agreement';const card=node('article',undefined,'source-card');card.dataset.tone=contradiction?'warning':agreement?'ok':'neutral';const head=node('div',undefined,'source-card-header');head.append(node('strong',(claim.scope==='prior'?'Earlier':'Current')+' study vs report'),node('span',contradiction?'Sources disagree':agreement?'Sources agree':'Review report',contradiction?'tone-warning':agreement?'tone-ok':''));const rows=node('div',undefined,'source-rows');rows.append(sourceRow('Blind read',stateText),sourceRow('Written report',CLAIMS[claim.state]||human(claim.state)));if(claim.quote)rows.append(sourceRow('Quotation','“'+claim.quote+'”'));card.append(head,rows);return card;}
function heroTitle(v){if(v.status==='cannot_compare'||v.status==='unstable'||v.status==='disagreement')return STATUS[v.status].lead;return LABELS[v.reading_label]||'Result ready for review.';}
function showResult(run,c){
  const result=run.result,v=result.verdict,meta=STATUS[v.status]||STATUS.image_only,content=$('assessment-content');content.replaceChildren();
  const hero=node('div',undefined,'result-hero');hero.append(node('div',meta.icon,'result-icon'+(['agrees','image_only'].includes(v.status)?' ok':'')));
  const heroCopy=node('div');const tags=node('div',undefined,'run-tags');
  tags.append(node('span',statusText(v.status),'status-chip status-'+meta.chip));
  tags.append(node('span',run.replay?'Replay · cached '+new Date(run.created*1000).toLocaleString():(result.orchestrator==='openswarm'?'Live · OpenSwarm':'Live · headless runner')+' · '+new Date(run.updated*1000).toLocaleTimeString(),'status-chip'));
  heroCopy.append(tags,node('h3',heroTitle(v)),node('p',v.summary));hero.append(heroCopy);content.append(hero);
  const reading=result.reading?.data;
  if(reading){
    const a=reading.reading_a,track=node('div',undefined,'change-track');
    for(const scope of ['prior','current']){if(scope==='current')track.append(node('div','','track-line'));const s=node('div',undefined,'study-state');s.append(node('span',(scope==='prior'?'Earlier':'Current')+' image · blind read'),node('strong',reading.consistent?STATES[a[scope].state]:STATES[a[scope].state]+' / '+STATES[reading.reading_b[scope].state]));track.append(s);}
    content.append(track);
    content.append(node('p','Order-swap check: the films were read twice with their slots swapped and chronology withheld.','section-note'));
    const grid=node('div',undefined,'source-grid');const tone=reading.consistent?'ok':'warning';
    grid.append(readingCard('Reading A · earlier film in slot 1',a,tone),readingCard('Reading B · slots swapped',reading.reading_b,tone));content.append(grid);
  }
  const claims=v.claims||[];
  if(claims.length&&reading){content.append(node('p','Report check: the Report Reader saw only the text; quotations are verified verbatim in code.','section-note'));const grid=node('div',undefined,'source-grid');for(const claim of claims)grid.append(claimCard(claim,STATES[reading.reading_a[claim.scope].state]));content.append(grid);}
  const re=result.reassessment?.data;
  if(re){const card=node('article',undefined,'source-card investigator');card.dataset.tone=v.status==='disagreement'?'warning':'ok';const head=node('div',undefined,'source-card-header');head.append(node('strong','Investigator · one targeted reassessment'),node('span',human(re.label),v.status==='disagreement'?'tone-warning':'tone-ok'));const rows=node('div',undefined,'source-rows');rows.append(sourceRow('Question',re.question),sourceRow('Earlier image',STATES[re.prior.state]),sourceRow('Current image',STATES[re.current.state]));card.append(head,rows,evidenceDetails('Reassessment evidence',[['Earlier',re.prior],['Current',re.current]]));content.append(card);}
  const limits=node('details',undefined,'trace-details');limits.append(node('summary','Comparability and limitations'));const list=node('ul',undefined,'limit-list');
  list.append(node('li','Views: earlier '+c.gate.views.prior+', current '+c.gate.views.current+' — gate '+(c.gate.comparable?'passed':'stopped the run')));
  for(const r of c.gate.reasons)list.append(node('li',r));
  if(reading)for(const issue of new Set([...reading.reading_a.comparability_issues,...reading.reading_b.comparability_issues]))list.append(node('li','Reader noted: '+issue));
  for(const l of v.limitations)list.append(node('li',l));
  limits.append(list);if(v.status!=='agrees'&&v.status!=='image_only')limits.open=true;content.append(limits);
  if(result.agents?.length){const details=node('details',undefined,'trace-details');details.append(node('summary','View '+(result.orchestrator==='openswarm'?'OpenSwarm':'headless')+' execution trace'));const table=node('table',undefined,'trace-table');const head=node('tr');for(const h of ['Agent','Tool','Status','Time','Model calls'])head.append(node('th',h));table.append(head);
    for(const agent of result.agents){const tr=node('tr'),t=agent.tool_trace||{};const name=node('td',agent.label);if(agent.session_id)name.append(node('small','session '+agent.session_id.slice(0,8)+(agent.returned_model?' · '+agent.returned_model:'')));tr.append(name,node('td',agent.tool),node('td',human(agent.status)+(agent.rejected_tool_calls?' · '+agent.rejected_tool_calls+' rejected':'')),node('td',agent.seconds?agent.seconds.toFixed(1)+' s':'—'),node('td',t.model_requests?t.model_requests+' × '+(t.used_model||t.requested_model||'Gemini')+(t.input_tokens?' · '+(t.input_tokens+(t.output_tokens||0)).toLocaleString()+' tokens':''):'—'));table.append(tr);}
    details.append(table,node('p','Each OpenSwarm agent had a fresh connector exposing only its own tool; connectors and modes were deleted afterwards. Agent agreement is not a confidence score.','section-note'));content.append(details);}
  $('assessment-status').textContent='Human review';statusClass($('assessment-status'),meta.chip);
}

// ---------- Live progress (persisted backend states only) ----------
const STAGES=[['gate','Comparability gate'],['launch','Launching isolated OpenSwarm agents'],['image','Blind Reader reading both films twice'],['report','Report Reader extracting report statements'],['investigate','Investigator reassessing a dispute'],['status','Computing status for review']];
function phaseState(key,run,hasReports){
  const order={queued:0,launching_agents:1,readers_running:2,investigating:4,finalizing:5,human_review:6,gate_stopped:6};const current=order[run.stage]??0,p=run.progress||{};
  if(run.stage==='gate_stopped')return key==='gate'?'complete':'skipped';
  if(key==='gate')return current>0?'complete':'active';
  if(key==='launch')return current>1?'complete':current===1?'active':'waiting';
  if(key==='image'){const s=p.read_pair;return s==='complete'?'complete':s==='running'?'active':current>2?'complete':current===2?'active':'waiting';}
  if(key==='report'){if(!hasReports)return 'skipped';const s=p.read_reports;return s==='complete'?'complete':s==='running'?'active':current>2?'complete':current===2?'active':'waiting';}
  if(key==='investigate'){const s=p.reassess;if(s==='complete')return 'complete';if(s==='running'||current===4)return 'active';return current>=5?'skipped':'waiting';}
  return current>=5?'active':'waiting';
}
function elapsed(created){const s=Math.max(0,Math.floor(Date.now()/1000-created));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');}
function renderProgress(run){
  const c=state.cases.find(item=>item.id===selected),hasReports=Boolean(c?.reports.length),content=$('assessment-content');content.replaceChildren();
  $('viewer').closest('.viewer-shell').classList.add('analyzing');
  const live=node('div',undefined,'analysis-live'),head=node('div',undefined,'analysis-head'),copy=node('div');
  copy.append(node('h3','Investigating this comparison…'),node('p',(run.engine==='headless'?'Headless runner: the same tools, no agents.':'Watch the agent cards appear in OpenSwarm.')+' Images and report text stay inside their own MCP tools.'));
  head.append(copy,node('span',elapsed(run.created),'elapsed'));live.append(head);
  const states=STAGES.map(([key])=>phaseState(key,run,hasReports)),done=states.filter(s=>s==='complete'||s==='skipped').length;
  const progress=node('div',undefined,'progress-line'),fill=node('span');fill.style.width=Math.max(8,done/STAGES.length*100)+'%';progress.append(fill);live.append(progress);
  const list=node('div',undefined,'stage-list');STAGES.forEach(([key,label],i)=>{const s=states[i],row=node('div',undefined,'stage '+(s==='active'?'active':s==='complete'?'complete':''));row.append(node('span',s==='complete'?'✓':s==='skipped'?'—':String(i+1),'marker'),node('span',label),node('span',s==='active'?'Working':s==='complete'?'Done':s==='skipped'?'Skipped':'Waiting','stage-state'));list.append(row);});live.append(list);
  const agents=node('div',undefined,'agent-live-grid three');
  for(const [label,key,text] of [['Blind Reader','read_pair','Receives the two films, never the reports.'],['Report Reader','read_reports',hasReports?'Receives report text, never the images.':'Skipped because no report was attached.'],['Investigator','reassess','Runs only if the blind read contradicts the report.']]){const s=key==='read_reports'&&!hasReports?'complete':(run.progress?.[key]||'waiting');const card=node('div',undefined,'agent-live '+s);const title=node('h4');title.append(node('span','','agent-pulse'),document.createTextNode(label));card.append(title,node('p',text));agents.append(card);}
  live.append(agents);content.append(live);$('assessment-status').textContent='Analyzing';statusClass($('assessment-status'),'running');
}
async function pollRun(runId,caseId){
  const token=++pollToken;$('analyze').disabled=true;$('analyze-headless').disabled=true;
  while(token===pollToken&&selected===caseId){
    let run;try{run=await api('/api/runs/'+encodeURIComponent(runId));}catch(error){showEmpty(state.cases.find(c=>c.id===caseId));break;}
    const c=state.cases.find(x=>x.id===caseId);if(c)c.last_run=run;
    if(!['queued','running'].includes(run.status)){await refresh(caseId);return;}
    renderProgress(run);await new Promise(resolve=>setTimeout(resolve,1000));
  }
}
async function startRun(engine){
  if(!selected)return;const caseId=selected;$('analyze').disabled=true;$('analyze-headless').disabled=true;
  renderProgress({stage:'queued',created:Date.now()/1000,progress:{},engine});
  try{const run=await post('/api/runs',{case_id:caseId,engine});const c=state.cases.find(x=>x.id===caseId);c.last_run=run;renderRail();await pollRun(run.id,caseId);}
  catch(error){$('assessment-content').replaceChildren(node('p',error.message,'error'));$('viewer').closest('.viewer-shell').classList.remove('analyzing');$('analyze').disabled=!state.integration.ready;$('analyze-headless').disabled=!state.integration.gemini;}
}

// ---------- Sign-off ----------
function renderSignoff(c){
  const canSign=Boolean(c.status)&&!['queued','running'].includes(c.last_run?.status);
  for(const id of ['approve','override','escalate'])$(id).disabled=!canSign;
  $('signoff-state').textContent=c.signoff?'Last decision: '+human(c.signoff.action)+' of “'+statusText(c.signoff.status)+'” ('+c.signoff.source+') · '+new Date(c.signoff.created*1000).toLocaleString()+(c.signoff.reason?' — '+c.signoff.reason:''):canSign?'Approve, override with a reason, or escalate. Each decision is written to the sign-off log.':'No result to sign off yet.';
}
async function sign(action,reason){await post('/api/signoffs',{case_id:selected,action,reason});await refresh(selected);$('announcement').textContent='Sign-off recorded: '+action+'.';}

// ---------- Evaluation page ----------
async function renderEval(){
  const page=$('page-eval');page.replaceChildren();
  const intro=node('section',undefined,'workspace-intro'),d=node('div');d.append(node('p','EVALUATION · A PILOT, NOT PROOF','kicker'));const h=node('h1','Does the swarm ');h.append(node('em','add anything?'));d.append(h,node('p','The same NIH pilot pairs under three conditions. Built so it can disprove TimeLens: if one strong prompt (B) matches TimeLens (C), we say so.','subtitle'));intro.append(d);page.append(intro);
  let data;try{data=await api('/api/evaluation');}catch(e){page.append(node('p',e.message,'error'));return;}
  const panel=node('section',undefined,'assessment-panel');page.append(panel);
  if(!data.available){panel.append(node('h2','Not run yet'),node('p','Run .venv\\Scripts\\python scripts\\run_eval.py and reload this page.','report-empty'));return;}
  panel.append(node('p','Run '+new Date(data.created*1000).toLocaleString()+' · '+data.model+' · '+data.n_pairs+' PA→PA pairs, '+data.n_ap_pa+' AP-vs-PA pairs, '+data.n_controls+' near-duplicate control.','section-note'));
  const table=node('table',undefined,'trace-table eval');const hr=node('tr');for(const x of ['Condition','Accuracy on answered','Coverage','Correct abstention (AP vs PA)','False “new” on control','Order-swap consistent','Failed calls'])hr.append(node('th',x));table.append(hr);
  for(const r of data.conditions){const tr=node('tr');tr.append(node('td',r.id+' · '+r.name),node('td',r.accuracy),node('td',r.coverage),node('td',r.abstention),node('td',r.false_new),node('td',r.swap_consistency??'—'),node('td',String(r.errors)));table.append(tr);}
  panel.append(node('h2','Conditions'),table);
  if(data.anchoring){const a=data.anchoring,t=node('table',undefined,'trace-table eval');const r0=node('tr');for(const x of ['Setup','Pairs with a wrong report','Image label followed the wrong report','Wrong report flagged'])r0.append(node('th',x));t.append(r0);for(const r of a.rows){const tr=node('tr');tr.append(node('td',r.name),node('td',String(r.n)),node('td',r.anchored),node('td',r.flagged));t.append(tr);}panel.append(node('h2','Anchoring test'),node('p',a.description,'section-note'),t);}
  const per=node('table',undefined,'trace-table eval');const ph=node('tr');for(const x of ['Pair','NIH label','A naive','B strong','C TimeLens'])ph.append(node('th',x));per.append(ph);for(const r of data.pairs){const tr=node('tr');tr.append(node('td',r.id),node('td',human(r.truth)),node('td',human(r.A)),node('td',human(r.B)),node('td',human(r.C)));per.append(tr);}
  const det=node('details',undefined,'trace-details');det.append(node('summary','Per-pair results'),per);panel.append(det,node('p',data.honesty,'section-note'));
}

// ---------- Pages, refresh ----------
function route(){
  const hash=location.hash.slice(1),page=hash==='/eval'?'eval':hash==='/about'?'about':'workspace';
  for(const p of ['workspace','eval','about'])$('page-'+p).hidden=p!==page;
  document.querySelectorAll('.page-nav a').forEach(a=>a.setAttribute('aria-current',String(a.dataset.page===page)));
  if(page!=='workspace'){clearInterval(flickerTimer);flickerTimer=null;}
  if(page==='eval')renderEval();
  if(page==='workspace'&&state){const id=decodeURIComponent(hash);const c=state.cases.find(x=>x.id===id);if(c&&(c.set||'upload')!==currentSet){currentSet=c.set||'upload';renderRail();}select(c?id:(selected||state.cases.find(x=>x.set===currentSet)?.id||state.cases[0].id));}
}
async function refresh(id){
  state=await api('/api/state');const i=state.integration;
  $('integration').textContent=i.message;$('integration-badge').textContent=i.ready?'Live':i.gemini?'Headless only':'Replay only';statusClass($('integration-badge'),i.ready?'ready':'review');
  $('system-text').textContent='OpenSwarm '+(i.openswarm?'connected':'offline')+' · Gemini '+(i.gemini?'key set':'no key');
  renderRail();
  if(id){selected=null;select(id);}
}
document.querySelectorAll('.rail-filter button').forEach(b=>b.onclick=()=>{currentSet=b.dataset.set;renderRail();const first=state.cases.filter(c=>(c.set||'upload')===currentSet).sort((a,b)=>rank(a)-rank(b)||a.id.localeCompare(b.id))[0];if(first)location.hash=encodeURIComponent(first.id);});
document.querySelectorAll('.mode-button').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
$('swipe').oninput=updateSwipe;
$('analyze').onclick=()=>startRun('openswarm');$('analyze-headless').onclick=()=>startRun('headless');
for(const scope of ['prior','current']){const film=$(scope+'-film');film.addEventListener('pointerenter',()=>{activeScope=scope;applyViews();});let drag=null;film.addEventListener('pointerdown',event=>{activeScope=scope;if(view[scope].scale===1)return;drag={x:event.clientX,y:event.clientY,starts:{}};for(const target of view.sync?['prior','current']:[scope])drag.starts[target]={x:view[target].x,y:view[target].y};film.setPointerCapture(event.pointerId);});film.addEventListener('pointermove',event=>{if(!drag)return;for(const target of Object.keys(drag.starts)){view[target].x=drag.starts[target].x+event.clientX-drag.x;view[target].y=drag.starts[target].y+event.clientY-drag.y;}applyViews();});film.addEventListener('pointerup',()=>drag=null);film.addEventListener('pointercancel',()=>drag=null);}
$('zoom-in').onclick=()=>setScale(.25);$('zoom-out').onclick=()=>setScale(-.25);$('reset-view').onclick=resetView;
$('sync-view').onclick=()=>{view.sync=!view.sync;$('sync-view').classList.toggle('active',view.sync);$('sync-view').setAttribute('aria-pressed',String(view.sync));};
$('fullscreen-view').onclick=()=>{const shell=$('viewer').closest('.viewer-shell');if(document.fullscreenElement)document.exitFullscreen();else shell.requestFullscreen?.();};
$('approve').onclick=()=>sign('approve').catch(e=>alert(e.message));$('escalate').onclick=()=>sign('escalate').catch(e=>alert(e.message));
$('override').onclick=()=>{$('override-error').textContent='';$('override-dialog').showModal();};
for(const id of ['close-override','cancel-override'])$(id).onclick=()=>$('override-dialog').close();
$('override-form').onsubmit=async event=>{event.preventDefault();try{await sign('override',new FormData(event.target).get('reason'));$('override-dialog').close();event.target.reset();}catch(error){$('override-error').textContent=error.message;}};
window.addEventListener('hashchange',route);
$('new-case').onclick=()=>{$('form-error').textContent='';$('upload-dialog').showModal();};for(const id of ['close-dialog','cancel-upload'])$(id).onclick=()=>$('upload-dialog').close();
$('upload-form').onsubmit=async event=>{event.preventDefault();$('form-error').textContent='';$('save-upload').disabled=true;$('save-upload').textContent='Saving…';try{const saved=await api('/api/cases',{method:'POST',body:new FormData(event.target)});currentSet='upload';await refresh();$('upload-dialog').close();event.target.reset();location.hash=encodeURIComponent(saved.id);}catch(error){$('form-error').textContent=error.message;$('form-error').focus();}finally{$('save-upload').disabled=false;$('save-upload').textContent='Save comparison';}};
refresh().then(route).catch(error=>{$('integration').textContent='Workspace unavailable: '+error.message;$('case-name').textContent='Could not load comparisons';});
