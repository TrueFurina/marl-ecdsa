// V16: presentation/navigation only; existing business APIs unchanged.
(()=>{'use strict';const names={overview:'研究工作台',train:'协作训练',incentive:'贡献治理',chain:'可信共识',audit:'证据审计'};document.addEventListener('click',e=>{const b=e.target.closest('.nav-tab');if(b){const k=b.dataset.tab;const h=document.getElementById('current-location');if(h&&names[k])h.textContent=names[k]}});})();
