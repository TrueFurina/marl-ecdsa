"""
Markdown → PDF 转换脚本（竞赛提交格式）

将竞赛文档（设计报告、测试报告等）从 Markdown 转换为带样式的 HTML，
可通过浏览器打印为 PDF。

用法:
  python convert_to_pdf.py <input.md> [output.html]
  python convert_to_pdf.py --all  # 转换所有竞赛文档
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import sys
import os
from pathlib import Path

import markdown

BASE_DIR = Path(__file__).parent
SUBMISSION_DIR = BASE_DIR.parent / 'competition_submission'

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
@page {{
  size: A4;
  margin: 2cm;
}}
body {{
  font-family: "Microsoft YaHei", "Noto Sans SC", "SimSun", sans-serif;
  font-size: 12pt;
  line-height: 1.8;
  color: #333;
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
}}
h1 {{
  font-size: 20pt;
  color: #1a1a1a;
  border-bottom: 2px solid #333;
  padding-bottom: 10px;
  margin-top: 30px;
  page-break-before: auto;
}}
h1:first-of-type {{
  page-break-before: avoid;
}}
h2 {{
  font-size: 16pt;
  color: #2c2c2c;
  border-bottom: 1px solid #aaa;
  padding-bottom: 5px;
  margin-top: 25px;
  page-break-after: avoid;
}}
h3 {{
  font-size: 14pt;
  color: #444;
  margin-top: 20px;
  page-break-after: avoid;
}}
h4 {{
  font-size: 12pt;
  color: #555;
  margin-top: 15px;
}}
p {{
  text-align: justify;
  margin: 10px 0;
}}
table {{
  border-collapse: collapse;
  width: 100%;
  margin: 15px 0;
  font-size: 11pt;
  page-break-inside: avoid;
}}
th, td {{
  border: 1px solid #888;
  padding: 6px 10px;
  text-align: left;
}}
th {{
  background-color: #f0f0f0;
  font-weight: bold;
}}
tr:nth-child(even) {{
  background-color: #fafafa;
}}
code {{
  font-family: "Consolas", "Courier New", monospace;
  background-color: #f5f5f5;
  padding: 2px 4px;
  border-radius: 3px;
  font-size: 10.5pt;
}}
pre {{
  background-color: #f5f5f5;
  border: 1px solid #ddd;
  border-radius: 5px;
  padding: 12px;
  overflow-x: auto;
  font-size: 10.5pt;
  line-height: 1.5;
  page-break-inside: avoid;
}}
pre code {{
  background-color: transparent;
  padding: 0;
}}
blockquote {{
  border-left: 4px solid #4a90d9;
  margin: 15px 0;
  padding: 10px 20px;
  background-color: #f9f9f9;
  color: #666;
}}
ul, ol {{
  margin: 10px 0;
  padding-left: 30px;
}}
li {{
  margin: 5px 0;
}}
a {{
  color: #4a90d9;
  text-decoration: none;
}}
hr {{
  border: none;
  border-top: 1px solid #ccc;
  margin: 20px 0;
}}
strong {{
  color: #1a1a1a;
}}
@media print {{
  body {{
    max-width: none;
    padding: 0;
  }}
  h1, h2, h3 {{
    page-break-after: avoid;
  }}
  table, pre {{
    page-break-inside: avoid;
  }}
}}
</style>
</head>
<body>
{content}
</body>
</html>"""


def convert_md_to_html(input_path, output_path=None):
    """将Markdown文件转换为带样式的HTML"""
    input_path = Path(input_path)
    if not input_path.exists():
        print(f"文件不存在: {input_path}")
        return False

    with open(input_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # Markdown扩展：表格、代码高亮、目录等
    html_body = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'toc', 'nl2br', 'sane_lists']
    )

    title = input_path.stem.replace('_', ' ')
    html = HTML_TEMPLATE.format(title=title, content=html_body)

    if output_path is None:
        output_path = input_path.with_suffix('.html')
    else:
        output_path = Path(output_path)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"转换完成: {input_path.name} -> {output_path.name}")
    return True


def convert_all():
    """转换所有竞赛文档"""
    docs = [
        '设计报告_MARL-ECDSA共识链——面向协作多智能体的可信共识与激励机制.md',
        '测试报告_MARL-ECDSA共识链——面向协作多智能体的可信共识与激励机制.md',
        'warehouse-deployment-scenario.md',
        'defense-qa-50.md',
    ]

    output_dir = SUBMISSION_DIR / 'pdf_output'
    output_dir.mkdir(exist_ok=True)

    for doc in docs:
        input_path = SUBMISSION_DIR / doc
        if input_path.exists():
            output_path = output_dir / doc.replace('.md', '.html')
            convert_md_to_html(input_path, output_path)
        else:
            print(f"跳过（不存在）: {doc}")

    print(f"\n所有HTML文件已生成在: {output_dir}")
    print("请在浏览器中打开HTML文件，使用 Ctrl+P 打印为PDF")


if __name__ == '__main__':
    if len(sys.argv) == 1:
        convert_all()
    elif sys.argv[1] == '--all':
        convert_all()
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        convert_md_to_html(input_file, output_file)
