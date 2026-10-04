# -*- coding: utf-8 -*-
"""MARL-ECDSA Dashboard 单文件启动器（PyInstaller 入口）

行为：随机可用端口启动本机服务 → 自动打开浏览器 → 前台运行（Ctrl+C 退出）。
数据与页面全部内置于包内（_MEIPASS），无需安装 Python。
口径说明：权威口径接口在独立部署时回退到内置兜底值（与 number_registry.json
登记值一致），页面脚注会如实显示出处。
"""
import os
import socket
import sys
import threading
import webbrowser

# PyInstaller onefile：资源解包目录
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)


def _free_port(start=9090, end=9109):
    for p in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def main():
    from visualization.dashboard import _create_app

    app = _create_app()
    if app is None:
        print("[错误] Flask 未随包生效")
        return 1

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print("=" * 56)
    print("  MARL-ECDSA 共识链 — Dashboard 演示版")
    print(f"  正在打开浏览器: {url}  （若未自动打开请手动访问）")
    print("  Ctrl+C 退出")
    print("=" * 56)

    from werkzeug.serving import run_simple
    try:
        run_simple("127.0.0.1", port, app, use_reloader=False, use_debugger=False)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
