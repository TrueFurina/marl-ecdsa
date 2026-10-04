// MARL-ECDSA Dashboard - Main JavaScript
// Extracted from dashboard.html on 2026-09-26
// ============================================

// ===================== 调试 =====================
(function() {
    var debugBar = document.getElementById('debug-bar');
    window._debug = function(msg, color) {
        debugBar.style.display = 'block';
        debugBar.style.background = color || '#1a3a2a';
        debugBar.style.color = '#fff';
        debugBar.textContent = '[DEBUG] ' + msg;
        console.log('[DEBUG]', msg);
    };
    window._error = function(msg) {
        debugBar.style.display = 'block';
        debugBar.style.background = '#5a1a1a';
        debugBar.style.color = '#faa';
        debugBar.textContent = '[ERROR] ' + msg;
        console.error('[ERROR]', msg);
    };
    // Global error catch
    window.addEventListener('error', function(e) {
        _error(e.message + ' (line ' + e.lineno + ')');
    });
    // Check Chart.js
    setTimeout(function() {
        if (typeof Chart === 'undefined') {
            _error('Chart.js 未加载！请检查 /static/chart.umd.min.js');
        } else {
            _debug('Chart.js v' + (Chart.version||'?') + ' 加载成功');
            setTimeout(function() { debugBar.style.display = 'none'; }, 2000);
        }
    }, 500);
})();

