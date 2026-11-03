# 2026 CCF 区块链技术与创新应用竞赛 · 前端重构说明

## 设计目标

参考成熟企业管理控制台（如 Ant Design Pro 的信息架构、常规 SaaS 账号入口、卡片式指标看板）的布局逻辑，而非复制页面或使用官方商标。根据 [官方赛事章程](https://btc.ccf.org.cn/competitioncharter)，展示重点为 **技术创新、应用实用性、安全性/隐私性、可复现评估**。本系统是独立参赛作品的原型演示，并非 CCF 官方网站或报名入口。

## 页面模块

- 总览：产品定位、四大技术价值、数据口径说明、真实统计、实验对照和链上事件。
- 训练与对比：BC-MARL / Pure MARL / Selfish 实验对比与曲线。
- 贡献与激励：贡献评分、排行榜、可解释公式沙盒（非链上真实结算）。
- 链上共识：ECDSA 签名、CW-PBFT 阶段、区块浏览器。
- P2P 网络：节点拓扑、网络数据与通信日志。
- 攻防演示：攻击场景与防护反馈（受控演示环境）。
- 登录 / 注册：`/login`、`/register`；SQLite 本地账户库；`/logout`，`/api/me`。

## 启动

```bash
cd source_code
pip install -r requirements.txt
python start_dashboard.py
```

访问 `http://127.0.0.1:9090`，或 `http://127.0.0.1:9090/login`。该项目原有启动脚本与算法文件均保留。

## 身份与安全说明

- 账户信息保存在 `source_code/instance/accounts.sqlite3`（首次运行创建），不上传到大赛官网。
- Werkzeug 密码哈希、CSRF 表单校验、参数化 SQLite 查询、HttpOnly/SameSite Cookie。
- 设置环境变量 `MARL_DASHBOARD_SECRET` 可在服务器重启后保持 session 有效；未设置时每次启动生成临时随机密钥。
- 当前默认允许匿名访问公开实验看板，避免影响展示与原有接口测试；**登录不代表 API 已有访问控制**。若公开部署，必须额外实现账户权限、API 鉴权、登录限速、HTTPS、安全审计和生产级 WSGI 配置，不应直接公网暴露演示模式攻击接口。
- CCF 竞赛要求提交材料匿名：**不得在作品和截图中出现学校、教师及队员姓名**。
- 只展示实际读取的数据；不可把演示、参数推算或本地测试称为正式链上实测。

## 前端文件

- `templates/dashboard.html`：业务控制台结构、入口与矢量图标。
- `templates/auth.html`：登录注册模板。
- `static/competition-redesign.css`：比赛导向设计系统覆盖层。
- `static/auth.css`：登录注册布局。
- `static/competition-redesign.js`：账户入口状态交互。
- `visualization/dashboard.py`：本地账号路由和存储。

## 验证范围

已完成 Python 语法编译与文件结构检查。当前构建环境未安装 Flask 且无法从网络下载，未能执行 HTTP 集成测试。请在具备 requirements.txt 所需环境的机器上进行实际启动与浏览器回归测试。
