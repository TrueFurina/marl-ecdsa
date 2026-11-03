/* V24 · MARL-ECDSA semantic icon system (local, inline SVG). */
(() => {
  'use strict';
  const PATHS = {"brand":"<path d=\"M5 6.5 12 3l7 3.5v10L12 21l-7-4.5Z\"/><path d=\"M5 6.5 12 12l7-5.5M12 12v9\"/><circle cx=\"5\" cy=\"6.5\" r=\"1.6\" fill=\"currentColor\" stroke=\"none\"/><circle cx=\"19\" cy=\"6.5\" r=\"1.6\" fill=\"currentColor\" stroke=\"none\"/><circle cx=\"12\" cy=\"12\" r=\"1.8\" fill=\"currentColor\" stroke=\"none\"/><circle cx=\"12\" cy=\"21\" r=\"1.5\" fill=\"currentColor\" stroke=\"none\"/>","overview":"<rect x=\"3\" y=\"3\" width=\"8\" height=\"8\" rx=\"1.8\"/><rect x=\"14\" y=\"3\" width=\"7\" height=\"5\" rx=\"1.5\"/><rect x=\"14\" y=\"11\" width=\"7\" height=\"10\" rx=\"1.8\"/><rect x=\"3\" y=\"14\" width=\"8\" height=\"7\" rx=\"1.8\"/><path d=\"M6 17.5h2M17.5 14v4\"/>","training":"<path d=\"M2.5 14h4l2.5-6 4 11 3.2-9 2.1 4H22\"/><path d=\"M17 4l2-2 2 2\"/>","governance":"<path d=\"M5 19h14M8 16V9m8 7V7\"/><circle cx=\"8\" cy=\"6\" r=\"2.5\"/><circle cx=\"16\" cy=\"4\" r=\"2.5\"/><path d=\"M5 19c0-3 1-4 3-4m8-2c2 0 3 3 3 6\"/>","consensus":"<rect x=\"3\" y=\"3\" width=\"8\" height=\"8\" rx=\"2\"/><rect x=\"13\" y=\"3\" width=\"8\" height=\"8\" rx=\"2\"/><rect x=\"3\" y=\"13\" width=\"8\" height=\"8\" rx=\"2\"/><path d=\"M15 16h6m-3-3v8\"/><path d=\"M11 7h2M7 11v2\"/>","network":"<circle cx=\"12\" cy=\"4\" r=\"2.2\"/><circle cx=\"4.5\" cy=\"19\" r=\"2.2\"/><circle cx=\"19.5\" cy=\"19\" r=\"2.2\"/><path d=\"M10.8 6 5.6 17m7.6-11 5.2 11M7 19h10\"/>","security":"<path d=\"M12 2.5 20 6v5.8c0 4.9-3 8.1-8 9.7-5-1.6-8-4.8-8-9.7V6Z\"/><path d=\"M12 7v5.5m0 3.5h.01\"/>","shield-check":"<path d=\"M12 2.5 20 6v5.8c0 4.9-3 8.1-8 9.7-5-1.6-8-4.8-8-9.7V6Z\"/><path d=\"m8.6 12 2.2 2.2 4.8-5\"/>","shield-alert":"<path d=\"M12 2.5 20 6v5.8c0 4.9-3 8.1-8 9.7-5-1.6-8-4.8-8-9.7V6Z\"/><path d=\"M12 7.8v5.8m0 3h.01\"/>","key":"<circle cx=\"8\" cy=\"15.5\" r=\"4.5\"/><path d=\"m11.5 12.2 8.2-8.2 2 2-2.8 2.8 1.3 1.3-2.8 2.8-1.3-1.3-2.6 2.6\"/>","signature":"<path d=\"M4 4h14v5M4 4v16h16v-8\"/><path d=\"m8 15 4.8-5 2.8 2.8-5 5-3 1Z\"/><path d=\"m14 9 2-2 3 3-2 2\"/>","award":"<circle cx=\"12\" cy=\"9\" r=\"5\"/><path d=\"M8.5 13 6 21l6-3.1 6 3.1-2.5-8\"/><path d=\"m10 9 1.5 1.5L14.5 7\"/>","vote":"<path d=\"M3 20h18v-7H3Z\"/><path d=\"m8 9 4 4 6-8\"/><path d=\"M3 16h18\"/>","epoch":"<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M12 6v6l4 2M6 4 4 6m14-2 2 2\"/>","hash":"<path d=\"M9 3 6 21M18 3l-3 18M3.5 9h18M2.5 15h18\"/>","block":"<path d=\"m12 2 9 5-9 5-9-5 9-5ZM3 7v10l9 5 9-5V7M12 12v10\"/>","audit":"<path d=\"M12 2 4 6v7c0 4 3 7 8 9 5-2 8-5 8-9V6Z\"/><path d=\"m8.5 12 2.4 2.4 4.6-5\"/>","check":"<path d=\"m4.5 12 5.2 5.2L19.5 7\"/>","check-circle":"<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"m8 12 2.8 2.8L16.5 9\"/>","close":"<path d=\"M5 5 19 19M19 5 5 19\"/>","error":"<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M12 7.5v5.5m0 3h.01\"/>","alert":"<path d=\"m12 3 10 17H2Z\"/><path d=\"M12 9v5m0 3h.01\"/>","user":"<circle cx=\"12\" cy=\"8\" r=\"4\"/><path d=\"M4.5 21v-1c0-4 3-6 7.5-6s7.5 2 7.5 6v1\"/>","lock":"<rect x=\"5\" y=\"10\" width=\"14\" height=\"11\" rx=\"2.5\"/><path d=\"M8 10V7a4 4 0 0 1 8 0v3M12 14v3\"/>","eye":"<path d=\"M2 12c2.5-4 5.8-6 10-6s7.5 2 10 6c-2.5 4-5.8 6-10 6S4.5 16 2 12Z\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/>","eye-off":"<path d=\"M3 3 21 21M10 6.2a12 12 0 0 1 2-.2c4.2 0 7.5 2 10 6a16.6 16.6 0 0 1-3 3.5M6 7.5A17 17 0 0 0 2 12c2.5 4 5.8 6 10 6a12 12 0 0 0 3.5-.5\"/><path d=\"M10 10a3 3 0 0 0 4 4\"/>","arrow-right":"<path d=\"M4 12h16m-6-6 6 6-6 6\"/>","arrow-up-right":"<path d=\"M5 19 19 5M8 5h11v11\"/>","refresh":"<path d=\"M20 7a8 8 0 0 0-14-2L3.5 8M3.5 3v5h5M4 17a8 8 0 0 0 14 2l2.5-3M20.5 21v-5h-5\"/>","download":"<path d=\"M12 3v12m-4-4 4 4 4-4M4 18v3h16v-3\"/>","upload":"<path d=\"M12 20V8m-4 4 4-4 4 4M4 6V3h16v3\"/>","play":"<path d=\"m8 5 11 7-11 7Z\"/>","pause":"<path d=\"M7 5v14m10-14v14\"/>","search":"<circle cx=\"10.5\" cy=\"10.5\" r=\"6.5\"/><path d=\"m16 16 5 5\"/>","history":"<path d=\"M3 5v5h5M4 10a8 8 0 1 1 1 7\"/><path d=\"M12 6v6l4 2\"/>","settings":"<path d=\"M10 2h4l.8 3a8 8 0 0 1 2 1.2l3-.8 2 3.5-2.2 2.2a8 8 0 0 1 0 2l2.2 2.1-2 3.6-3-.8a8 8 0 0 1-2 1.2L14 22h-4l-.8-3a8 8 0 0 1-2-1.2l-3 .8-2-3.6 2.2-2.1a8 8 0 0 1 0-2L2.2 8.9l2-3.5 3 .8a8 8 0 0 1 2-1.2Z\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/>","list":"<path d=\"M8 6h13M8 12h13M8 18h13\"/><circle cx=\"4\" cy=\"6\" r=\"1\"/><circle cx=\"4\" cy=\"12\" r=\"1\"/><circle cx=\"4\" cy=\"18\" r=\"1\"/>","file":"<path d=\"M5 2h10l4 4v16H5Z\"/><path d=\"M15 2v5h4M8 11h8M8 15h8M8 19h5\"/>","chart":"<path d=\"M3 21h18M5 17v-7h4v7M11 17V3h4v14M17 17v-9h4v9\"/>","users":"<circle cx=\"9\" cy=\"8\" r=\"3.5\"/><path d=\"M2.5 20v-1c0-3.6 2.6-5.4 6.5-5.4s6.5 1.8 6.5 5.4v1M16 5a3.5 3.5 0 0 1 0 7m1 2c2.7.3 4.5 2 4.5 5v1\"/>","link":"<path d=\"M9 15 15 9M8 9H6a5 5 0 0 0 0 10h5a5 5 0 0 0 5-5M16 15h2a5 5 0 0 0 0-10h-5a5 5 0 0 0-5 5\"/>","copy":"<rect x=\"8\" y=\"8\" width=\"13\" height=\"13\" rx=\"2\"/><path d=\"M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3\"/>","terminal":"<rect x=\"2\" y=\"3\" width=\"20\" height=\"18\" rx=\"2\"/><path d=\"m6 8 4 4-4 4m6 0h5\"/>","menu":"<path d=\"M3 6h18M3 12h18M3 18h18\"/>","logout":"<path d=\"M9 3H4v18h5M12 16l4-4-4-4m4 4H8M14 3h6v18h-6\"/>","compare":"<path d=\"M3 4h8v16H3ZM13 8h8v12h-8Z\"/><path d=\"M6 9h2m8 4h2\"/>","provenance":"<path d=\"M3 4h8v6H3ZM13 14h8v6h-8ZM7 10v6h6M10 4h5v5M15 9l-2-2m2 2 2-2\"/>","sync":"<path d=\"M4 7a8 8 0 0 1 13-2l2 2M19 3v4h-4M20 17a8 8 0 0 1-13 2l-2-2M5 21v-4h4\"/>","flask":"<path d=\"M9 3h6M10 3v7l-6 9c-.9 1.5 0 3 2 3h12c2 0 3-1.5 2-3l-6-9V3\"/><path d=\"M7 17h10m-5-2h.01m3 4h.01\"/>","spark":"<path d=\"m12 2 2.7 7.3L22 12l-7.3 2.7L12 22l-2.7-7.3L2 12l7.3-2.7Z\"/>"};
  function icon(name, className = 'v24-icon') {
    const d = PATHS[name] || PATHS.file;
    return `<svg class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">${d}</svg>`;
  }
  window.MarlIcons = Object.freeze({ icon, paths: Object.freeze(PATHS) });
  // Controls may be inserted at runtime by legacy modules; keep them themed.
  const exactId = {
    'v7-train-refresh':'refresh','v22-refresh':'refresh',
    'v22-to-train':'training','v22-to-preview':'governance','v22-to-attest':'signature',
    'v22-to-trace':'audit','v22-to-nodes':'network',
    'v21-jobs-refresh':'refresh','v10-preview':'governance','v10-activate':'check-circle',
    'v10-snapshot':'epoch','v11-epochs':'history','v10-recover':'sync','v20-attest':'signature',
    'v21-trace-btn':'audit','v9-refresh':'refresh','v9-verify':'audit',
    'v7-tx-refresh':'refresh','v7-tx-search':'search','v8-audit':'audit',
    'v8-blocks-refresh':'refresh','v8-receipt':'file','v8-export':'download',
    'v8-tamper-btn':'shield-alert','probe-run':'network','probe-export':'download',
    'net-repeat':'refresh','incentive-export':'download'
  };
  const byLabel = [
    [/刷新|重新检测/, 'refresh'],[/导出|下载/, 'download'],[/训练|开始协作/, 'training'],
    [/贡献|评分|排名|排行榜/, 'governance'],[/快照|纪元|历史/, 'epoch'],
    [/核验|验证|审计|防篡改|检查/, 'audit'],[/节点|连通|同步/, 'network'],
    [/提交|签名|确认/, 'signature'],[/安全|攻击|故障|女巫|伪造|篡改|重放/, 'security'],
    [/查看|查询/, 'search'],[/报告/, 'file'],[/取消/, 'close'],[/生成|激活/, 'check-circle']
  ];
  function iconFor(button){
    if (button.id in exactId) return exactId[button.id];
    if (button.matches('.nav-tab,.toggle-btn,.menu-trigger,.auth-submit,.password-reveal,.v24-decorated')) return null;
    if (button.closest('.auth-form') && button.type === 'submit') return null;
    const label = (button.textContent || '').trim().replace(/\s+/g, ' ');
    if (label.length > 50 || !label || button.closest('svg')) return null;
    const found = byLabel.find(([pattern]) => pattern.test(label));
    return found ? found[1] : null;
  }
  function applyOne(button){
    if (button.classList.contains('v24-decorated')) return;
    const name = iconFor(button);
    if (!name) return;
    // Keep original text, id, handlers and form behaviour unchanged.
    const holder = document.createElement('span');
    holder.className = 'v24-action-icon';
    holder.innerHTML = icon(name);
    button.insertBefore(holder,button.firstChild);
    button.classList.add('v24-decorated');
  }
  function decorate(root){
    if (root.nodeType !== 1) return;
    if (root.matches?.('button')) applyOne(root);
    root.querySelectorAll?.('button').forEach(applyOne);
  }
  function init(){
    decorate(document.body);
    const observer = new MutationObserver(records=>{
      for(const rec of records) for(const node of rec.addedNodes) if(node.nodeType === 1) decorate(node);
    });
    observer.observe(document.body,{subtree:true,childList:true});
    // Page sign-in toggles intentionally keep an explicit textual label.
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();