// ===================== 粒子背景 =====================
(function() {
    const c = document.getElementById('particles');
    const ctx = c.getContext('2d');
    let w, h, particles = [];
    function resize() { w = c.width = window.innerWidth; h = c.height = window.innerHeight; }
    resize(); window.addEventListener('resize', resize);

    // 更多粒子 + 多种颜色
    for (let i = 0; i < 80; i++) {
        const colorSet = ['56,189,248', '129,140,248', '52,211,153'];
        const ci = Math.floor(Math.random() * colorSet.length);
        particles.push({
            x: Math.random() * w, y: Math.random() * h,
            vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25,
            r: Math.random() * 2 + 0.5, o: Math.random() * 0.35 + 0.08,
            color: colorSet[ci]
        });
    }
    function animate() {
        ctx.clearRect(0, 0, w, h);
        particles.forEach(p => {
            p.x += p.vx; p.y += p.vy;
            if (p.x < 0) p.x = w; if (p.x > w) p.x = 0;
            if (p.y < 0) p.y = h; if (p.y > h) p.y = 0;
            ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI*2);
            ctx.fillStyle = `rgba(${p.color},${p.o})`; ctx.fill();
        });
        // lines between close particles
        for (let i = 0; i < particles.length; i++) {
            for (let j = i+1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const d = Math.sqrt(dx*dx + dy*dy);
                if (d < 100) {
                    ctx.beginPath(); ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(${particles[i].color},${0.04*(1-d/100)})`;
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(animate);
    }
    animate();
})();

// ===================== 数字动画 =====================
function animateNumber(el, target, duration=1200) {
    if (!el) return;
    const start = 0;
    const startTime = performance.now();
    const isPercent = typeof target === 'string' && target.includes('%');
    const numTarget = parseFloat(target.toString().replace('%',''));
    function step(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
        const current = start + (numTarget - start) * eased;
        if (isPercent) el.textContent = (current >= 0 ? '+' : '') + current.toFixed(0) + '%';
        else el.textContent = current.toFixed(Number.isInteger(numTarget) ? 0 : 1);
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

// ===================== 演示模式 =====================
let demoMode = false;
let demoInterval = null;
// 09-28 修复：此前漏掉 'attack'，演示模式 6s 轮播永不展示攻防演示页（自废最强演示页）。
// 追加在末尾（而非按导航顺序插入），以保持既有键盘快捷键 1-9 → TABS[0..8] 的映射不变。
const TABS = ['overview', 'monitor', 'compare', 'tri', 'blockchain', 'consensus', 'explorer', 'system', 'p2p', 'attack'];

function toggleDemoMode() {
    demoMode = !demoMode;
    document.getElementById('btn-demo').classList.toggle('active', demoMode);
    document.getElementById('demo-indicator').classList.toggle('show', demoMode);
    if (demoMode) {
        demoInterval = setInterval(() => {
            const current = TABS.findIndex(t => document.getElementById('tab-' + t).classList.contains('active'));
            const next = (current + 1) % TABS.length;
            switchTab(TABS[next]);
        }, 6000);
    } else {
        clearInterval(demoInterval);
        demoInterval = null;
    }
}

// ===================== 导出报告 =====================
function showExportModal() { document.getElementById('export-modal').classList.add('show'); }
function hideExportModal() { document.getElementById('export-modal').classList.remove('show'); }

function doExport() {
    hideExportModal();
    const ps = pureData?.summary || {};
    const bs = bcData?.summary || {};
    const ss = selfishData?.summary || {};
    const now = new Date().toLocaleString('zh-CN');

    const reportHTML = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>MARL-ECDSA 实验报告</title>
<style>body{font-family:'Microsoft YaHei',sans-serif;background:#fff;color:#333;padding:40px;line-height:1.8;max-width:900px;margin:auto}
h1{text-align:center;border-bottom:2px solid #38bdf8;padding-bottom:10px;margin-bottom:30px;color:#0f172a}
h2{color:#1e40af;margin-top:25px;border-left:3px solid #38bdf8;padding-left:10px}
table{width:100%;border-collapse:collapse;margin:15px 0}th,td{border:1px solid #ddd;padding:8px 12px;text-align:center}
th{background:#f1f5f9;font-weight:600;color:#475569}td{font-size:0.9rem}
.highlight{background:#ecfdf5;color:#065f46;padding:10px;border-radius:6px;font-weight:600;margin:15px 0}
.footer{text-align:center;color:#94a3b8;font-size:0.75rem;margin-top:30px;padding-top:15px;border-top:1px solid #e2e8f0}</style></head><body>
<h1>MARL-ECDSA 共识链 — 对照实验报告</h1>
<p style="text-align:center;color:#64748b">生成时间：${now} · CCF 第五届区块链竞赛</p>

<h2>实验概述</h2>
<p>本实验通过三组对照实验验证区块链激励机制对多智能体协作的提升效果：</p>
<table><tr><th>实验组</th><th>模式</th><th>说明</th><th>平均奖励</th><th>合作率</th></tr>
<tr><td>Exp A</td><td>Pure MARL</td><td>纯多智能体协同</td><td>${ps.avg_reward?.toFixed(1)||'--'}</td><td>${((ps.avg_cooperation_rate||0)*100).toFixed(1)}%</td></tr>
<tr><td>Exp B</td><td>BC-MARL</td><td>MARL+区块链激励</td><td>${bs.avg_reward?.toFixed(1)||'--'}</td><td>${((bs.avg_cooperation_rate||0)*100).toFixed(1)}%</td></tr>
<tr><td>Exp C</td><td>Selfish</td><td>含自私智能体</td><td>${ss.avg_reward?.toFixed(1)||'--'}</td><td>${((ss.avg_cooperation_rate||0)*100).toFixed(1)}%</td></tr></table>

<h2>核心结论</h2>
<div class="highlight">🏆 权威申报口径（登记簿 NR-1，n=71/组）：末50回合 env_reward +28.17%（Welch p=0.0095，BH-FDR 显著/Bonferroni 不显著），须与 NR-2 全程 +7.92%（p&lt;1e-10）同报。本机运行观测：总奖励提升 ${(bs.avg_reward&&ps.avg_reward) ? ((bs.avg_reward-ps.avg_reward)/Math.abs(ps.avg_reward)*100).toFixed(0) : '--'}%（当前加载运行·演示数据，非申报口径）。
${(ps.avg_env_reward!=null&&bs.avg_env_reward!=null&&ps.avg_env_reward!==0) ? '⚖ <strong>环境奖励（公平对比，env_reward）提升 '+((Math.abs(ps.avg_env_reward)-Math.abs(bs.avg_env_reward))/Math.abs(ps.avg_env_reward)*100).toFixed(0)+'%</strong> — 该口径为申报主口径。' : '本页为单次演示运行；申报主口径为 n=71/组 env_reward：末50回合 +28.2%（Welch p=0.0095）与全程 +7.9%（p&lt;1e-10）两口径同报，效果强依赖底层算法。'}</div>

<h2>ECDSA 安全机制</h2>
<table><tr><th>安全特性</th><th>实现</th></tr>
<tr><td>密钥算法</td><td>ECDSA secp256r1 (P-256)</td></tr>
<tr><td>签名标准</td><td>FIPS 186-5 + RFC 6979 确定性k值</td></tr>
<tr><td>k值重用检测</td><td>相同r值签名→告警（私钥可推导风险）</td></tr>
<tr><td>nonce防重放</td><td>单调递增nonce + 时间戳±30秒有效期</td></tr></table>

<h2>CW-PBFT 共识机制</h2>
<table><tr><th>参数</th><th>值</th></tr>
<tr><td>共识算法</td><td>CW-PBFT（贡献加权PBFT）</td></tr>
<tr><td>投票阈值</td><td>≥ 2/3 权重同意即确认</td></tr>
<tr><td>贡献权重</td><td>task=0.40, coop=0.35, compliance=0.25</td></tr>
<tr><td>惩罚等级</td><td>警告(10) → 降权(30) → 封禁(50)</td></tr></table>

<h2>区块链流水线统计</h2>
<p>以下数据来自 BC-MARL 实验组（1000 回合完整集成训练），验证区块链与MARL双向协同的完整数据流。</p>
<table><tr><th>流水线模块</th><th>指标</th><th>值</th></tr>
${(() => {
    const bc = bcData || {};
    const es = bc.ecdsa_stats || {};
    const ss = bc.security_stats || {};
    const cs = bc.consensus_stats || {};
    const bs = bc.blockchain_stats || {};
    const rows = [
        ['ECDSA 签名', '签名次数', es.sign_count || '--'],
        ['ECDSA 签名', '验签次数', es.verify_count || '--'],
        ['SecurityGuard', '通过次数', ss.security_pass_count || '--'],
        ['SecurityGuard', '拦截次数', ss.security_fail_count || '--'],
        ['SecurityGuard', '总告警数', ss.total_alerts || '--'],
        ['Blockchain', '链高度', bs.height || '--'],
        ['Blockchain', '总交易数', bs.total_transactions || '--'],
        ['CW-PBFT', 'PREPARE 投票数', cs.prepare_votes || '--'],
    ];
    return rows.map(r => '<tr><td>'+r[0]+'</td><td>'+r[1]+'</td><td>'+r[2]+'</td></tr>').join('');
})()}</table>

<h2>算法与环境参数</h2>
<table><tr><th>参数</th><th>值</th></tr>
<tr><td>算法</td><td>IQL (Independent Q-Learning)</td></tr>
<tr><td>环境</td><td>SimpleSpread (NumPy)</td></tr>
<tr><td>智能体数</td><td>3</td></tr>
<tr><td>目标点数</td><td>3</td></tr>
<tr><td>最大步数</td><td>25</td></tr>
<tr><td>隐藏维度</td><td>128</td></tr>
<tr><td>学习率</td><td>0.001</td></tr>
<tr><td>折扣因子 γ</td><td>0.8</td></tr>
<tr><td>λ权重</td><td>0.1</td></tr>
<tr><td>训练回合</td><td>1000</td></tr></table>

<div class="footer">MARL-ECDSA 共识链 · CCF 第五届区块链竞赛 · ${now}</div></body></html>`;

    const blob = new Blob([reportHTML], {type: 'text/html'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'MARL-ECDSA_实验报告.html'; a.click();
    URL.revokeObjectURL(url);
}

// ===================== 键盘快捷键 =====================
document.addEventListener('keydown', (e) => {
    if (e.key >= '1' && e.key <= '9') { switchTab(TABS[parseInt(e.key)-1]); e.preventDefault(); }
    if (e.key === 'p' || e.key === 'P') { toggleDemoMode(); e.preventDefault(); }
    if (e.key === 'e' || e.key === 'E') { showExportModal(); e.preventDefault(); }
    if (e.key === 'Escape') { hideExportModal(); if (demoMode) toggleDemoMode(); }
});

// ===================== 标签切换 =====================
function switchTab(tab) {
    document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
    const btn = document.querySelector(`.nav-tab[data-tab="${tab}"]`);
    if (btn) btn.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const content = document.getElementById('tab-' + tab);
    if (content) content.classList.add('active');
    if (tab === 'compare') loadComparison();
    if (tab === 'tri') loadTriComparison();
    if (tab === 'blockchain') loadBlockchain();
    if (tab === 'consensus') loadConsensus();
    if (tab === 'explorer') loadBlockExplorer();
    if (tab === 'system') loadSystem();
    if (tab === 'overview') loadOverview();
    if (tab === 'monitor') loadMonitor();
    if (tab === 'p2p') loadP2PData();
    if (tab === 'attack') loadAttackPanel();
}

document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ===================== 数据加载 =====================
// v3.9: 原先此处用 Jinja 注入（{{ pure_data_json | safe }}），但本文件经 /static/
// 原样服务，Jinja 不渲染 → 浏览器 JS 语法错误 → 整页初始化中断（白屏 P0）。
// 改为 null 初始化，统一由 loadData() 走 /api/load/<mode> 运行时获取。
let pureData = null;
let bcData = null;
let selfishData = null;
let monitorMode = 'bc';
let charts = {};
// ===================== 图表工具函数 =====================
// 显著性检验（两样本均值差异）
function checkSig(m1, ci1, m2, ci2) {
    // 简化：如果置信区间不重叠，差异显著
    var m1lo = m1 - ci1, m1hi = m1 + ci1;
    var m2lo = m2 - ci2, m2hi = m2 + ci2;
    if (m1hi < m2lo || m2hi < m1lo) return 'p<0.05 (显著)';
    return 'p>0.05';
}
// 滑动窗口平滑（专业呈现用大窗口压制噪声）
function smoothData(arr, windowSize) {
    var w = Math.max(1, Math.min(windowSize, arr.length));
    var s = [];
    for (var i = 0; i < arr.length - w + 1; i++) {
        var sum = 0;
        for (var j = i; j < i + w; j++) sum += arr[j];
        s.push(sum / w);
    }
    return s;
}
// 生成 x 轴标签（平滑后从 windowSize 开始编号）
function smoothLabels(smoothed, windowSize) {
    var labels = [];
    for (var i = 0; i < smoothed.length; i++) labels.push(i + windowSize);
    return labels;
}

// 全局基座图表配置（专业暗色主题）
var baseOpts = {
    responsive: true,
    maintainAspectRatio: true,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
        legend: {
            labels: { color: '#cbd5e1', font: { size: 12 }, usePointStyle: true, pointStyleWidth: 8, padding: 16 }
        },
        tooltip: {
            backgroundColor: 'rgba(15,23,42,0.92)',
            titleColor: '#f1f5f9',
            bodyColor: '#cbd5e1',
            borderColor: 'rgba(56,189,248,0.35)',
            borderWidth: 1,
            padding: 10,
            cornerRadius: 6
        }
    },
    scales: {
        x: {
            grid: { color: 'rgba(148,163,184,0.06)', drawTicks: false },
            ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 12 }
        },
        y: {
            grid: { color: 'rgba(148,163,184,0.08)', drawTicks: false },
            ticks: { color: '#64748b', font: { size: 10 } },
            beginAtZero: false
        }
    }
};

async function loadData(type) {
    // 服务端已通过 Jinja2 预注入数据，直接返回对应变量
    if (type === 'pure' && pureData) return pureData;
    if (type === 'bc' && bcData) return bcData;
    if (type === 'selfish' && selfishData) return selfishData;
    // 回退到API（运行时/动态数据）
    try {
        const resp = await fetch('/api/load/' + type);
        if (!resp.ok) return null;
        return await resp.json();
    } catch(e) { return null; }
}

async function initAll() {
    const bar = document.getElementById('loading-bar');
    bar.style.width = '20%';

    // 若预注入不完整，则fetch补充
    try {
        if (!pureData || !bcData) {
            [pureData, bcData] = await Promise.all([loadData('pure'), loadData('bc')]);
        }
        bar.style.width = '60%';
        if (!selfishData) selfishData = await loadData('selfish');
        bar.style.width = '80%';
    } catch(e) {
        console.warn('历史数据加载失败:', e);
        _error('数据加载失败: ' + e.message);
    }

    bar.style.width = '100%';

    // 隐藏加载遮罩
    setTimeout(() => {
        document.getElementById('loading-overlay').classList.add('hide');
    }, 500);

    const loaded = pureData || bcData;
    if (!loaded) {
        _error('未加载到任何训练数据！请检查 training_results_*.json');
        document.getElementById('top-mode').textContent = '数据加载失败';
    } else {
        document.getElementById('top-mode').textContent = '数据已加载';
        _debug('数据加载成功: pure=' + (pureData ? pureData.summary.total_episodes : 'N/A') + 'eps, bc=' + (bcData ? bcData.summary.total_episodes : 'N/A') + 'eps');
        setTimeout(function() { document.getElementById('debug-bar').style.display = 'none'; }, 2000);
    }

    loadOverview();
    loadMonitor();

    // 权威口径 Bento 卡（登记簿驱动）+ 数据截至时间戳
    renderCaliber();
    setDataUpdated();
}

// ===================== 权威口径（登记簿驱动，禁手抄） =====================
// 兜底常量与 deliverables/number_registry.json 登记值一致；正常情况数据来自
// /api/caliber（后端程序化读登记簿），口径出处显示在卡片脚注。
// NR-1（末50回合）与 NR-2（全程）必须同报，禁单点宣称"激励有效"。
var CALIBER_FALLBACK = {
    nr1: { pct: '+28.17%', p: '0.0095', d: '0.44', n: 71 },
    nr2: { pct: '+7.92%', p: '<1e-10', d: '1.20' },
    nr3: { pct: '+1.95%' }
};

function setDataUpdated() {
    var el = document.getElementById('data-updated');
    var chip = document.getElementById('data-updated-chip');
    if (!el) return;
    var t = new Date();
    var pad = function(x) { return ('0' + x).slice(-2); };
    el.textContent = '数据截至 ' + pad(t.getHours()) + ':' + pad(t.getMinutes()) + ':' + pad(t.getSeconds());
    if (chip) chip.classList.remove('stale');
}

function renderCaliber() {
    var done = function(cal, source) {
        var g = function(id) { return document.getElementById(id); };
        if (g('cal-nr1-pct')) g('cal-nr1-pct').textContent = cal.nr1.pct;
        if (g('cal-nr1-p')) g('cal-nr1-p').textContent = cal.nr1.p;
        if (g('cal-nr1-d')) g('cal-nr1-d').textContent = cal.nr1.d;
        if (g('cal-nr2-pct')) g('cal-nr2-pct').textContent = cal.nr2.pct;
        if (g('cal-nr2-p')) g('cal-nr2-p').textContent = cal.nr2.p;
        if (g('cal-nr2-d')) g('cal-nr2-d').textContent = cal.nr2.d;
        if (g('cal-nr3-pct')) g('cal-nr3-pct').textContent = cal.nr3.pct;
        if (g('cal-n')) g('cal-n').textContent = cal.nr1.n || 71;
        if (g('cal-src')) g('cal-src').textContent = '口径出处：' + source;
    };
    var fmtP = function(v) {
        if (v == null || isNaN(Number(v))) return '--';
        return Number(v) < 0.001 ? '<1e-10' : Number(v).toFixed(4);
    };
    if (typeof fetch === 'function') {
        fetch('/api/caliber')
            .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error('http ' + r.status)); })
            .then(function(j) {
                var c = j.caliber || {};
                var n1 = c['NR-1'] || {}, n2 = c['NR-2'] || {}, n3 = c['NR-3'] || {};
                if (n1.improvement_pct == null) return Promise.reject(new Error('empty caliber'));
                done({
                    nr1: { pct: '+' + Number(n1.improvement_pct).toFixed(2) + '%',
                           p: fmtP(n1.welch_p), d: Number(n1.cohens_d).toFixed(2), n: n1.n || 71 },
                    nr2: { pct: '+' + Number(n2.improvement_pct).toFixed(2) + '%',
                           p: fmtP(n2.welch_p), d: Number(n2.cohens_d).toFixed(2) },
                    nr3: { pct: '+' + Number(n3.improvement_pct).toFixed(2) + '%' }
                }, j.source || 'number_registry.json');
            })
            .catch(function() {
                done(CALIBER_FALLBACK, 'fallback（登记簿接口不可达，用内置兜底值）');
            });
    } else {
        done(CALIBER_FALLBACK, 'fallback（浏览器无 fetch，用内置兜底值）');
    }
}

// ===================== 总览 =====================
function loadOverview() {
    const d = bcData || pureData || {};
    const s = d.summary || {};

    const overviewStats = document.getElementById('overview-stats');
    if (!overviewStats) return;

    const pureAvg = pureData?.summary?.avg_reward || 0;
    const bcAvg = bcData?.summary?.avg_reward || 0;
    const selfishAvg = selfishData?.summary?.avg_reward || 0;
    const improvement = pureAvg !== 0 ? ((bcAvg - pureAvg) / Math.abs(pureAvg) * 100) : 0;

    overviewStats.innerHTML = [
        {l:'纯MARL均奖励', v:(pureAvg||0).toFixed(1), u:'/回合', c:'accent'},
        {l:'BC-MARL均奖励', v:(bcAvg||0).toFixed(1), u:'/回合', c:'accent2'},
        {l:'Selfish均奖励', v:(selfishAvg||0).toFixed(1), u:'/回合', c:'danger'},
        {l:'BC提升幅度', v: (improvement||0).toFixed(1)+'%', u:'', c:'success'},
    ].map(s => `<div class="stat-card ${s.c}"><div class="label">${s.l}</div><div class="value animated-num">${s.v}<span class="unit"> ${s.u}</span></div></div>`).join('');

    // 数字动画
    setTimeout(() => {
        overviewStats.querySelectorAll('.animated-num').forEach(el => {
            const val = el.textContent.trim().replace(/[^0-9.\-]/g, '');
            animateNumber(el, parseFloat(val) || 0);
        });
    }, 100);

    // v3.4: 实验核心结论对比表格
    const cmpTable = document.getElementById('ov-comparison-table');
    if (cmpTable) {
        const pureR50 = pureData?.summary?.avg_reward_last_50 || 0;
        const bcR50 = bcData?.summary?.avg_reward_last_50 || 0;
        const sfR50 = selfishData?.summary?.avg_reward_last_50 || 0;
        const pureCoop = (pureData?.summary?.avg_cooperation_rate || 0) * 100;
        const bcCoop = (bcData?.summary?.avg_cooperation_rate || 0) * 100;
        const sfCoop = (selfishData?.summary?.avg_cooperation_rate || 0) * 100;
        const pureTime = pureData?.summary?.elapsed_time || 0;
        const bcTime = bcData?.summary?.elapsed_time || 0;
        const sfTime = selfishData?.summary?.elapsed_time || 0;
        const pureBetrayal = (pureData?.summary?.avg_betrayal_rate || 0) * 100;
        const bcBetrayal = (bcData?.summary?.avg_betrayal_rate || 0) * 100;
        const sfBetrayal = (selfishData?.summary?.avg_betrayal_rate || 0) * 100;

        // 数据缺失一律显示 '--'（不显示 0，避免被误读为「该组跑了但得 0」）
        const hasPure = !!pureData, hasBc = !!bcData, hasSf = !!selfishData;
        const dig = (o, path) => { try { return path.split('.').reduce((a, k) => (a == null ? undefined : a[k]), o); } catch (e) { return undefined; } };
        const fmtPct = (v, has) => (has ? (v||0).toFixed(1) + '%' : '--');
        const fmtTime = (v) => (v||0).toFixed(0) + 's';
        const fmtR = (v, has) => (has ? (v||0).toFixed(1) : '--');
        const fmtInt = (v) => (v == null ? '--' : Number(v).toLocaleString());
        const bcVsPure = (pureV, bcV) => {
            if (pureV === 0) return '--';
            const pct = ((bcV - pureV) / Math.abs(pureV) * 100);
            const arrow = pct > 0 ? '↑' : '↓';
            return `<span style="color:${pct > 0 ? '#34d399' : '#f87171'}">${arrow}${(Math.abs(pct||0)).toFixed(1)}%</span>`;
        };

        cmpTable.innerHTML = [
            ['全程均奖励', fmtR(pureAvg, hasPure), fmtR(bcAvg, hasBc), fmtR(selfishAvg, hasSf), bcVsPure(pureAvg, bcAvg)],
            ['后50回合均奖励', fmtR(pureR50, hasPure), fmtR(bcR50, hasBc), fmtR(sfR50, hasSf), bcVsPure(pureR50, bcR50)],
            ['合作率', fmtPct(pureCoop, hasPure), fmtPct(bcCoop, hasBc), fmtPct(sfCoop, hasSf), '<span class="note-tag">behavioral 口径（本运行观测）</span>'],
            ['背叛率', fmtPct(pureBetrayal, hasPure), fmtPct(bcBetrayal, hasBc), fmtPct(sfBetrayal, hasSf), '<span class="note-tag">behavioral 口径；Selfish 组含 30% 自私智能体</span>'],
            ['训练耗时', fmtTime(pureTime), fmtTime(bcTime), fmtTime(sfTime), '--'],
            ['ECDSA 签名', '0（无区块链）', fmtInt(dig(bcData, 'ecdsa_stats.sign_count')), fmtInt(dig(selfishData, 'ecdsa_stats.sign_count')), '--'],
            ['区块高度', '0（无区块链）', fmtInt(dig(bcData, 'blockchain_stats.height')), fmtInt(dig(selfishData, 'blockchain_stats.height')), '--'],
            ['CW-PBFT PREPARE 投票', '0（无区块链）', fmtInt(dig(bcData, 'consensus_stats.prepare_votes')), fmtInt(dig(selfishData, 'consensus_stats.prepare_votes')), '--'],
        ].map(row => `<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
            <td style="color:var(--text-dim);padding:6px 8px;">${row[0]}</td>
            <td style="color:#94a3b8;text-align:center;padding:6px 8px;">${row[1]}</td>
            <td style="color:#38bdf8;text-align:center;padding:6px 8px;font-weight:600;">${row[2]}</td>
            <td style="color:#f87171;text-align:center;padding:6px 8px;">${row[3]}</td>
            <td style="color:#34d399;text-align:center;padding:6px 8px;font-weight:600;">${row[4]}</td>
        </tr>`).join('');
    }

    // v3.4: 区块链流水线规模
    const pipelineScale = document.getElementById('ov-pipeline-scale');
    if (pipelineScale && bcData) {
        const ecdsa = bcData.ecdsa_stats || {};
        const security = bcData.security_stats || {};
        const blkchain = bcData.blockchain_stats || {};
        const consensus = bcData.consensus_stats || {};
        pipelineScale.innerHTML = [
            {l:'ECDSA签名', v:ecdsa.sign_count||0, c:'#34d399', icon:'🔐'},
            {l:'ECDSA验签', v:ecdsa.verify_count||0, c:'#38bdf8', icon:'✅'},
            {l:'SecurityGuard通过', v:security.security_pass_count||0, c:'#fbbf24', icon:'🛡️'},
            {l:'CW-PBFT PREPARE投票', v:consensus.prepare_votes||0, c:'#818cf8', icon:'⚖️'},
        ].map(s => `<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:10px;padding:12px;text-align:center;">
            <div style="font-size:0.7rem;color:#94a3b8;margin-bottom:4px;">${s.icon} ${s.l}</div>
            <div style="font-size:1.3rem;font-weight:700;color:${s.c};">${typeof s.v==='number'&&s.v>9999?((s.v||0)/1000).toFixed(0)+'K':(s.v||0)}</div>
        </div>`).join('');
    }
}

// ===================== 训练监控 =====================
function switchMonitorMode(mode) {
    monitorMode = mode;
    document.getElementById('btn-bc').classList.toggle('active', mode === 'bc');
    document.getElementById('btn-pure').classList.toggle('active', mode === 'pure');
    document.getElementById('btn-selfish').classList.toggle('active', mode === 'selfish');
    loadMonitor();
}

function loadMonitor() {
    const d = monitorMode === 'bc' ? bcData : (monitorMode === 'selfish' ? selfishData : pureData);
    if (!d) { document.getElementById('monitor-stats').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-dim)">等待训练数据...</div>'; return; }
    // 自动适配单种子 / 合并格式
    const fmt = d._format || 'single';
    const isCombined = fmt === 'combined';
    const rewards = isCombined ? (d.episode_rewards_mean || []) : (d.episode_rewards || []);
    const rewardsStd = isCombined ? (d.episode_rewards_std || null) : null;
    const coops = isCombined ? (d.cooperation_rates_mean || []) : (d.cooperation_rates || []);
    const betrayals = isCombined ? [] : (d.betrayal_rates || []);
    const s = d.summary || {};
    const config = d.config || {};
    const nSeeds = d.n_seeds || 1;

    document.getElementById('top-mode').textContent = (config.mode || monitorMode) + (isCombined ? ' (' + nSeeds + '种子)' : '');

    // 统计卡片
    const avgReward = rewards.length ? (rewards.reduce((a,b)=>a+b,0)/rewards.length) : 0;
    const last50Avg = s.avg_reward_last_50 || 0;
    document.getElementById('monitor-stats').innerHTML = [
        {l:'训练回合', v:s.total_episodes||0, u: isCombined ? ' ('+nSeeds+'种子)' : ''},
        {l:'平均奖励', v:(avgReward||0).toFixed(1), u: isCombined && s.avg_reward_std ? ' ±' + (s.avg_reward_std||0).toFixed(1) : '/回合', c:'accent'},
        {l:'最近50回合', v:(last50Avg||0).toFixed(1), u:'(收敛值)', c:'accent2'},
        {l:'合作率', v:((s.avg_cooperation_rate||0)*100).toFixed(1)+'%', u: isCombined && s.avg_cooperation_rate_std ? ' ±'+((s.avg_cooperation_rate_std||0)*100).toFixed(1)+'%' : '', c:'success'},
        {l:'总耗时', v:(s.elapsed_time||0).toFixed(0), u:'秒/种子'},
    ].map(function(s){ return '<div class="stat-card '+(s.c||'')+'"><div class="label">'+s.l+'</div><div class="value animated-num">'+s.v+'<span class="unit"> '+s.u+'</span></div></div>'; }).join('');

    // ---------- 奖励曲线：原始（淡色）+ 50回合平滑（加粗+填充）+ 误差带（合并格式） ----------
    var rwSmooth = smoothData(rewards, 50);
    var rwSmLabels = smoothLabels(rwSmooth, 50);
    var rwDatasets = [
        {
            label: '原始奖励',
            data: rewards.length > 0 ? rewards : [0],
            borderColor: 'rgba(56,189,248,0.18)',
            borderWidth: 0.5,
            pointRadius: 0,
            fill: false
        },
        {
            label: '50回合平滑',
            data: rwSmooth.length > 0 ? rwSmooth : [0],
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56,189,248,0.08)',
            borderWidth: 2.2,
            pointRadius: 0,
            fill: true,
            tension: 0.15
        }
    ];
    // 合并格式：添加 ±1σ 误差带
    if (isCombined && rewardsStd && rewardsStd.length > 0) {
        var rwSmStd = smoothData(rewardsStd, 50);
        var upper = []; var lower = [];
        for (var i = 0; i < rwSmooth.length; i++) {
            upper.push(rwSmooth[i] + (rwSmStd[i] || 0));
            lower.push(rwSmooth[i] - (rwSmStd[i] || 0));
        }
        rwDatasets.push({
            label: '+1σ',
            data: upper,
            borderColor: 'transparent',
            backgroundColor: 'rgba(56,189,248,0.06)',
            pointRadius: 0,
            fill: 2
        });
        rwDatasets.push({
            label: '-1σ',
            data: lower,
            borderColor: 'transparent',
            backgroundColor: 'rgba(56,189,248,0.00)',
            pointRadius: 0,
            fill: false
        });
    }
    createOrUpdateChart('chart-reward', 'line', {
        labels: rewards.length > 0 ? rewards.map(function(_,i){return i+1;}) : [1],
        datasets: rwDatasets
    }, baseOpts);

    // ---------- 合作/背叛率：平滑 ----------
    var coopSm = smoothData(coops, 50);
    var betSm = smoothData(betrayals, 50);
    var cLen = Math.max(coopSm.length, betSm.length, 1);
    createOrUpdateChart('chart-coop', 'line', {
        labels: smoothLabels(coopSm, 50),
        datasets: [
            {
                label: '合作率',
                data: coopSm.length > 0 ? coopSm : [0],
                borderColor: '#34d399',
                backgroundColor: 'rgba(52,211,153,0.06)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            },
            {
                label: '背叛率',
                data: betSm.length > 0 ? betSm : [0],
                borderColor: '#f87171',
                borderWidth: 1.2,
                pointRadius: 0,
                fill: false
            }
        ]
    }, baseOpts);

    // ---------- BC积分（累积值，已平滑） ----------
    var bcHist = d.bc_scores_history || [];
    var bcLabels = bcHist.length > 0 ? bcHist.map(function(_,i){return i+1;}) : [1];
    var bcDatasets = [];
    if (bcHist.length > 0 && Object.keys(bcHist[0]).length > 0) {
        Object.keys(bcHist[0]).forEach(function(aid, i) {
            var rawVals = bcHist.map(function(h){return h[aid]||0;});
            var smVals = smoothData(rawVals, 30);
            bcDatasets.push({
                label: aid,
                data: smVals.length > 0 ? smVals : rawVals,
                borderColor: ['#38bdf8','#f87171','#34d399'][i%3],
                backgroundColor: ['rgba(56,189,248,0.05)','rgba(248,113,113,0.04)','rgba(52,211,153,0.05)'][i%3],
                borderWidth: 1.8,
                pointRadius: 0,
                fill: true
            });
        });
    }
    var bcMsg = (monitorMode === 'bc')
      ? 'BC 积分数据缺失 · 请重新生成 training_results_bc.json'
      : '本模式未启用区块链激励 · 无链上积分';
    createOrUpdateChart('chart-bc', 'line', {labels: bcLabels, datasets: bcDatasets},
      Object.assign({}, baseOpts, {plugins: Object.assign({}, baseOpts.plugins || {}, {emptyState:{message: bcMsg}})}));

    // ---------- Loss：100步大窗口平滑 ----------
    var losses = d.losses || [];
    var lossSm = smoothData(losses, 100);
    createOrUpdateChart('chart-loss', 'line', {
        labels: smoothLabels(lossSm, 100),
        datasets: [{
            label: 'TD-Error Loss',
            data: lossSm.length > 0 ? lossSm : [0],
            borderColor: '#fbbf24',
            backgroundColor: 'rgba(251,191,36,0.04)',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: true
        }]
    }, baseOpts);

    // 排行榜
    const lb = d.leaderboard || [];
    document.getElementById('mon-leaderboard').innerHTML = lb.length > 0
        ? lb.map((x,i) => `<tr><td>${i+1}</td><td>${x.agent_id}</td><td class="${x.score>=0?'score-pos':'score-neg'}">${(x.score||0).toFixed(1)}</td><td><span class="badge-sm ${x.score>=0?'badge-ok':'badge-err'}">${x.score>=0?'活跃':'异常'}</span></td></tr>`).join('')
        : '<tr><td colspan="4" style="color:var(--text-dim)">暂无排行榜数据</td></tr>';

    // 摘要
    document.getElementById('mon-summary').innerHTML = [
        ['总回合数', s.total_episodes||0],
        ['最近50回合均奖励', (s['avg_reward_last_50']||0).toFixed(2)],
        ['平均合作率', ((s.avg_cooperation_rate||0)*100).toFixed(1)+'%'],
        ['平均背叛率', ((s.avg_betrayal_rate||0)*100).toFixed(1)+'%'],
        ['Loss更新次数', s.total_losses||0],
        ['总训练耗时', (s.elapsed_time||0).toFixed(1)+' 秒'],
    ].map(r => `<tr><td style="color:var(--text-dim)">${r[0]}</td><td>${r[1]}</td></tr>`).join('');
}

// ===================== 对比分析 =====================
function loadComparison() {
    if (!pureData || !bcData) {
        document.getElementById('cmp-pure-metrics').innerHTML = '<div style="padding:30px;text-align:center;color:var(--text-dim)">等待数据...</div>';
        return;
    }
    const ps = (pureData && pureData.summary) || {}, bs = (bcData && bcData.summary) || {};
    const isCombined = pureData._format === 'combined' && bcData._format === 'combined';
    const pureRewards = isCombined ? (pureData.episode_rewards_mean || []) : (pureData.episode_rewards || []);
    const bcRewards = isCombined ? (bcData.episode_rewards_mean || []) : (bcData.episode_rewards || []);
    const pureStd = isCombined ? (pureData.episode_rewards_std || null) : null;
    const bcStd = isCombined ? (bcData.episode_rewards_std || null) : null;
    const improve = ps.avg_reward !== 0 ? ((bs.avg_reward-ps.avg_reward)/Math.abs(ps.avg_reward)*100) : 0;
    const improveSig = (isCombined && ps.avg_reward_ci95 && bs.avg_reward_ci95)
        ? checkSig(bs.avg_reward, bs.avg_reward_ci95, ps.avg_reward, ps.avg_reward_ci95) : null;
    // [v3.7] 公平对比：基于 env_rewards（纯环境奖励，不含BC激励）
    const pe = ps.avg_env_reward || 0, be = bs.avg_env_reward || 0;
    const envImprove = (pe !== 0 && be !== 0) ? ((Math.abs(pe) - Math.abs(be)) / Math.abs(pe) * 100) : null;

    // 指标卡片（合并格式显示 ±std）
    var fmtMetric = function(s, extra){
        var stdText = isCombined && s.avg_reward_std ? ' ±'+(s.avg_reward_std||0).toFixed(1) : '';
        return [
            {l:'平均奖励',v:(s.avg_reward||0).toFixed(1)+stdText},
            {l:'最近50回合',v:(extra||s.avg_reward_last_50||0).toFixed(1)},
            {l:'合作率',v:((s.avg_cooperation_rate||0)*100).toFixed(1)+'%'},
            {l:'训练耗时',v:(s.elapsed_time||0).toFixed(0)+'s'}
        ];
    };
    document.getElementById('cmp-pure-metrics').innerHTML = fmtMetric(ps).map(function(m){
        return '<div class="compare-metric"><div class="val" style="color:#94a3b8">'+m.v+'</div><div class="lbl">'+m.l+'</div></div>';
    }).join('');
    document.getElementById('cmp-bc-metrics').innerHTML = fmtMetric(bs).map(function(m){
        return '<div class="compare-metric"><div class="val" style="color:#38bdf8">'+m.v+'</div><div class="lbl">'+m.l+'</div></div>';
    }).join('');

    var impText = '本机运行观测：BC-MARL 提升 +'+(improve||0).toFixed(0)+'%（演示数据·非申报口径；权威口径 +28.17%，见登记簿 NR-1/NR-2）';
    if (improveSig !== null) impText += '  [' + improveSig + ']';
    // [v3.7] 环境奖励公平对比（不存在时静默跳过）
    if (envImprove !== null && !isNaN(envImprove)) {
        impText += ' | <span style="color:#fbbf24">⚖ 环境奖励提升 +'+envImprove.toFixed(0)+'% (公平对比)</span>';
    }
    document.getElementById('cmp-improve').innerHTML = impText;

    // ---------- 奖励对比：100回合大窗口平滑 + 差异阴影 ----------
    var w = Math.min(100, pureRewards.length, bcRewards.length);
    var pureSm = smoothData(pureRewards, w);
    var bcSm = smoothData(bcRewards, w);
    var smLabels = smoothLabels(pureSm.length > bcSm.length ? pureSm : bcSm, w);

    // 差异阴影：Pure下方到BC之间填充（可视化提升幅度）
    var diffMin = [], diffMax = [];
    for (var i = 0; i < Math.min(pureSm.length, bcSm.length); i++) {
        diffMin.push(Math.min(pureSm[i], bcSm[i]));
        diffMax.push(Math.max(pureSm[i], bcSm[i]));
    }

    createOrUpdateChart('chart-cmp-reward', 'line', {
        labels: smLabels,
        datasets: [
            {
                label: '差异区间',
                data: diffMin,
                backgroundColor: 'rgba(56,189,248,0.12)',
                borderColor: 'transparent',
                pointRadius: 0,
                fill: '+1'
            },
            {
                label: '',
                data: diffMax,
                backgroundColor: 'rgba(56,189,248,0.12)',
                borderColor: 'transparent',
                pointRadius: 0,
                fill: '-1'
            },
            {
                label: 'Pure MARL',
                data: pureSm,
                borderColor: '#94a3b8',
                borderWidth: 2,
                pointRadius: 0,
                fill: false,
                borderDash: [6,3]
            },
            {
                label: 'BC-MARL',
                data: bcSm,
                borderColor: '#38bdf8',
                borderWidth: 2.8,
                pointRadius: 0,
                fill: false
            },
            {
                label: 'BC均值 -45.0',
                data: Array(smLabels.length).fill(bs.avg_reward || 0),
                borderColor: 'rgba(56,189,248,0.3)',
                borderWidth: 1,
                borderDash: [3,6],
                pointRadius: 0,
                fill: false
            }
        ]
    }, baseOpts);

    // ---------- 合作率对比 ----------
    var pCoopSm = smoothData(pureData.cooperation_rates||[], 50);
    var bCoopSm = smoothData(bcData.cooperation_rates||[], 50);
    createOrUpdateChart('chart-cmp-coop', 'line', {
        labels: smoothLabels(pCoopSm.length > bCoopSm.length ? pCoopSm : bCoopSm, 50),
        datasets: [
            {
                label: 'Pure 合作率',
                data: pCoopSm.length > 0 ? pCoopSm : [0],
                borderColor: '#94a3b8',
                borderWidth: 1.5,
                pointRadius: 0,
                borderDash: [6,3],
                fill: false
            },
            {
                label: 'BC 合作率',
                data: bCoopSm.length > 0 ? bCoopSm : [0],
                borderColor: '#34d399',
                backgroundColor: 'rgba(52,211,153,0.06)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            }
        ]
    }, baseOpts);

    // ---------- 奖励分布柱状图 ----------
    createOrUpdateChart('chart-cmp-dist', 'bar', {
        labels: ['全程平均', '最近50回合'],
        datasets: [
            {label:'Pure MARL',data:[ps.avg_reward, ps.avg_reward_last_50],backgroundColor:'rgba(148,163,184,0.45)',borderColor:'#94a3b8',borderWidth:1,borderRadius:4},
            {label:'BC-MARL',data:[bs.avg_reward, bs.avg_reward_last_50],backgroundColor:'rgba(56,189,248,0.55)',borderColor:'#38bdf8',borderWidth:1,borderRadius:4}
        ]
    }, baseOpts);
}

// ===================== 三模式对比 =====================
function loadTriComparison() {
    const ps = pureData?.summary || {};
    const bs = bcData?.summary || {};
    const ss = selfishData?.summary || {};
    const hasSelfish = selfishData !== null;

    // 指标卡片
    function metricsFor(s, color) {
        return [
            {l:'平均奖励', v:(s.avg_reward||0).toFixed(1), c:color},
            {l:'最近50回合', v:(s.avg_reward_last_50||0).toFixed(1), c:color},
            {l:'合作率', v:((s.avg_cooperation_rate||0)*100).toFixed(1)+'%', c:'#34d399'},
        ].map(function(m){ return '<div class="compare-metric"><div class="val" style="color:'+m.c+'">'+m.v+'</div><div class="lbl">'+m.l+'</div></div>'; }).join('');
    }

    document.getElementById('tri-pure-metrics').innerHTML = metricsFor(ps, '#94a3b8');
    document.getElementById('tri-bc-metrics').innerHTML = metricsFor(bs, '#38bdf8');
    document.getElementById('tri-selfish-metrics').innerHTML = hasSelfish
        ? metricsFor(ss, '#f87171')
        : '<div style="padding:20px;text-align:center;color:var(--text-dim)">训练中...</div>';

    // ---------- 三模式奖励曲线：100回合大窗口平滑 ----------
    var sw = 100;
    var pureR = smoothData(pureData?.episode_rewards||[], sw);
    var bcR = smoothData(bcData?.episode_rewards||[], sw);
    var selfishR = smoothData(selfishData?.episode_rewards||[], sw);

    var datasets = [];
    if (pureR.length > 0) datasets.push({label:'Pure MARL',data:pureR,borderColor:'#94a3b8',borderWidth:2,pointRadius:0,borderDash:[6,3],fill:false});
    if (bcR.length > 0) datasets.push({label:'BC-MARL',data:bcR,borderColor:'#38bdf8',borderWidth:2.8,pointRadius:0,fill:false});
    if (selfishR.length > 0) datasets.push({label:'Selfish',data:selfishR,borderColor:'#f87171',borderWidth:1.8,pointRadius:0,borderDash:[4,4],fill:false});

    var maxLen = 1;
    for (var d = 0; d < datasets.length; d++) {
        if (datasets[d].data.length > maxLen) maxLen = datasets[d].data.length;
    }

    createOrUpdateChart('chart-tri-reward', 'line', {
        labels: Array.from({length:maxLen}, function(_,i){return i+sw;}),
        datasets: datasets.length > 0 ? datasets : [{label:'等待数据',data:[0],borderColor:'#64748b'}]
    }, baseOpts);

    // ---------- 合作率对比 ----------
    var pCoopSm = smoothData(pureData?.cooperation_rates||[], 50);
    var bCoopSm = smoothData(bcData?.cooperation_rates||[], 50);
    var sCoopSm = smoothData(selfishData?.cooperation_rates||[], 50);
    var coopDatasets = [];
    if (pCoopSm.length > 0) coopDatasets.push({label:'Pure',data:pCoopSm,borderColor:'#94a3b8',borderWidth:1.5,pointRadius:0,borderDash:[6,3],fill:false});
    if (bCoopSm.length > 0) coopDatasets.push({label:'BC',data:bCoopSm,borderColor:'#34d399',borderWidth:2,pointRadius:0,fill:true,backgroundColor:'rgba(52,211,153,0.06)'});
    if (sCoopSm.length > 0) coopDatasets.push({label:'Selfish',data:sCoopSm,borderColor:'#f87171',borderWidth:1.2,pointRadius:0,borderDash:[4,4],fill:false});

    createOrUpdateChart('chart-tri-coop', 'line', {
        labels: smoothLabels(coopDatasets.length>0 ? coopDatasets[0].data : [0], 50),
        datasets: coopDatasets.length > 0 ? coopDatasets : [{label:'等待数据',data:[0],borderColor:'#64748b'}]
    }, baseOpts);

    // ---------- 奖励分布柱状图 ----------
    createOrUpdateChart('chart-tri-dist', 'bar', {
        labels: ['全程平均', '最近50回合'],
        datasets: [
            {label:'Pure',data:[ps.avg_reward||0, ps.avg_reward_last_50||0],backgroundColor:'rgba(148,163,184,0.4)',borderColor:'#94a3b8',borderWidth:1,borderRadius:4},
            {label:'BC',data:[bs.avg_reward||0, bs.avg_reward_last_50||0],backgroundColor:'rgba(56,189,248,0.5)',borderColor:'#38bdf8',borderWidth:1,borderRadius:4},
            ...(hasSelfish ? [{label:'Selfish',data:[ss.avg_reward||0, ss.avg_reward_last_50||0],backgroundColor:'rgba(248,113,113,0.4)',borderColor:'#f87171',borderWidth:1,borderRadius:4}] : [])
        ]
    }, baseOpts);
}

// ===================== 区块链 =====================
function loadBlockchain() {
    const d = bcData || pureData || {};
    const config = d.config || {};
    const bcScores = d.bc_scores_final || {};
    document.getElementById('bc-stats').innerHTML = [
        {l:'链上积分(agent_0)', v:(bcScores.agent_0||0).toFixed(0), c:'accent'},
        {l:'链上积分(agent_1)', v:(bcScores.agent_1||0).toFixed(0), c:'accent2'},
        {l:'链上积分(agent_2)', v:(bcScores.agent_2||0).toFixed(0), c:'success'},
    ].map(s => `<div class="stat-card ${s.c}"><div class="label">${s.l}</div><div class="value animated-num">${s.v}</div></div>`).join('');

    document.getElementById('bc-identity').innerHTML = [0,1,2].map(i =>
        `<tr><td>agent_${i}</td><td style="font-family:monospace;font-size:0.75rem;color:var(--text-dim)">ECDSA:secp256r1:agent_${i}</td><td>SHA256+ECDSA</td><td><span class="badge-sm badge-ok">已注册</span></td><td>1</td></tr>`
    ).join('');

    document.getElementById('bc-params').innerHTML = [
        ['共识算法','CW-PBFT（贡献加权PBFT）'],
        ['容错节点数','f = floor((n-1)/2) = 0'],
        ['贡献权重','task=0.40, coop=0.35, compliance=0.25'],
        ['投票阈值','≥ 2/3 权重同意即确认'],
        ['惩罚等级','警告(10) → 降权(30) → 封禁(50)'],
        ['基础奖励','10.0'],
        ['lambda权重',config.lambda_weight||0.1],
        ['主节点轮换','每10个区块轮换一次'],
    ].map(r => `<tr><td style="color:var(--text-dim)">${r[0]}</td><td>${r[1]}</td></tr>`).join('');

    // 积分历史
    const bcHist = d.bc_scores_history || [];
    var bchLabels = bcHist.length > 0 ? bcHist.map(function(_,i){return i+1;}) : [1];
    var bchDatasets = [];
    if (bcHist.length > 0 && Object.keys(bcHist[0]).length > 0) {
        Object.keys(bcHist[0]).forEach(function(aid, i) {
            bchDatasets.push({
                label: aid,
                data: bcHist.map(function(h){return h[aid]||0;}),
                borderColor: ['#38bdf8','#f87171','#34d399'][i%3],
                borderWidth: 2
            });
        });
    }
    var bchMsg = (d === bcData)
      ? 'BC 积分数据缺失 · 请重新生成 training_results_bc.json'
      : '本模式未启用区块链激励 · 无链上积分';
    createOrUpdateChart('chart-bc-history', 'line', {labels: bchLabels, datasets: bchDatasets},
      Object.assign({}, baseOpts, {plugins: Object.assign({}, baseOpts.plugins || {}, {emptyState:{message: bchMsg}})}));

    // v3.4: 流水线统计面板
    const ecdsa = d.ecdsa_stats || {};
    const security = d.security_stats || {};
    const consensus = d.consensus_stats || {};
    const blkchain = d.blockchain_stats || {};
    const weights = consensus.weights || {};
    const weightEntries = Object.entries(weights);
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setVal('pl-sign-count', ecdsa.sign_count || 0);
    setVal('pl-verify-count', ecdsa.verify_count || 0);
    setVal('pl-sec-pass', security.security_pass_count || 0);
    setVal('pl-sec-fail', security.security_fail_count || 0);
    setVal('pl-chain-height', blkchain.height || 0);
    setVal('pl-total-tx', blkchain.total_transactions || 0);
    setVal('pl-consensus-count', consensus.prepare_votes || 0);
    setVal('pl-weights', weightEntries.length ? weightEntries.map(([k,v]) => k.split('_')[1] + ':' + Number(v).toFixed(2)).join(' ') : '--');
    // 更新 ECDSA 签名徽章
    setVal('ecdsa-sign-badge', ecdsa.sign_count || 0);
    // 更新 ECDSA 验签徽章
    const verifyBadge = document.getElementById('ecdsa-verify-badge');
    if (verifyBadge) setVal('ecdsa-verify-badge', ecdsa.verify_count || 0);

    // v3.8: 子组件独立统计
    const signing = d.signing_stats || {};
    const recorder = d.recorder_stats || {};
    const detector = d.detector_stats || {};
    const settlement = d.settlement_stats || {};

    // SigningService 卡片
    setVal('sc-sign-count', signing.ecdsa_sign_count || ecdsa.sign_count || 0);
    setVal('sc-verify-count', signing.ecdsa_verify_count || ecdsa.verify_count || 0);
    setVal('sc-sec-pass', signing.security_pass_count || security.security_pass_count || 0);
    setVal('sc-sec-fail', signing.security_fail_count || security.security_fail_count || 0);
    setVal('sc-sign-badge', signing.ecdsa_sign_count || ecdsa.sign_count || 0);

    // ActionRecorder 卡片
    setVal('sc-pending', recorder.pending_actions || 0);
    setVal('sc-tx-count', recorder.tx_count || blkchain.total_transactions || 0);
    setVal('sc-tx-badge', recorder.tx_count || blkchain.total_transactions || 0);

    // CooperationDetector 卡片
    setVal('sc-coop-agents', detector.episode_coop_agents || 0);
    setVal('sc-coop-badge', detector.episode_coop_agents || 0);
    const lastStepCoop = detector.last_step_coop || {};
    const coopTrue = Object.values(lastStepCoop).filter(v => v === true).length;
    const coopTotal = Object.values(lastStepCoop).filter(v => v !== null && v !== undefined).length;
    setVal('sc-coop-rate', coopTotal > 0 ? (coopTrue / coopTotal * 100).toFixed(0) + '%' : '--');

    // SettlementCoordinator 卡片
    setVal('sc-lambda', settlement.lambda_weight || 0.10);
    setVal('sc-settle-badge', settlement.lambda_weight ? 'λ=' + Number(settlement.lambda_weight).toFixed(2) : 'λ');
    setVal('sc-lambda-display', settlement.lambda_weight ? 'λ=' + Number(settlement.lambda_weight).toFixed(2) : 'λ=0.10');

    // Per-agent 签名/合作状态
    const bcScoresFinal = settlement.bc_scores || {};
    const bcRewards = settlement.bc_rewards || {};
    for (let i = 0; i < 3; i++) {
        const aid = 'agent_' + i;
        const signCount = signing.ecdsa_sign_count ? Math.round(signing.ecdsa_sign_count / 3) : 0;
        const coopStatus = lastStepCoop[aid] === true ? '✓合作' : (lastStepCoop[aid] === false ? '✗背叛' : '—中性');
        const bcScore = (bcScoresFinal[aid] || 0).toFixed(1);
        setVal('sc-agent' + i + '-status', '签名:' + signCount + ' ' + coopStatus + ' 积分:' + bcScore);
        // 合作状态颜色
        const circle = document.getElementById('sc-agent' + i + '-circle');
        if (circle) {
            if (lastStepCoop[aid] === true) circle.setAttribute('fill', 'rgba(52,211,153,0.4)');
            else if (lastStepCoop[aid] === false) circle.setAttribute('fill', 'rgba(248,113,113,0.4)');
            else circle.setAttribute('fill', 'rgba(148,163,184,0.2)');
        }
    }
}

// ===================== 系统 =====================
function loadSystem() {
    const d = bcData || pureData || {};
    const c = d.config || {};
    document.getElementById('sys-config').innerHTML = [
        ['模式', c.mode||'未知'],['智能体数', c.n_agents||3],['目标点数', c.n_landmarks||3],
        ['总回合', c.n_episodes||'--'],['每回合步数', c.max_steps||25],
        ['随机种子', c.seed||42],['lambda权重', c.lambda_weight||0.1],
    ].map(r => `<tr><td style="color:var(--text-dim);width:160px">${r[0]}</td><td>${r[1]}</td></tr>`).join('');

    document.getElementById('sys-env').innerHTML = [
        ['环境','SimpleSpread (NumPy)'],['状态维度','18'],['观测维度','14'],['动作空间','5 (离散)'],
        ['智能体数','3'],['目标点数','3'],['最大步数','25'],
    ].map(r => `<tr><td style="color:var(--text-dim);width:140px">${r[0]}</td><td>${r[1]}</td></tr>`).join('');

    document.getElementById('sys-algo').innerHTML = [
        ['算法','IQL (Independent Q-Learning)'],['隐藏维度',c.hidden_dim||128],
        ['学习率',c.lr||0.001],['折扣因子',c.gamma||0.8],
        ['Batch Size',c.batch_size||64],['Target τ',0.01],
        ['ε 衰减',c.epsilon_decay||5000],['Replay Buffer',2500],
    ].map(r => `<tr><td style="color:var(--text-dim);width:140px">${r[0]}</td><td>${r[1]}</td></tr>`).join('');
}

// ===================== 图表工具 =====================
// ===== 空状态占位插件（C2 修复：数据为空时绘制统一占位，避免"空白图像 Bug"） =====
const emptyStatePlugin = {
  id: 'emptyState',
  afterDraw(chart, _args, opts) {
    const ds = chart.data.datasets || [];
    const empty = !ds.length || ds.every(d => !(d.data || []).length);
    if (!empty) return;
    const msg = (opts && opts.message) || '暂无数据';
    const {ctx, chartArea:{left,top,right,bottom}} = chart;
    const cx = (left+right)/2, cy = (top+bottom)/2;
    ctx.save();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#38bdf8'; ctx.font = '22px system-ui';
    ctx.fillText('⬡', cx, cy - 16);
    ctx.fillStyle = '#94a3b8'; ctx.font = '500 14px system-ui';
    ctx.fillText(msg, cx, cy + 12);
    ctx.restore();
  }
};
Chart.register(emptyStatePlugin);

function createOrUpdateChart(id, type, data, options) {
    try {
        var canvas = document.getElementById(id);
        if (!canvas) { _error('Canvas not found: #' + id); return; }
        if (typeof Chart === 'undefined') { _error('Chart.js not loaded'); return; }

        // Always destroy old chart to avoid Chart.js v4 mutation/recursion bugs
        if (charts[id]) {
            try { charts[id].destroy(); } catch(e) {}
            charts[id] = null;
        }

        var ctx = canvas.getContext('2d');
        charts[id] = new Chart(ctx, {
            type: type,
            data: data,
            options: options || {}
        });
    } catch(e) {
        _error('Chart ' + id + ': ' + e.message);
    }
}

// ===================== 启动 =====================
initAll();

// ===================== P2P 网络拓扑可视化 =====================
function drawP2PTopology(nodes, connections, activeNode) {
    try {
    const canvas = document.getElementById('p2p-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    
    // Node positions (3节点宽布局铺满画布；其他数量用圆形)
    const positions = nodes.map((_, i) => {
        if (nodes.length === 3) {
            if (i === 0) return { x: W * 0.5, y: H * 0.24 };
            if (i === 1) return { x: W * 0.22, y: H * 0.76 };
            return { x: W * 0.78, y: H * 0.76 };
        }
        const angle = (i * 2 * Math.PI / nodes.length) - Math.PI / 2;
        const r = Math.min(W, H) * 0.36;
        return { x: W/2 + r * Math.cos(angle), y: H/2 + r * Math.sin(angle) };
    });
    
    // Draw connections
    connections.forEach(([from, to]) => {
        const p1 = positions[from], p2 = positions[to];
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.strokeStyle = 'rgba(100, 180, 255, 0.25)';
        ctx.lineWidth = 2;
        ctx.stroke();
        
        // Animated pulse on connections
        const t = Date.now() / 2000;
        const pulse = 0.5 + 0.5 * Math.sin(t * Math.PI + from + to);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        const mx = p1.x + (p2.x - p1.x) * pulse;
        const my = p1.y + (p2.y - p1.y) * pulse;
        ctx.arc(mx, my, 4, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(100, 200, 255, 0.7)';
        ctx.fill();
    });
    
    // Draw nodes
    positions.forEach((pos, i) => {
        const isActive = i === activeNode;
        
        // Glow
        const gradient = ctx.createRadialGradient(pos.x, pos.y, 10, pos.x, pos.y, 40);
        if (isActive) {
            gradient.addColorStop(0, 'rgba(16, 185, 129, 0.6)');
            gradient.addColorStop(1, 'rgba(16, 185, 129, 0)');
        } else {
            gradient.addColorStop(0, 'rgba(0, 150, 255, 0.4)');
            gradient.addColorStop(1, 'rgba(0, 150, 255, 0)');
        }
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, 40, 0, Math.PI * 2);
        ctx.fillStyle = gradient;
        ctx.fill();
        
        // Node circle
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, 28, 0, Math.PI * 2);
        ctx.fillStyle = isActive ? '#34d399' : '#38bdf8';
        ctx.fill();
        ctx.strokeStyle = isActive ? '#34d399' : '#2563eb';
        ctx.lineWidth = 3;
        ctx.stroke();
        
        // Node label
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(nodes[i], pos.x, pos.y + 5);
        
        // Port label
        ctx.fillStyle = '#94a3b8';
        ctx.font = '10px monospace';
        ctx.fillText(`:${7001 + i}`, pos.x, pos.y + 50);
    });
    
    requestAnimationFrame(() => drawP2PTopology(nodes, connections, activeNode));
    } catch(e) { _error('drawP2PTopology: ' + e.message); }
}

// ===================== 共识投票可视化 =====================
let consensusDataLoaded = false;

function loadConsensus() {
    fetch('/api/consensus_votes')
        .then(r => r.json())
        .then(data => {
            // 更新统计卡片
            document.getElementById('cs-rounds').textContent = data.n_consensus_rounds || 0;
            document.getElementById('cs-txs').textContent = data.n_transactions || 0;
            const secStats = data.security_stats || {};
            document.getElementById('cs-alerts').textContent = secStats.total_alerts || 0;
            // 权重分布柱状图
            const weights = data.weights || {};
            const wLabels = Object.keys(weights);
            const wData = Object.values(weights);
            const ce = document.getElementById('consensus-empty');
            if (ce) ce.style.display = (wData && wData.length) ? 'none' : 'flex';
            const wColors = wLabels.map((_, i) => ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#6366f1'][i % 5]);

            createOrUpdateChart('chart-consensus-weights', 'bar', {
                labels: wLabels,
                datasets: [{
                    label: '投票权重',
                    data: wData,
                    backgroundColor: wColors.map(c => c + '40'),
                    borderColor: wColors,
                    borderWidth: 2,
                }]
            }, {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#888' }, grid: { color: 'rgba(0,0,0,0.06)' } },
                    x: { ticks: { color: '#aaa' }, grid: { display: false } }
                }
            });

            // 权重分布图数据来源标注：与展宽卡片对称，闭合「跨运行混排」追问。
            // 本图 weights 来自定稿主数据（broadening 默认关闭，213000 轮），
            // 与「权重展宽纪元」卡片（开启展宽＋省略故障的对照运行）不是同一次训练。
            (function () {
                const _cv = document.getElementById('chart-consensus-weights');
                if (!_cv) return;
                const _card = _cv.closest('.chart-card');
                if (!_card) return;
                if (_card.querySelector('.chart-src-note')) return; // 去重：loadConsensus 可能多次调用
                const _note = document.createElement('div');
                _note.className = 'chart-src-note';
                _note.style.cssText = 'margin-top:6px;font-size:11px;color:#888;text-align:center;';
                _note.textContent = '数据来源：定稿主数据（默认关闭展宽，213000 轮）';
                _note.title = '本图权重取自定稿主数据（broadening 默认关闭，213000 轮）；与「权重展宽纪元」卡片（开启展宽＋省略故障的对照运行）不是同一次训练';
                _card.appendChild(_note);
            })();

            // 权重展宽纪元卡片（NR-83/84 机制）
            // 语义严格区分两件事：epochs_triggered 是「机制运行的纪元数」，不等于「发生了恢复」。
            // 只有存在省略节点（omission_ratio>0）时才谈"展宽触发·活性恢复"；无省略节点时如实标注未触发。
            const wb = data.weight_broadening || null;
            const wbEl = document.getElementById('cs-broadening-epochs');
            const wbSub = document.getElementById('cs-broadening-sub');
            if (wbEl) {
                const wbSrc = data.weight_broadening_source || '—';
                const wbShare = (wb && typeof wb.honest_weight_share === 'number')
                    ? (wb.honest_weight_share * 100).toFixed(2) + '%' : '—';
                // 口径提示挂在 title（悬停可见）：诚实权重占比是「省略故障下的活性/权重配额恢复」，
                // 不是任意对手（含满参与作恶）的安全界。
                wbEl.title = '数据源：' + wbSrc
                    + '；口径：省略故障（静默不投票）下的活性 / 权重配额恢复，非任意对手安全界';
                if (wb && (wb.enabled === true || wb.enabled === undefined)) {
                    const ep = typeof wb.epochs_triggered === 'number' ? wb.epochs_triggered : 0;
                    const om = wb.omission_ratio || 0;
                    wbEl.textContent = String(ep);
                    if (om > 0) {
                        wbEl.style.color = '#10b981';
                        if (wbSub) wbSub.textContent = '省略故障 ' + (om * 100).toFixed(0) + '% · 展宽已触发 · 诚实权重占比 '
                            + wbShare + '（展宽对照运行；限省略故障下活性）';
                        // 触发脉冲动画：卡片短暂高亮
                        wbEl.animate(
                            [{ textShadow: '0 0 0px #10b981' }, { textShadow: '0 0 18px #10b981' }, { textShadow: '0 0 0px #10b981' }],
                            { duration: 1200, iterations: 2 }
                        );
                    } else {
                        wbEl.style.color = '#818cf8';
                        if (wbSub) wbSub.textContent = '已启用展宽 · 本次无省略节点（未触发恢复）';
                    }
                } else if (wb) {
                    wbEl.textContent = '未启用';
                    wbEl.style.color = '#888';
                    if (wbSub) wbSub.textContent = '本次训练未开启 weight_broadening';
                } else {
                    wbEl.textContent = '无数据';
                    wbEl.style.color = '#888';
                    if (wbSub) wbSub.textContent = '数据源未包含展宽统计';
                }
            }

            // 贡献度雷达图
            const cw = data.contribution_weights || {task_score: 0.40, cooperation_score: 0.35, compliance_score: 0.25};
            createOrUpdateChart('chart-contribution-radar', 'radar', {
                labels: ['任务完成', '合作度', '合规性'],
                datasets: [{
                    label: 'Shapley风格权重',
                    data: [cw.task_score || 0.40, cw.cooperation_score || 0.35, cw.compliance_score || 0.25],
                    backgroundColor: 'rgba(37,99,235,0.15)',
                    borderColor: '#2563eb',
                    borderWidth: 2,
                    pointBackgroundColor: '#2563eb',
                    pointRadius: 5,
                }]
            }, {
                responsive: true,
                plugins: { legend: { display: true, labels: { color: '#aaa' } } },
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 0.5,
                        ticks: { color: '#666', backdropColor: 'transparent' },
                        grid: { color: 'rgba(0,0,0,0.08)' },
                        angleLines: { color: 'rgba(0,0,0,0.08)' },
                        pointLabels: { color: '#aaa', font: { size: 13 } }
                    }
                }
            });

            consensusDataLoaded = true;
            startConsensusPhaseAnimation();
        })
        .catch(e => _error('loadConsensus: ' + e.message));
}

