/* Task-centred MARL -> chain experience. No data fabrication or ledger writes. */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const select=$('v22-job');if(!select)return;
const state={current:null,busy:false};
async function get(url){const r=await fetch(url,{credentials:'same-origin'});let data;try{data=await r.json()}catch{throw Error('服务器未返回有效 JSON')}if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);return data}
const clear=(root)=>root.replaceChildren();
function node(tag, cls, text){let n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n}
function short(v){return typeof v==='string'&&v.length>18?v.slice(0,10)+'…'+v.slice(-6):String(v??'—')}
function numeric(v,d=2){return typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'—'}
function jump(id){const n=$(id);if(n){n.scrollIntoView({behavior:'smooth',block:'start'});n.focus?.({preventScroll:true})}}
function render(data){
  state.current=data;
  window.dispatchEvent(new CustomEvent('marl:lifecycle-loaded',{detail:data}));
  const stages=$('v22-stages');clear(stages);
  for(let i=0;i<data.stages.length;i++){
    const st=data.stages[i], card=node('div','v22-stage '+(st.done?'v22-done':'v22-pending'));
    card.append(node('span','v22-stage-number',String(i+1).padStart(2,'0')),
      node('strong','',st.label),node('small','',st.detail));stages.append(card);
  }
  const t=data.training, met=$('v22-metrics');clear(met);
  for(const [name,value] of [['训练算法',t.algorithm?.toUpperCase()],['已完成回合',t.episodes],['平均奖励',numeric(t.avg_reward)],['合作率',typeof t.avg_cooperation_rate==='number'?numeric(t.avg_cooperation_rate*100)+'%':'—'],['权重纪元',data.epoch.active_for_job?'当前生效':data.epoch.historical_versions.length?'历史纪元':'未激活']]){
    let c=node('div','v22-metric');c.append(node('span','',name),node('strong','',value));met.append(c);
  }
  const w=$('v22-weights');clear(w);
  if(data.epoch.weights.length){
    for(const x of data.epoch.weights){let line=node('div','v22-weight-row');line.append(node('span','',x.agent+' → '+x.node),node('strong','',x.weight+' 票权'));w.append(line)}
  }else{
    w.append(node('p','v22-muted','尚无当前生效的本任务权重快照。必须先选择任务、预览来源，再在停节点状态下激活。'));
  }
  const proof=$('v22-chain-result');clear(proof);
  const records=data.chain.records;
  if(records.length){
    const latest=records[0], audit=data.chain.latest_verification||{};
    proof.append(node('div','v22-proof-line','区块高度 '+latest.height+' · '+short(latest.txid)));
    const rows=[['节点投票证书',latest.local_certificate_valid?'本地证书有效':'未验证'],
      ['跨节点一致',audit.cross_node_consistent===true?'通过':'尚未通过'],
      ['纪元来源字段',audit.evidence_fields_match_epoch===true?'通过':'尚未通过'],
      ['训练数据来源',audit.training_artifacts_match===true?'通过':'尚未通过']];
    for(const [k,v] of rows){let line=node('div','v22-proof-check');line.append(node('span','',k),node('strong',v==='通过'?'v22-ok':'v22-warn',v));proof.append(line)}
  }else proof.append(node('p','v22-muted','尚未发现对应任务的已写入链上存证。完成权重激活与三节点启动后，可提交贡献存证。'));
  $('v22-next').textContent=data.next_action;
  $('v22-summary').textContent='任务 '+short(data.job_id)+' · '+(data.chain.records.length?'发现链上存证':'尚无链上存证');
  const chainInput=$('v21-trace-height');if(chainInput&&records.length)chainInput.value=records[0].height;
}
async function loadTask(){const jid=select.value;state.current=null;
  if(!jid){$('v22-summary').textContent='暂无符合条件的 BC-MARL 训练任务';return}
  $('v22-summary').textContent='正在核验训练来源、纪元与节点账本…';
  try{const d=await get('/api/distributed/collaboration/task/'+encodeURIComponent(jid)+'/lifecycle');render(d)}
  catch(e){$('v22-summary').textContent='数据关联检查失败：'+e.message;$('v22-next').textContent=e.message;clear($('v22-stages'))}
}
async function loadJobs(){
 const old=select.value;select.disabled=true;$('v22-summary').textContent='正在读取当前账户的训练任务…';
 try{const jobs=(await get('/api/distributed/collaboration/jobs')).jobs;clear(select);
   const valid=jobs.filter(x=>x.eligible);
   if(!valid.length)select.append(node('option','','尚无符合条件的已完成训练任务'));
   for(const job of valid){let option=node('option','',job.job_id.slice(0,8)+' · '+job.algorithm?.toUpperCase()+' · '+job.episodes+' 回合');option.value=job.job_id;select.append(option)}
   select.value=valid.some(j=>j.job_id===old)?old:(valid[0]?.job_id||'');
   if(select.value)await loadTask();else{$('v22-summary').textContent='请先在协作训练页面完成三智能体 BC-MARL 任务';$('v22-next').textContent='训练完成后再刷新任务来源。'}
 }catch(e){$('v22-summary').textContent=e.message}finally{select.disabled=false}
}
select.addEventListener('change',loadTask);
$('v22-refresh').addEventListener('click',loadJobs);
window.addEventListener('marl:chain-changed',loadJobs);
$('v22-to-train').addEventListener('click',()=>window.switchTab?.('train'));
$('v22-to-preview').addEventListener('click',()=>jump('v25-governance-step'));
$('v22-to-attest').addEventListener('click',()=>jump('v25-evidence-step'));
$('v22-to-trace').addEventListener('click',()=>jump('v21-trace-height'));
$('v22-to-nodes').addEventListener('click',()=>jump('v25-node-step'));
// Keep the overview synchronized after existing operations rather than inventing new client state.
for(const id of ['v10-preview','v10-activate','v20-attest','v10-recover','v21-trace-btn']){
 const btn=$(id);if(btn)btn.addEventListener('click',()=>{setTimeout(loadTask,1800)});
}
loadJobs();
})();
