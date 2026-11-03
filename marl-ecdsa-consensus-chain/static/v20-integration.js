(()=>{'use strict';const $=id=>document.getElementById(id),button=$('v20-attest');if(!button)return;
const status=$('v20-attest-status'),result=$('v20-attest-result'),traceButton=$('v21-trace-btn');
async function req(path,method,body){const r=await fetch(path,{method:method||'GET',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':window.APP_CSRF||''},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||`请求失败 (${r.status})`);return d}
button.addEventListener('click',async()=>{button.disabled=true;status.textContent='正在核对本账户训练结果、贡献记录和当前纪元，然后进行交易签名与加权共识…';try{
const selectedJob=$('v22-job')?.value;if(!selectedJob)throw Error('请先选择已完成且来源有效的 BC-MARL 训练任务');
const data=await req('/api/distributed/contribution/attest','POST',{job_id:selectedJob,timeout:Number($('v11-timeout')?.value||1),max_views:Number($('v11-views')?.value||3)});
result.textContent=JSON.stringify(data,null,2);window.dispatchEvent(new CustomEvent('marl:consensus-proposed',{detail:data}));
status.textContent=data.status==='already_attested'?'该任务在当前纪元已有链上存证；请核验现有区块，不要重复提交。':data.status==='replicated'?'三个节点返回匹配的区块写入回执。可以进一步核验链上记录与训练来源。':data.status==='partially_replicated'?'仅部分节点已写入，尚未完全复制':data.status==='commit_unconfirmed'?'取得投票证书，但写入尚未确认':'共识门槛未达成，未确认出块';
if(data.block_height){const h=$('v9-height');if(h)h.value=data.block_height;$('v21-trace-height').value=data.block_height;}window.dispatchEvent(new CustomEvent('marl:chain-changed'));
}catch(e){status.textContent='提交失败：'+e.message;result.textContent='存证需先用当前账户的训练任务激活贡献纪元，并确保独立节点在线。'}finally{button.disabled=false}});
traceButton.addEventListener('click',async()=>{traceButton.disabled=true;$('v21-trace-status').textContent='正在跨节点检查区块并重新计算训练文件摘要…';try{
const height=Number($('v21-trace-height').value);if(!Number.isInteger(height)||height<1)throw Error('请输入有效区块高度');
const data=await req('/api/distributed/collaboration/trace/'+height);
const chosen=$('v22-job')?.value;if(chosen&&data.training_job_id&&chosen!==data.training_job_id)throw Error('该区块对应其他训练任务，请在上方切换至匹配任务后核验');
$('v21-trace-result').textContent=JSON.stringify(data,null,2);
$('v21-trace-status').textContent=data.verified?'共识证书、节点账本、纪元权重及本地训练来源均验证通过':`证据尚未完整验证：跨节点一致=${data.cross_node_consistent}；纪元匹配=${data.evidence_fields_match_epoch}；本地训练来源匹配=${data.training_artifacts_match}`;
}catch(e){$('v21-trace-status').textContent=e.message}finally{traceButton.disabled=false}});
})();