// ===================== 共识三阶段流转动画（增量创新 #8，自研） =====================
let consensusPhaseTimer = null;
let consensusPhaseIndex = 0;

function startConsensusPhaseAnimation() {
    if (consensusPhaseTimer) return;  // 已在运行
    const phases = ['consensus-phase-1', 'consensus-phase-2', 'consensus-phase-3'];
    const colors = ['#2563eb', '#10b981', '#f59e0b'];
    const statusEl = document.getElementById('consensus-anim-status');

    function render() {
        phases.forEach((id, i) => {
            const el = document.getElementById(id);
            if (!el) return;
            const active = (i === consensusPhaseIndex);
            el.style.borderWidth = active ? '3px' : '1px';
            el.style.boxShadow = active ? '0 0 18px ' + colors[i] + '66' : 'none';
            el.style.transform = active ? 'translateY(-3px)' : 'none';
        });
        if (statusEl) statusEl.textContent = '▶ Phase ' + (consensusPhaseIndex + 1) + ' 流转中';
    }

    render();
    consensusPhaseTimer = setInterval(() => {
        consensusPhaseIndex = (consensusPhaseIndex + 1) % phases.length;
        render();
    }, 2200);
}

// ===================== 区块浏览器 =====================
let explorerDataLoaded = false;

