"""F10：私钥加密落盘 + 旧明文原地迁移 的回归/负测。
覆盖 business_service 用户私钥与 distributed_consensus 节点私钥两条曾明文存储的路径。"""
import importlib
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from visualization import business_service as biz
from visualization import distributed_consensus as dc
from blockchain.crypto.ecdsa_utils import ECDSAUtils, resolve_key_passphrase

_ENC = b"ENCRYPTED PRIVATE KEY"


def test_user_private_key_stored_encrypted_and_signs():
    old_db = biz.DB
    tmp = Path(tempfile.mkdtemp())
    biz.DB = tmp / "business.sqlite3"
    try:
        biz.init()
        with biz.conn() as db:
            key, pub = biz.key_for(db, 42)
            row = db.execute("SELECT private_pem FROM user_keys WHERE user_id=42").fetchone()
            assert _ENC in row["private_pem"].encode(), "用户私钥未加密落盘"
            # 二次读取（解密）可用且签名/验签自洽
            key2, _ = biz.key_for(db, 42)
            sig = key2.sign(b"hello", ec.ECDSA(hashes_sha256()))
            key2.public_key().verify(sig, b"hello", ec.ECDSA(hashes_sha256()))
    finally:
        biz.DB = old_db


def test_plaintext_user_key_migrated_on_read():
    old_db = biz.DB
    tmp = Path(tempfile.mkdtemp())
    biz.DB = tmp / "business.sqlite3"
    try:
        biz.init()
        # 预置一条旧版明文私钥行
        k = ec.generate_private_key(ec.SECP256R1())
        plain = k.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        pub = k.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        with biz.conn() as db:
            db.execute("INSERT INTO user_keys VALUES (?,?,?)", (7, plain, pub))
        with biz.conn() as db:
            key, _ = biz.key_for(db, 7)                 # 读旧明文（回退兼容）
            assert key.private_numbers().private_value == k.private_numbers().private_value
            row = db.execute("SELECT private_pem FROM user_keys WHERE user_id=7").fetchone()
            assert _ENC in row["private_pem"].encode(), "读取后未迁移为加密 PEM"
    finally:
        biz.DB = old_db


def test_node_private_keys_stored_encrypted():
    old = (dc.BASE, dc.CONFIG, dc.HISTORY)
    tmp = Path(tempfile.mkdtemp())
    dc.BASE = tmp / "nodes"
    dc.CONFIG = dc.BASE / "network.json"
    dc.HISTORY = dc.BASE / "epochs"
    try:
        cfg = dc.init_network()
        for peer in cfg["peers"]:
            pem = (dc.BASE / (peer["id"] + ".pem")).read_bytes()
            assert _ENC in pem, f"{peer['id']} 节点私钥未加密落盘"
            # 可用同一稳定口令解密
            ECDSAUtils.private_key_from_bytes(pem, resolve_key_passphrase())
    finally:
        dc.BASE, dc.CONFIG, dc.HISTORY = old


def hashes_sha256():
    from cryptography.hazmat.primitives import hashes
    return hashes.SHA256()
