/* V25: display actual distributed nodes and verify blocks committed by training governance. */
(()=>{'use strict';
const $=id=>document.getElementById(id);if(!$('v9-nodes'))return;
const output=$('v9-result');
async function api(url){const response=await fetch(url,{credentials:'same-origin'});
 let data;try{data=await response.json()}catch{throw Error('后端未返回有效 JSON')}
 if(!response.ok)throw Error(data.error||'HTTP '+response.status);return data}
const show=value=>{if(output)output.textContent=typeof value==='string'?value:JSON.stringify(value,null,2)};
function showNode(n){const card=document.createElement('div');card.className='v9-node';
 const title=document.createElement('b');title.textContent=n.node||'未命名节点';
 const details=document.createElement('small');details.textContent=(n.online?'在线':'离线')+' · 区块 '+(n.height??'—')+' · 票权 '+(n.weight??'—')+(n.epoch_matched===false?' · 纪元不匹配':'');
 card.append(title,details);return card}
async function nodes(){try{const data=await api('/api/distributed/nodes');$('v9-nodes').replaceChildren(...(data.nodes||[]).map(showNode));
 if(!data.nodes?.length)show('没有节点配置，请检查分布式共识初始化。')}
 catch(error){show('节点查询失败：'+error.message)}}
$('v9-refresh')?.addEventListener('click',nodes);
$('v9-verify')?.addEventListener('click',async()=>{const height=Number($('v9-height')?.value);
 if(!Number.isInteger(height)||height<1){show('请输入有效的已确认区块高度');return}
 try{show(await api('/api/distributed/verify/'+height))}catch(error){show('跨节点核验失败：'+error.message)}});
window.addEventListener('marl:chain-changed',nodes);
nodes();
})();