function loadBlockExplorer() {
    fetch('/api/block_explorer')
        .then(r => r.json())
        .then(data => {
            // 更新统计卡片
            document.getElementById('ex-height').textContent = data.total_blocks || 0;
            document.getElementById('ex-txs').textContent = data.total_transactions || 0;
            const ecdsa = data.ecdsa_stats || {};
            document.getElementById('ex-sigs').textContent = (ecdsa.sign_count || 0) + '/' + (ecdsa.verify_count || 0);
            // chain_valid: true=真实链校验通过 / false=校验失败 / null=示意数据（未做真实链校验）
            (function () {
                var cv = data.chain_valid;
                var exv = document.getElementById('ex-valid');
                if (!exv) return;
                exv.textContent = (cv === true) ? 'OK' : (cv === false ? 'FAIL' : '示意');
                exv.style.color = (cv === true) ? '#10b981' : (cv === false ? '#ef4444' : '#94a3b8');
            })();

            // 渲染区块列表
            const tbody = document.getElementById('ex-blocks-body');
            const blocks = data.blocks || [];
            const ee = document.getElementById('explorer-empty');
            if (ee) ee.style.display = (blocks && blocks.length) ? 'none' : 'flex';
            tbody.innerHTML = blocks.map(b => `
                <tr style="border-bottom:1px solid rgba(0,0,0,0.06);">
                    <td style="padding:8px;color:#2563eb;font-family:monospace;">#${b.height}</td>
                    <td style="padding:8px;color:#aaa;font-family:monospace;font-size:0.8rem;">${b.hash.substring(0,18)}...</td>
                    <td style="padding:8px;color:#666;font-family:monospace;font-size:0.8rem;">${b.prev_hash.substring(0,18)}...</td>
                    <td style="padding:8px;color:#10b981;">${b.proposer}</td>
                    <td style="padding:8px;text-align:right;color:#f59e0b;">${b.tx_count}</td>
                    <td style="padding:8px;color:#888;">${b.consensus}</td>
                </tr>
            `).join('');

            // 每块交易数趋势
            const txCounts = blocks.map(b => b.tx_count).reverse();
            const heights = blocks.map(b => b.height).reverse();
            createOrUpdateChart('chart-block-tx-trend', 'line', {
                labels: heights,
                datasets: [{
                    label: '交易数/区块',
                    data: txCounts,
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37,99,235,0.06)',
                    borderWidth: 2,
                    pointRadius: 2,
                    fill: true,
                }]
            }, {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#888' }, grid: { color: 'rgba(0,0,0,0.06)' } },
                    x: { ticks: { color: '#666', maxTicksLimit: 10 }, grid: { display: false } }
                }
            });

            // 出块者分布饼图
            const proposerCounts = {};
            blocks.forEach(b => { proposerCounts[b.proposer] = (proposerCounts[b.proposer] || 0) + 1; });
            const pLabels = Object.keys(proposerCounts);
            const pData = Object.values(proposerCounts);
            const pColors = pLabels.map((_, i) => ['#2563eb', '#10b981', '#f59e0b', '#ef4444'][i % 4]);

            createOrUpdateChart('chart-proposer-dist', 'doughnut', {
                labels: pLabels,
                datasets: [{
                    data: pData,
                    backgroundColor: pColors.map(c => c + '80'),
                    borderColor: pColors,
                    borderWidth: 2,
                }]
            }, {
                responsive: true,
                plugins: { legend: { position: 'right', labels: { color: '#aaa' } } }
            });

            explorerDataLoaded = true;
        })
        .catch(e => _error('loadBlockExplorer: ' + e.message));
}

