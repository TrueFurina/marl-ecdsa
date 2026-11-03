/* V26: Visual governance state from account-scoped real APIs only; no fabricated records. */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const stageNames={training:'协作训练',contribution:'贡献评价',governance:'纪元治理',attestation:'加权共识',verification:'证据核验'};
const stageDescriptions={
 training:'训练任务在当前账号下完成，训练模式、随机种子、训练结果文件共同定位业务来源。',
 contribution:'同一任务的逐回合贡献文件和训练结果哈希构成候选权重的来源；哈希对应关系不证明贡献公平性。',
 governance:'从贡献计算候选票权；激活后绑定纪元版本。更新需要停节点且账本状态满足一致条件。',
 attestation:'当前纪元的签名贡献事件提交至三个独立节点；节点按纪元票权参与加权投票并写入区块。',
 verification:'通过区块高度分别核查签名证书、跨节点账本和本地训练来源，任何一项不匹配都不能标记整体通过。'
};
let lifecycle=null,selectedStage='training',portfolio=null,recentProposal=null,recentJob=null;
const fmt=v=>v===null||v===undefined||v===''?'—':String(v);
const brief=v=>typeof v==='string'&&v.length>33?v.slice(0,15)+'…'+v.slice(-10):fmt(v);
const safeText=(id,t)=>{if($(id))$(id).textContent=fmt(t)};
const node=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=String(text);return e};
const clear=id=>{if($(id))$(id).replaceChildren()};
async function get(url){const r=await fetch(url,{credentials:'same-origin',cache:'no-store'});let d;try{d=await r.json()}catch{throw Error('服务器返回的数据不是有效 JSON')}if(!r.ok)throw Error(d.error||'HTTP '+r.status);return d}
async function post(url,body){const r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':window.APP_CSRF||''},body:JSON.stringify(body)});let d;try{d=await r.json()}catch{throw Error('服务器返回的数据不是有效 JSON')}if(!r.ok)throw Error(d.error||'HTTP '+r.status);return d}
function kv(container,records){container.replaceChildren();for(const [key,val] of records){container.append(node('dt','',key),node('dd','',brief(val)))}}
function verifyFlag(value){return value===true?'通过':value===false?'未通过':'未检查'}
function stageData(d,key){
 const t=d.training||{},e=d.epoch||{},c=d.chain||{},v=c.latest_verification||{};
 if(key==='training')return [['任务 ID',d.job_id],['训练算法',t.algorithm],['完成回合',t.episodes],['结果 SHA-256',t.result_sha256],['训练模式',t.mode],['随机种子',t.seed]];
 if(key==='contribution')return [['对应任务 ID',d.job_id],['贡献文件 SHA-256',t.contribution_sha256],['结果文件 SHA-256',t.result_sha256],['来源匹配',e.verified_against_source?'匹配':'尚无纪元或来源不符']];
 if(key==='governance')return [['当前纪元',e.current_epoch],['本任务生效',e.active_for_job?'是':'否'],['历史纪元', (e.historical_versions||[]).join(', ')||'无'],['权重快照摘要',e.current_snapshot],['来源一致性',e.verified_against_source?'通过':'未通过']];
 if(key==='attestation')return [['任务存证数',(c.records||[]).length],['最近区块高度',c.records?.[0]?.height],['最近交易 ID',c.records?.[0]?.txid],['签名证书',verifyFlag(v.certificate_valid)],['在线节点数',(d.network?.nodes||[]).filter(n=>n.online).length]];
 return [['最近区块高度',c.records?.[0]?.height],['签名证书',verifyFlag(v.certificate_valid)],['跨节点一致性',verifyFlag(v.cross_node_consistent)],['来源记录',verifyFlag(v.training_artifacts_match)],['纪元字段',verifyFlag(v.evidence_fields_match_epoch)],['整体核验',verifyFlag(v.verified)]];
}
function stageInspect(){const d=lifecycle,st=selectedStage;
 safeText('v26-stage-title',stageNames[st]);safeText('v26-stage-description',stageDescriptions[st]);
 const rows=d?stageData(d,st):[['状态','未选择训练任务'],['操作','前往训练页面创建已完成 BC-MARL 任务']];
 kv($('v26-stage-kv'),rows);
 const action=$('v26-stage-action');action.textContent=st==='training'?'查看协作训练':st==='contribution'?'打开贡献治理':st==='verification'?'查看历史审计':st==='governance'?'跳转纪元治理':'跳转存证操作';
 action.onclick=()=>{if(st==='training')window.switchTab?.('train');else if(st==='contribution')window.switchTab?.('incentive');else if(st==='verification')window.switchTab?.('audit');else document.getElementById(st==='governance'?'v25-governance-step':'v25-evidence-step')?.scrollIntoView({behavior:'smooth',block:'start'})};
 document.querySelectorAll('[data-v26-stage]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v26Stage===st)));
}
function renderProtocol(result){
 if(!result&&recentProposal&&lifecycle?.job_id===recentJob)result=recentProposal;
 const labels=document.querySelectorAll('#v26-protocol-steps span');if(!labels.length)return;
 const events=result?.events||[], certified=result?.status==='already_attested'||(lifecycle?.chain?.records||[]).length>0;
 const pre=events.some(e=>e.phase==='PRE-PREPARE'),prepare=events.some(e=>e.phase==='PREPARE'),commit=events.some(e=>e.phase==='COMMIT');
 const flags=result?[(Boolean(result.txid)||certified),pre,prepare,commit,Boolean(result.certificate)||certified]:[certified,certified,certified,certified,certified];
 labels.forEach((n,i)=>{n.classList.toggle('is-complete',flags[i]);n.classList.toggle('is-warning',Boolean(result)&&i===3&&result.status!=='replicated'&&result.status!=='already_attested')});
 if(result){safeText('v26-protocol-status',result.status==='replicated'?'三节点已返回写入回执':result.status==='already_attested'?'当前纪元已有签名存证':result.status==='partially_replicated'?'仅部分节点写入':result.status==='commit_unconfirmed'?'提交确认不足':fmt(result.status));
 safeText('v26-protocol-metrics','有效投票：'+fmt(result.votes?.length)+' · 通过票权 '+fmt(result.weight_approved)+'/'+fmt(result.weight_total)+' · 写入节点 '+fmt(result.commits?.length)+'；此状态来自本次提交响应。');
 }else{safeText('v26-protocol-status',certified?'发现本地签名存证 · 请核验在线副本':'尚未执行本任务的贡献存证');safeText('v26-protocol-metrics',certified?'本地链上存在有效签名证书；历史阶段事件不在此处伪造，跨节点结果以在线核验为准。':'尚未取得交易证书；提交后将展示真实投票、通过权重和复制状态。')}
}
function drawFlow(d,loading){lifecycle=d||null;const st=d?.stages||[],e=d?.epoch||{},c=d?.chain||{},v=c.latest_verification||{},LD='读取中…';
 const info=d?{training:fmt(d.training.episodes)+' 回合',contribution:'来源文件已绑定',governance:e.active_for_job?'纪元 '+e.current_epoch:(e.historical_versions?.length?'历史纪元 '+e.historical_versions.at(-1):'未激活'),attestation:c.records?.length?'区块 #'+c.records[0].height:'尚未存证',verification:v.verified===true?'全部通过':c.records?.length?'需逐项核验':'无链上证据'}:{training:loading?LD:'未运行',contribution:loading?LD:'待训练',governance:loading?LD:'未激活',attestation:loading?LD:'尚未存证',verification:loading?LD:'无链上证据'};
 for(const b of document.querySelectorAll('[data-v26-stage]')){
  const k=b.dataset.v26Stage,done=st.some(x=>x.key===k&&x.done);b.classList.toggle('is-complete',Boolean(done));b.classList.toggle('is-warning',Boolean(d&&k==='verification'&&c.records?.length&&!v.verified));
  b.querySelector('[data-stage-value]').textContent=info[k];
 }
 const links=document.querySelectorAll('.v26-flow-link');links.forEach((n,i)=>n.classList.toggle('is-complete',Boolean(st[i]?.done&&st[i+1]?.done)));
 const nodes=$('v26-real-nodes');nodes.replaceChildren();
 if(!d){nodes.append(node('p','v26-subtle','未选择训练任务，节点状态暂未读取。'))}
 else{
 for(const n of d.network?.nodes||[]){const card=node('div','v26-real-node'),name=node('strong','',n.node||n.id||'节点'),stat=node('span','',(n.online?'在线':'离线')+' · '+(n.epoch_matched?'纪元匹配':'纪元未匹配')),more=node('span','',`高度 ${fmt(n.height)} · 票权 ${fmt(n.weight)}`),light=node('span','v26-node-indicator'+(n.online&&n.epoch_matched?' is-on':''));name.prepend(light);card.append(name,stat,more);nodes.append(card)}
 if(!nodes.children.length)nodes.append(node('p','v26-subtle','当前没有可查询的节点状态'))
 }
 const checks=[['签名与证书',v.certificate_valid],['跨节点副本',v.cross_node_consistent],['训练来源',v.training_artifacts_match]];
 const strip=$('v26-verification-strip');strip.replaceChildren();for(const [name,ok] of checks){const x=node('span',ok===true?'is-ok':ok===false?'is-fail':'',name+'：'+verifyFlag(ok));strip.append(x)}
 renderProtocol(null);
 safeText('v26-flow-state',!d?(loading?'正在读取训练任务与链上证据…':'尚无训练任务'):v.verified?'证据闭环已核验':c.records?.length?'已存证 · 待核验':e.active_for_job?'可执行贡献存证':'等待治理配置');stageInspect();
}
async function loadTaskFromSelect(){const jid=$('v22-job')?.value;if(!jid||jid.length!==32){drawFlow(null,false);return}drawFlow(null,true);try{drawFlow(await get('/api/distributed/collaboration/task/'+encodeURIComponent(jid)+'/lifecycle'))}catch(e){drawFlow(null,false);safeText('v26-flow-state','来源读取失败：'+e.message)}}
function portfolioRow(job,type){const row=node('div','v26-taskrow'),info=node('div');const title=node('strong','',job.job_id?.slice(0,12)+'… '+(job.eligible?'· '+fmt(job.algorithm).toUpperCase()+' / '+fmt(job.episodes)+' 回合':'· 无法绑定来源'));
 const hint=job.eligible?job.status:job.reason;info.append(title,node('small','',hint||'等待来源'));
 if(type==='overview'){const status=node('span','v26-status',job.records?.length?'已存证':job.epoch_versions?.length?'已配置权重':'待治理');info.append(status);const button=node('button','','查看治理');button.type='button';button.onclick=()=>{window.switchTab?.('chain');chooseJob(job.job_id)};row.append(info,button)}
 else{const button=node('button','',job.records?.length?'核验最近区块':'查看来源');button.type='button';button.onclick=()=>auditTask(job);row.append(info,button)}return row}
function drawPortfolio(d){portfolio=d;const s=d.summary||{},stats=$('v26-overview-stats');stats.replaceChildren();for(const [label,value] of [['有效训练任务',s.eligible??0],['已产生权重纪元',s.with_epochs??0],['已有签名存证',s.with_signed_records??0]]){let n=node('div','v26-stat');n.append(node('span','',label),node('strong','',value));stats.append(n)}
 for(const [id,mode] of [['v26-overview-tasks','overview'],['v26-audit-list','audit']]){let c=$(id);c.replaceChildren();if(!d.tasks?.length)c.append(node('p','v26-subtle','暂无已完成的训练任务。请先在协作训练页面执行 BC-MARL 任务。'));else d.tasks.forEach(j=>c.append(portfolioRow(j,mode)))}
 const select=$('v26-incentive-job');const old=select.value;select.replaceChildren();const valid=d.tasks?.filter(x=>x.eligible)||[];
 if(!valid.length){const o=node('option','','暂无有效训练任务');o.value='';select.append(o)}else{for(const j of valid){const o=node('option','',j.job_id.slice(0,12)+'… · '+j.episodes+' 回合');o.value=j.job_id;select.append(o)}select.value=valid.some(j=>j.job_id===old)?old:valid[0].job_id}
}
async function loadPortfolio(){for(const x of ['v26-audit-list','v26-overview-tasks'])safeText(x,'正在读取训练任务及本地签名证据…');try{drawPortfolio(await get('/api/distributed/collaboration/audit'))}catch(e){for(const x of ['v26-audit-list','v26-overview-tasks'])safeText(x,'数据查询失败：'+e.message);safeText('v26-incentive-state','来源查询失败：'+e.message)}}
function chooseJob(jid){const select=$('v22-job');if(!select)return;if(![...select.options].some(o=>o.value===jid)){safeText('v22-summary','请刷新可信共识任务列表，定位 '+jid.slice(0,8));return}select.value=jid;select.dispatchEvent(new Event('change',{bubbles:true}));}
async function loadIncentive(){const jid=$('v26-incentive-job')?.value;const windowValue=Number($('v26-incentive-window')?.value);const stat=$('v26-incentive-state');const root=$('v26-incentive-weights');root.replaceChildren();clear('v26-incentive-origin');
 if(!jid){stat.textContent='没有可用的 BC-MARL 训练任务；请先完成训练。';return}if(!Number.isInteger(windowValue)||windowValue<1){stat.textContent='请输入大于零的有效训练回合窗口';return}
 stat.textContent='正在按任务标识、训练结果和贡献文件校验来源…';try{const d=await post('/api/distributed/contribution/preview',{job_id:jid,window:windowValue});
 const weights=Array.isArray(d.agent_mapping)?d.agent_mapping:[];const max=Math.max(1,...weights.map(x=>Number(x.weight)||0));for(const w of weights){const card=node('div','v26-weight');const label=node('strong','',w.agent+' → '+w.node);const val=node('div','v26-value',fmt(w.weight));const m=node('div','v26-weight-meter');const bar=node('span');bar.style.width=(100*(Number(w.weight)||0)/max).toFixed(1)+'%';m.append(bar);card.append(label,val,m,node('small','','当前候选投票权重 · 非 BC 资产余额'));root.append(card)}
 const origin=$('v26-incentive-origin');for(const [k,v] of [['训练任务',jid],['贡献文件 SHA-256',d.origin_sha256],['最近窗口摘要',d.rounds_sha256],['已采纳回合数',d.episodes],['训练结果 SHA-256',d.training_binding?.training_result_sha256],['映射方法',d.source]]){const item=node('div','v26-origin-item');item.append(node('span','',k),node('strong','',brief(v)));origin.append(item)}
 stat.textContent='来源校验已完成。本次只计算候选权重，不修改当前生效纪元。';
 }catch(e){stat.textContent='来源或计算校验失败：'+e.message;root.append(node('p','v26-subtle','请核查训练任务状态、贡献文件以及训练结果哈希。'))}
}
async function auditTask(j){const results=$('v26-audit-results'),meta=$('v26-audit-meta');results.replaceChildren();meta.replaceChildren();safeText('v26-audit-description','正在检查任务 '+j.job_id+' 的历史证据…');
 if(!j.eligible && !j.records?.length){results.append(node('p','',j.reason||'当前训练任务的来源校验失败'));return}
 try{
 // Use the independent signed index for auditing: the task's source files may
 // be damaged, so calling lifecycle (which requires valid source) would fail.
 const r=j.records?.[0];if(!r){results.append(node('p','','该任务没有可核验的已提交链上贡献记录。'));safeText('v26-audit-description','任务 '+j.job_id.slice(0,12)+' · '+(j.epoch_versions?.length?'已有历史权重':'尚无纪元配置'));return}
 let trace;try{trace=await get('/api/distributed/collaboration/trace/'+r.height)}catch(e){trace={error:e.message}}
 if(trace.training_job_id&&trace.training_job_id!==j.job_id)throw Error('链上存证对应其他训练任务');
 for(const [name,value] of [['签名证书',trace.certificate_valid],['跨节点账本',trace.cross_node_consistent],['训练来源',trace.training_artifacts_match]]){const box=node('div','v26-audit-check '+(value===true?'is-ok':value===false?'is-fail':''));box.append(node('span','',name),node('strong','',verifyFlag(value)));results.append(box)}
 for(const [name,val] of [['任务 ID',j.job_id],['区块高度',r.height],['纪元',r.epoch],['交易 ID',r.txid],['权重摘要',r.snapshot_hash],['纪元字段匹配',verifyFlag(trace.evidence_fields_match_epoch)],['整体核验',verifyFlag(trace.verified)],['验证异常',trace.error||trace.source_error||(!j.eligible?j.reason:'无')]]){const item=node('div','v26-origin-item');item.append(node('span','',name),node('strong','',brief(val)));meta.append(item)}
 safeText('v26-audit-description',trace.error?'链上在线核验暂不可用：'+trace.error:trace.verified?'当前在线证据已全部匹配':'已返回分项结果；请逐项检查不通过的核验维度');
 }catch(e){results.append(node('p','',e.message));safeText('v26-audit-description','核验中断：'+e.message)}
}
for(const b of document.querySelectorAll('[data-v26-stage]'))b.addEventListener('click',()=>{selectedStage=b.dataset.v26Stage;stageInspect()});
$('v26-overview-refresh')?.addEventListener('click',loadPortfolio);
$('v26-audit-refresh')?.addEventListener('click',loadPortfolio);
$('v26-incentive-refresh')?.addEventListener('click',loadPortfolio);
$('v26-incentive-preview')?.addEventListener('click',loadIncentive);
$('v26-incentive-job')?.addEventListener('change',loadIncentive);
$('v26-incentive-window')?.addEventListener('change',loadIncentive);
$('v26-go-chain')?.addEventListener('click',()=>{window.switchTab?.('chain');chooseJob($('v26-incentive-job').value);document.getElementById('v25-governance-step')?.scrollIntoView({behavior:'smooth'})});
$('v22-job')?.addEventListener('change',()=>{recentProposal=null;recentJob=null;loadTaskFromSelect()});
window.addEventListener('marl:lifecycle-loaded',e=>drawFlow(e.detail));
window.addEventListener('marl:chain-changed',()=>{loadTaskFromSelect();loadPortfolio()});
window.addEventListener('marl:consensus-proposed',e=>{recentProposal=e.detail;recentJob=$('v22-job')?.value;renderProtocol(e.detail)});
// The existing v22 task selector is authoritative for the consensus workflow.
drawFlow(null,true);loadPortfolio();setTimeout(loadTaskFromSelect,600);
})();
