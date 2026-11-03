"""
测试共享夹具 (Fixtures)
"""
import pytest
import os
import sys

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 脚本子系统目录：实验/演示/工具脚本迁入 scripts/ 的多个子目录后，
# 部分测试仍按顶层模块名 import（如 `import run_experiment_pipeline`、
# `import launch_dashboard`、`import network_demo` 等），会导致单文件执行时
# ModuleNotFoundError。此处自动把 scripts/ 及其所有含 .py 的子目录加入 sys.path，
# 使"全量跑"与"单文件跑"行为一致，同时兼容后续新增子目录。
_SCRIPTS_ROOT = os.path.join(_PROJECT_ROOT, "scripts")
if os.path.isdir(_SCRIPTS_ROOT):
    _script_dirs = [_SCRIPTS_ROOT]
    for _cur, _subdirs, _files in os.walk(_SCRIPTS_ROOT):
        if "__pycache__" in _cur:
            continue
        if any(_f.endswith(".py") for _f in _files):
            _script_dirs.append(_cur)
    for _d in reversed(_script_dirs):
        if _d not in sys.path:
            sys.path.insert(0, _d)


@pytest.fixture(scope="session")
def ecdsa_utils():
    """ECDSA 工具类实例"""
    from blockchain.crypto.ecdsa_utils import ECDSAUtils
    return ECDSAUtils


@pytest.fixture(scope="function")
def key_pair(ecdsa_utils):
    """生成新的 ECDSA 密钥对 (每个测试独立)"""
    private_key, public_key = ecdsa_utils.generate_key_pair()
    return private_key, public_key


@pytest.fixture(scope="function")
def security_guard():
    """创建新的 SecurityGuard 实例"""
    from blockchain.crypto.security_guard import SecurityGuard
    return SecurityGuard()


@pytest.fixture(scope="function")
def sample_transaction():
    """创建一个示例交易"""
    from blockchain.ledger.block import Transaction
    import hashlib
    tx = Transaction(
        tx_id="",
        agent_id="agent_0",
        action={"move": "up", "position": [0.5, 0.3]},
        action_hash=hashlib.sha256(b"test_action").hexdigest(),
        timestamp=1000000,
        nonce=1,
        signature_hex="a1b2c3d4",
        tx_type="action"
    )
    tx.tx_id = tx.compute_hash()
    return tx


@pytest.fixture(scope="function")
def block_chain_instance():
    """创建区块链实例"""
    from blockchain.ledger.blockchain import Blockchain
    # R1 收紧后 stub 路径需显式开关：本 fixture 服务于链完整性/世界状态等非签名语义测试
    return Blockchain(allow_unsigned_stub=True)


@pytest.fixture(scope="function")
def signed_package(key_pair):
    """创建已签名的动作包（使用 sign_action 完整流程）"""
    private_key, public_key = key_pair
    import time
    from blockchain.crypto.ecdsa_utils import ECDSAUtils

    return ECDSAUtils.sign_action(
        agent_id="agent_0",
        private_key=private_key,
        action={"action": 2, "position": [0.5, 0.3]},
        nonce=1,
        timestamp=int(time.time() * 1000)
    )


# ── F08（2026-11-02 赛后）：G4 登录门禁时代的共享认证客户端 ──
# 六个门禁前时代写的 API 测试文件（attack_api_parametrized / dashboard_* /
# visualization_more）从不登录，G4 的 before_request 一律 401/302。
# 本助手：注册（幂等，重跑用户已存在时继续登录）+ 登录 + 提取现行 APP_CSRF
# 并包装 client 使所有 POST 自动带 X-CSRF-Token 头。
def make_auth_client(client, username):
    import re as _re

    def _csrf_of(html):
        m = _re.search(r'name="([^"]*csrf[^"]*)"[^>]*value="([^"]+)"', html)
        return (m.group(1), m.group(2)) if m else ('_csrf', '')

    f1, v1 = _csrf_of(client.get('/register').get_data(as_text=True))
    client.post('/register', data={'username': username, 'password': 'probe123abc',
                                   'confirm': 'probe123abc', f1: v1})
    f2, v2 = _csrf_of(client.get('/login').get_data(as_text=True))
    client.post('/login', data={'username': username, 'password': 'probe123abc', f2: v2})
    home = client.get('/').get_data(as_text=True)
    m3 = _re.search(r'APP_CSRF=(?:"([^"]+)"|([^;<\s]+))', home)
    token = (m3.group(1) or m3.group(2)) if m3 else ''

    class _CSRFClient:
        def __init__(self, c, t):
            self._c, self._t = c, t

        def post(self, path, **kw):
            h = {'X-CSRF-Token': self._t}
            h.update(kw.pop('headers', None) or {})
            return self._c.post(path, headers=h, **kw)

        def get(self, path, **kw):
            return self._c.get(path, **kw)

        def __getattr__(self, name):
            return getattr(self._c, name)

    return _CSRFClient(client, token)