let p2pDataLoaded = false;

function _drawP2PDemo() {
    // 演示拓扑兜底（3 节点全互联）；指标卡如实显示"未启用"，不造假数据
    const nodes = ['agent_0', 'agent_1', 'agent_2'];
    const conns = [[0,1], [0,2], [1,2]];
    const topoCanvas = document.getElementById('p2p-canvas');
    if (topoCanvas && topoCanvas.offsetWidth === 0) {
        const container = topoCanvas.parentElement;
        topoCanvas.width = container ? container.clientWidth || 800 : 800;
        topoCanvas.height = 380;
    }
    setTimeout(() => drawP2PTopology(nodes, conns, 0), 100);
    // 权重分布兜底：用共识权重（若有），否则均匀三节点
    fetch('/api/consensus_votes').then(r => r.json()).then(cv => {
        const w = (cv && cv.weights && Object.keys(cv.weights).length) ? cv.weights
                  : {agent_0: 0.3, agent_1: 0.3, agent_2: 0.3};
        setTimeout(() => drawWeightChart(w), 150);
    }).catch(() => {});
    document.getElementById('p2p-nnodes').textContent = '3（演示）';
    document.getElementById('p2p-rounds').textContent = '--';
    document.getElementById('p2p-msgs').textContent = '--';
    document.getElementById('p2p-latency').textContent = '--';
    document.getElementById('p2p-log').innerHTML =
        '<div style="color:#8a94a6;">P2P 网络未启用（模拟数据模式）。拓扑为演示布局；运行 <code>python network_demo.py</code> 启用实时网络。</div>';
}

