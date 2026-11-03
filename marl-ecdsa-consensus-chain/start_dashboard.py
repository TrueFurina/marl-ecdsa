"""启动 MARL-ECDSA V27：协作训练、贡献治理、可信共识与证据审计。"""
import sys

from visualization.dashboard import _create_app

PORT = 9090

print(f"\n{'='*60}")
print(f"  MARL-ECDSA 共识链 — V27 可信协作治理平台")
print(f"  协作训练 · 贡献治理 · 三节点可信共识 · 证据审计")
print(f"  请在浏览器中打开: http://127.0.0.1:{PORT}")
print(f"  Ctrl+C 退出")
print(f"{'='*60}\n")

app = _create_app()
if app is None:
    print("错误：请先安装Flask: pip install flask")
    sys.exit(1)

# 使用 Werkzeug run_simple 直接启动，避免 Flask app.run() 的模块发现机制
# 模块级 app=None（参见 dashboard.py）确保没有裸 Flask 实例被自动检测
from werkzeug.serving import run_simple
run_simple('127.0.0.1', PORT, app, use_reloader=False, use_debugger=False)
