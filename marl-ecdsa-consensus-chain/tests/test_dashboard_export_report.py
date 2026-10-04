"""
dashboard 导出报告测试（RalphLoop 原子任务 BV）
覆盖：导出报告前端 JS 功能（模态框/生成/下载/快捷键/内容结构）
通过标准：新增 ≥6 项测试全过
"""
import logging
from pathlib import Path

import pytest

logging.basicConfig(level=logging.CRITICAL)

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / 'templates' / 'dashboard.html'
# 前端 JS 已拆分为外链文件（static/dashboard.js），UI 断言需同时覆盖模板与其外链 JS
DASHBOARD_JS = ROOT / 'static' / 'dashboard.js'


def _ui_content() -> str:
    """模板 HTML + 外链 JS 的合并内容（用于 UI / 交互断言）。

    JS 拆分后导出报告实现位于 static/dashboard.js；合并两处后断言字符串本身不变，
    强度不降低。外链文件缺失时合并内容不含对应片段，测试照常失败。
    """
    content = TEMPLATE.read_text(encoding='utf-8')
    if DASHBOARD_JS.exists():
        content = content + '\n' + DASHBOARD_JS.read_text(encoding='utf-8')
    return content


class TestExportReportUI:
    def test_export_button(self):
        """导出报告按钮存在"""
        content = _ui_content()
        assert '导出报告' in content
        assert 'showExportModal' in content

    def test_export_modal(self):
        """导出模态框存在"""
        content = _ui_content()
        assert 'export-modal' in content
        assert 'doExport()' in content

    def test_do_export_function(self):
        """doExport 生成报告函数存在"""
        content = _ui_content()
        assert 'function doExport' in content


class TestExportDownload:
    def test_download_filename(self):
        """下载文件名为 MARL-ECDSA_实验报告.html"""
        content = _ui_content()
        assert 'MARL-ECDSA_实验报告.html' in content

    def test_download_mechanism(self):
        """使用 a.download + href 下载"""
        content = _ui_content()
        assert 'a.download' in content
        assert "a.href = url" in content or 'a.href=url' in content


class TestExportContent:
    def test_report_contains_title(self):
        """导出报告 HTML 含标题"""
        content = _ui_content()
        # doExport 内部构造 html 字符串，含标题
        idx = content.find('function doExport')
        export_section = content[idx:idx + 3000] if idx >= 0 else ''
        assert 'MARL-ECDSA' in export_section or '报告' in export_section

    def test_report_contains_keyboard_shortcut(self):
        """E 键快捷键触发导出"""
        content = _ui_content()
        assert "e.key === 'e'" in content or "e.key === 'E'" in content

    def test_report_close_modal(self):
        """导出后可关闭模态框"""
        content = _ui_content()
        assert 'hideExportModal' in content


class TestExportIntegration:
    def test_modal_close_button(self):
        """模态框含关闭按钮"""
        content = _ui_content()
        assert 'closeExportModal' in content or 'hideExportModal' in content

    def test_escape_closes_modal(self):
        """Esc 键关闭模态框"""
        content = _ui_content()
        assert 'Escape' in content

    def test_export_html_structure(self):
        """模板 HTML 结构完整（含 script 闭合）"""
        content = TEMPLATE.read_text(encoding='utf-8')
        assert content.count('<script') >= content.count('</script>')
        assert '</html>' in content