function loadP2PData() {
    // Try to fetch P2P network stats from API
    fetch('/api/p2p_stats')
        .then(r => r.json())
        .then(data => {
            if (!data.n_nodes) {
                // 模拟数据模式（p2p_enabled=false, n_nodes=0）：API 正常返回但无节点数据，
                // 不渲染也不触发 catch → 页面全空白。兜底走演示拓扑，指标卡如实显示未启用。
                _drawP2PDemo();
                p2pDataLoaded = true;
                return;
            }
            if (data.n_nodes) {
                document.getElementById('p2p-nnodes').textContent = data.n_nodes;
                document.getElementById('p2p-rounds').textContent = data.total_consensus_rounds || '--';
                document.getElementById('p2p-msgs').textContent = (data.total_msg_sent || 0) + ' / ' + (data.total_msg_received || 0);
                document.getElementById('p2p-latency').textContent = (data.avg_latency_ms || '--') + ' ms';
                
                // Fix canvas dimensions (hidden tab causes 0-size)
                const topoCanvas = document.getElementById('p2p-canvas');
                if (topoCanvas && (topoCanvas.width === 0 || topoCanvas.offsetWidth === 0)) {
                    const container = topoCanvas.parentElement;
                    topoCanvas.width = container ? container.clientWidth || 800 : 800;
                    topoCanvas.height = 380;
                }
                
                // Draw topology
                const nodes = data.nodes ? Object.keys(data.nodes) : ['agent_0', 'agent_1', 'agent_2'];
                const conns = [];
                for (let i = 0; i < nodes.length; i++) {
                    for (let j = i + 1; j < nodes.length; j++) {
                        conns.push([i, j]);
                    }
                }
                drawP2PTopology(nodes, conns, 0);
                
                // Weight chart (Canvas 2D, no Chart.js dependency)
                if (data.weights) {
                    setTimeout(() => drawWeightChart(data.weights), 100);
                }
                
                // Message log
                if (data.recent_log && data.recent_log.length > 0) {
                    let log = '';
                    data.recent_log.slice(-20).reverse().forEach(entry => {
                        log += '<div style="padding:2px 0; border-bottom:1px solid rgba(0,0,0,0.06);">' + entry + '</div>';
                    });
                    document.getElementById('p2p-log').innerHTML = log;
                } else {
                    // 无实时消息日志时如实留空，不生成任何占位数据
                    document.getElementById('p2p-log').innerHTML =
                        '<div style="color:#8a94a6;">暂无消息日志（P2P 网络未启用时无实时消息）</div>';
                }
            }
            p2pDataLoaded = true;
        })
        .catch(() => {
            // Fallback: show static demo topology
            const nodes = ['agent_0', 'agent_1', 'agent_2'];
            const conns = [[0,1], [0,2], [1,2]];
            // Fix canvas dimensions
            const topoCanvas = document.getElementById('p2p-canvas');
            if (topoCanvas && topoCanvas.offsetWidth === 0) {
                const container = topoCanvas.parentElement;
                topoCanvas.width = container ? container.clientWidth || 800 : 800;
                topoCanvas.height = 380;
            }
            setTimeout(() => drawP2PTopology(nodes, conns, 0), 100);
            document.getElementById('p2p-log').innerHTML = '<div style="color:#556;">P2P网络未启动。运行 python network_demo.py 查看实时拓扑。</div>';
        });
}

