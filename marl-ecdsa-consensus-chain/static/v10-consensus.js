(()=>{'use strict';
const el=id=>document.getElementById(id);if(!el('v10-preview'))return;
let pending=null;
async function req(path,body){const r=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':window.APP_CSRF||''},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}
const show=(id,v)=>{el(id).textContent=typeof v==='string'?v:JSON.stringify(v,null,2)};
const status=msg=>el('v10-state').textContent=msg;
async function run(fn){try{await fn()}catch(e){status(e.message)}}
// V25: no second job selector; governance always operates on current workbench task.
const sharedJob=el('v22-job');
if(sharedJob) sharedJob.addEventListener('change',()=>{
 pending=null;el('v10-activate').disabled=true;
 status('训练任务已切换，请重新读取对应贡献');
});
el('v10-preview').onclick=()=>run(async()=>{
  const jid=el('v22-job')?.value;if(!jid)throw Error('当前没有可核验的训练任务');
  pending=await req('/api/distributed/contribution/preview',{job_id:jid,window:Number(el('v10-window').value)});
  show('v10-detail',{training_job_id:pending.training_binding.job_id,training_summary:pending.training_summary,
  contribution_sha256:pending.origin_sha256,rounds_sha256:pending.rounds_sha256,agent_node_weights:pending.agent_mapping,
  method:pending.source,episodes:pending.episodes,bc_incentive_scores:pending.incentive_scores});
  el('v10-activate').disabled=false;status('已校验训练任务与贡献文件；停止全部节点、核对账本一致后方可激活新纪元');
});
el('v10-snapshot').onclick=()=>run(async()=>show('v10-detail',await req('/api/distributed/snapshot')));
el('v10-activate').onclick=()=>run(async()=>{
  if(!pending)throw Error('请先预览贡献权重');
  if(!confirm('权重切换要求三个节点已停止、账本一致且没有未完成投票。确认激活新的纪元？'))return;
  const r=await req('/api/distributed/contribution/activate',{
    job_id:pending.training_binding.job_id,origin_sha256:pending.origin_sha256,
    training_result_sha256:pending.training_binding.training_result_sha256,rounds_sha256:pending.rounds_sha256,
    window:Number(el('v10-window').value)});
  pending=null;el('v10-activate').disabled=true;show('v10-detail',r);
  status('新权重纪元已激活。请重新启动三个节点，再提交协作贡献链上存证。');window.dispatchEvent(new CustomEvent('marl:chain-changed')); 
});
el('v10-recover').onclick=()=>run(async()=>{show('v10-recovery',await req('/api/distributed/recover',{node:el('v10-node').value}));status('已返回节点恢复结果，请核对返回字段')});
})();
