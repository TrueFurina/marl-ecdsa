# -*- coding: utf-8 -*-
"""Dashboard 全标签页自动质检（Playwright headless）。

单进程合并方案：Flask 服务跑 daemon 线程 + Playwright headless 逐标签页质检，
结果落盘 ``qa_report.json`` + ``qa_shots/*.png``，供人工目检与回归比对。

用法：
    python -X utf8 scripts/qa_dashboard.py            # 全量质检
    python -X utf8 scripts/qa_dashboard.py --port 9090

前置：``pip install playwright`` + ``python -m playwright install chromium``
产物：qa_report.json（机器可读）、qa_shots/（截图证据）
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SHOT_DIR = REPO_ROOT / "qa_shots"
REPORT = REPO_ROOT / "qa_report.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Dashboard 自动质检")
    ap.add_argument("--port", type=int, default=9090)
    args = ap.parse_args()

    from visualization.dashboard import start_dashboard

    threading.Thread(target=start_dashboard, kwargs={"port": args.port}, daemon=True).start()

    base = f"http://127.0.0.1:{args.port}"
    up = False
    for _ in range(30):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2)
            up = True
            break
        except Exception:
            time.sleep(1)

    QA = {"server_up": up, "tabs": {}, "console_errors": [], "pageerrors": [],
          "broadening": None, "shots": []}
    if not up:
        QA["fatal"] = "SERVER_NOT_UP_30S"
    else:
        from playwright.sync_api import sync_playwright
        SHOT_DIR.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: QA["console_errors"].append(m.text[:150]) if m.type == "error" else None)
            page.on("pageerror", lambda e: QA["pageerrors"].append(str(e)[:150]))

            page.goto(base + "/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
            QA["title"] = page.title()
            QA["landing_tabs"] = page.eval_on_selector_all(
                "#nav-tabs .nav-tab", "els => els.map(e => e.textContent.trim())")
            page.screenshot(path=str(SHOT_DIR / "01_landing.png"))
            QA["shots"].append("01_landing.png")

            tab_handles = page.query_selector_all("#nav-tabs .nav-tab")
            names = [h.text_content().strip() for h in tab_handles]
            for i, _ in enumerate(names):
                try:
                    tab_handles[i].click(force=True, timeout=3000)
                    page.wait_for_timeout(1200)
                    info = {
                        # 多选择器并集：stat-card（统计卡）/ metric-value（总览指标）
                        # / num（highlight 大数字）/ compare-metrics .metric（对比页动态卡）
                        "cards": page.eval_on_selector_all(
                            ".tab-content.active .stat-card .stat-value,"
                            " .tab-content.active .stat-card .value,"
                            " .tab-content.active .metric-value,"
                            " .tab-content.active .highlight-item .num,"
                            " .tab-content.active .compare-metrics .metric",
                            "els => els.map(e => e.textContent.trim()).slice(0,10)"),
                        "charts": page.eval_on_selector_all(".tab-content.active canvas", "els => els.length"),
                        "empty": page.eval_on_selector_all(
                            ".tab-content.active .empty-state",
                            "els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim().slice(0,50))"),
                    }
                except Exception as e:
                    info = {"error": str(e)[:100]}
                fn = f"tab_{i:02d}.png"
                try:
                    page.screenshot(path=str(SHOT_DIR / fn), timeout=5000)
                    QA["shots"].append(fn)
                except Exception:
                    pass
                QA["tabs"][f"{i}_{names[i]}"] = info

            # 共识页专项：展宽纪元卡片三态（NR-83/84 机制可视化）
            for i, n in enumerate(names):
                if "共识" in n:
                    try:
                        tab_handles[i].click(force=True, timeout=3000)
                        page.wait_for_timeout(1500)
                        QA["broadening"] = page.evaluate(
                            "() => { const el = document.getElementById('cs-broadening-epochs');"
                            " const sub = document.getElementById('cs-broadening-sub');"
                            " return el ? {value: el.textContent, color: el.style.color,"
                            " sub: sub && sub.textContent} : 'NOT_FOUND'; }")
                        page.screenshot(path=str(SHOT_DIR / "consensus_focus.png"), timeout=5000)
                        QA["shots"].append("consensus_focus.png")
                    except Exception as e:
                        QA["broadening"] = "ERR: " + str(e)[:80]
                    break

            # 攻防页点击流回归：初始干净 → 一键注入 → 结果卡出现（52c55b9 行为契约）
            try:
                for i, n in enumerate(names):
                    if "攻防" in n:
                        tab_handles[i].click(force=True, timeout=3000)
                        page.wait_for_timeout(1200)
                        break
                QA["attack_flow"] = {}
                # 初始态：不应有"攻击注入完成"
                QA["attack_flow"]["initial_clean"] = page.evaluate(
                    "() => !document.getElementById('attack-results').textContent.includes('攻击注入完成')")
                # 点击 ⚡ 一键注入全部攻击
                page.click("#btn-att-all", force=True, timeout=3000)
                page.wait_for_timeout(2500)
                QA["attack_flow"]["after_click_results"] = page.evaluate(
                    "() => (document.getElementById('attack-status')||{}).textContent?.includes('攻击注入完成') || false")
                QA["attack_flow"]["after_click_cards"] = page.evaluate(
                    "() => document.getElementById('attack-results').children.length")
                page.screenshot(path=str(SHOT_DIR / "attack_injected.png"), timeout=5000)
                QA["shots"].append("attack_injected.png")
            except Exception as e:
                QA["attack_flow"] = {"error": str(e)[:100]}

            browser.close()

    REPORT.write_text(json.dumps(QA, ensure_ascii=False, indent=1), encoding="utf-8")
    print("QA_DONE up=%s tabs=%s consoleErr=%s pageErr=%s broadening=%s" % (
        up, len(QA["tabs"]), len(QA["console_errors"]), len(QA["pageerrors"]), QA["broadening"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