function drawWeightChart(weights) {
    try {
        const canvas = document.getElementById('p2p-weight-chart');
        if (!canvas) { _error('P2P weight canvas not found'); return; }
        
        // Fix dimensions (canvas may be 0-size in hidden tab)
        const container = canvas.parentElement;
        const cw = container ? container.clientWidth : 0;
        if (cw > 0 && (canvas.width === 0 || canvas.width < 100)) {
            canvas.width = cw;
            canvas.height = 380;
        }
        if (!canvas.width || canvas.width < 100) {
            canvas.width = 400;
            canvas.height = 380;
        }
        
        const ctx = canvas.getContext('2d');
        const W = canvas.width, H = canvas.height;
        ctx.clearRect(0, 0, W, H);
        
        // Background
        ctx.fillStyle = 'rgba(8,16,32,0.8)';
        ctx.fillRect(0, 0, W, H);
        
        const keys = Object.keys(weights);
        const values = Object.values(weights).map(v => (typeof v === 'number' && !isNaN(v)) ? v : 0);
        if (keys.length === 0) {
            ctx.fillStyle = '#556';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('暂无权重数据', W/2, H/2);
            return;
        }
        const maxVal = Math.max(...values, 1.5);
        const barW = Math.max(20, (W - 80) / keys.length - 20);
        
        // Helper: manual rounded rect
        function fillRoundRect(ctx, x, y, w, h, r) {
            r = Math.min(r, w/2, h/2);
            ctx.beginPath();
            ctx.moveTo(x + r, y);
            ctx.lineTo(x + w - r, y);
            ctx.arcTo(x + w, y, x + w, y + r, r);
            ctx.lineTo(x + w, y + h - r);
            ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
            ctx.lineTo(x + r, y + h);
            ctx.arcTo(x, y + h, x, y + h - r, r);
            ctx.lineTo(x, y + r);
            ctx.arcTo(x, y, x + r, y, r);
            ctx.closePath();
            ctx.fill();
        }
        
        keys.forEach((k, i) => {
            const x = 60 + i * (barW + 40);
            const h = Math.max(2, (values[i] / maxVal) * (H - 100));
            const y = H - 60 - h;
            
            // Bar with gradient
            const gradient = ctx.createLinearGradient(x, y, x, H - 60);
            gradient.addColorStop(0, '#0af');
            gradient.addColorStop(1, '#036');
            ctx.fillStyle = gradient;
            fillRoundRect(ctx, x, y, barW, h, 4);
            
            // Value label
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 14px monospace';
            ctx.textAlign = 'center';
            ctx.fillText((Number(values[i]) || 0).toFixed(2), x + barW/2, y - 10);
            
            // Name label
            ctx.fillStyle = '#94a3b8';
            ctx.font = '12px monospace';
            ctx.fillText(k, x + barW/2, H - 40);
        });
        
        // Axes
        ctx.strokeStyle = '#334';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(40, H - 60);
        ctx.lineTo(W - 20, H - 60);
        ctx.stroke();
    } catch(e) {
        _error('drawWeightChart: ' + e.message);
    }
}

// ===================== 攻防演示 =====================
let attackInjected = false;

function loadAttackPanel() {
    // 交互式演示：进入页面只展示引导文案，攻击注入由用户点击触发
    //（原先首次进入自动 injectAttack('all')，导致未点击就显示"攻击注入完成"）
    if (!attackInjected) {
        const status = document.getElementById('attack-status');
        if (status) {
            status.innerHTML = '<div style="padding:12px 16px;background:rgba(37,99,235,0.08);border:1px solid rgba(37,99,235,0.3);border-radius:8px;color:#1e3a8a;font-size:0.9rem;">'
                + '👆 点击上方任一攻击按钮（或 ⚡ 一键注入全部）开始攻防演示，实时对比无区块链基线与 MARL-ECDSA 防护的拦截效果。</div>';
        }
        const results = document.getElementById('attack-results');
        if (results) results.innerHTML = '';
    }
}

async function injectAttack(type) {
    const status = document.getElementById('attack-status');
    const results = document.getElementById('attack-results');
    const btnRow = document.getElementById('attack-btn-row');
    status.textContent = '⏳ 正在注入攻击并验证区块链防护...';
    status.style.color = '#f59e0b';
    btnRow.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
        const resp = await fetch('/api/attack/inject?type=' + encodeURIComponent(type));
        const data = await resp.json();
        if (data.error) { status.textContent = '❌ ' + data.error; return; }
        attackInjected = true;
        status.textContent = '✅ 攻击注入完成，防护结果如下';
        status.style.color = '#10b981';
        renderAttackResult(data);
    } catch(e) {
        status.textContent = '❌ 请求失败: ' + e.message;
        status.style.color = '#ef4444';
    } finally {
        btnRow.querySelectorAll('button').forEach(b => b.disabled = false);
    }
}

const ATTACK_NAMES = {
    'observation_forgery': '观测伪造攻击',
    'message_tampering': '消息篡改攻击',
    'replay_attack': '重放攻击',
    'byzantine_primary': '主节点故障',
    'sybil_attack': '女巫/Sybil 攻击',
    'k_reuse_attack': 'k 值重用攻击',
    'long_range_attack': '长程攻击'
};

function renderAttackResult(data) {
    const container = document.getElementById('attack-results');
    const list = data.attack_type === 'all' ? data.results : [data];
    let html = '';
    list.forEach(r => {
        const name = ATTACK_NAMES[r.attack_type] || r.attack_type;
        const noBc = r.no_bc || {};
        const withBc = r.with_bc || {};
        const noBcOk = !!noBc.attack_successful;
        const withBcOk = !!withBc.attack_successful;
        const defended = noBcOk && !withBcOk;

        let detailsHtml = '';
        const detailKeys = Object.keys(withBc).filter(k => !['attack_successful', 'description'].includes(k));
        detailKeys.forEach(k => {
            const v = withBc[k];
            const vStr = (typeof v === 'object') ? JSON.stringify(v) : String(v);
            detailsHtml += `<div style="display:flex;justify-content:space-between;gap:12px;padding:4px 0;font-size:0.8rem;border-bottom:1px solid rgba(0,0,0,0.06);">
                <span style="color:#8899aa;">${k}</span><span style="color:#e2e8f0;font-family:monospace;text-align:right;">${vStr}</span></div>`;
        });

        html += `
        <div class="chart-card full" style="padding:20px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
                <h3 style="margin:0;">${name}</h3>
                <span class="badge ${defended ? 'badge-green' : 'badge-red'}" style="font-size:0.85rem;">${defended ? '🛡 已拦截' : '⚠ 未拦截'}</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div style="background:rgba(255,107,107,0.08);border:1px solid rgba(255,107,107,0.25);border-radius:10px;padding:14px;">
                    <div style="font-size:0.85rem;color:#ff8a8a;margin-bottom:6px;">❌ 无区块链基线</div>
                    <div style="font-size:1.1rem;font-weight:700;color:#ef4444;margin-bottom:6px;">${noBcOk ? '攻击成功' : '—'}</div>
                    <div style="font-size:0.85rem;color:#aab8c8;line-height:1.6;">${noBc.description || ''}</div>
                </div>
                <div style="background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.25);border-radius:10px;padding:14px;">
                    <div style="font-size:0.85rem;color:#5eead4;margin-bottom:6px;">✅ MARL-ECDSA 区块链防护</div>
                    <div style="font-size:1.1rem;font-weight:700;color:${withBcOk ? '#ef4444' : '#10b981'};margin-bottom:6px;">${withBcOk ? '攻击成功' : '攻击被拦截'}</div>
                    <div style="font-size:0.85rem;color:#aab8c8;line-height:1.6;">${withBc.description || ''}</div>
                </div>
            </div>
            ${detailsHtml ? `<div style="margin-top:12px;background:rgba(255,255,255,0.03);border-radius:8px;padding:10px 14px;">${detailsHtml}</div>` : ''}
        </div>`;
    });
    container.innerHTML = html;
}
