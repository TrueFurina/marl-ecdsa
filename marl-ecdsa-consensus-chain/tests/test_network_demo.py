"""
network_demo 网络演示测试（RalphLoop 原子任务 AR）
覆盖：日志级别、横幅/小节打印、协议演示、模块完整性
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import network_demo as nd

logging.basicConfig(level=logging.CRITICAL)


class TestSetupLogging:
    def test_default_info_level(self):
        """默认 verbose=False → INFO 级别"""
        nd.setup_logging(verbose=False)
        assert logging.getLogger().level <= logging.INFO

    def test_verbose_debug_level(self):
        """verbose=True → DEBUG 级别"""
        nd.setup_logging(verbose=True)
        assert logging.getLogger().level == logging.DEBUG


class TestPrintBanner:
    def test_print_banner_output(self, capsys):
        nd.print_banner()
        captured = capsys.readouterr()
        assert "MARL-ECDSA Consensus Chain" in captured.out
        assert "CW-PBFT" in captured.out

    def test_print_section_output(self, capsys):
        nd.print_section("测试小节")
        captured = capsys.readouterr()
        assert "测试小节" in captured.out


class TestShowProtocol:
    def test_show_protocol_runs(self, capsys):
        """协议演示构建消息并编码（4 字节长度前缀）"""
        nd._show_protocol()
        captured = capsys.readouterr()
        assert "msg_type" in captured.out
        assert "MessageType." in captured.out  # 枚举类型显示（str Enum）
        assert "length" in captured.out or "bytes" in captured.out

    def test_protocol_message_roundtrip(self):
        """协议演示的消息可解码（encode→decode 往返）"""
        from blockchain.network.message_protocol import MessageProtocol, MessageType
        msg = MessageProtocol.build(
            MessageType.CONSENSUS_PREPREPARE, from_node="agent_0",
            data={"block_hash": "a1b2c3d4e5f6", "voter_id": "agent_0", "weight": 1.27},
            nonce=42,
        )
        encoded = MessageProtocol.encode(msg)
        decoded = MessageProtocol.decode(encoded)
        assert decoded == msg
        assert encoded[:4].hex() == len(encoded[4:]).to_bytes(4, 'big').hex()


class TestModuleIntegrity:
    def test_demo_callable(self):
        """demo 主流程可调用（不实际运行）"""
        assert callable(nd.demo)
        assert callable(nd.main)

    def test_import_ok(self):
        """模块导入完整（含 P2PConsensusNetwork）"""
        from blockchain.network.network_consensus import P2PConsensusNetwork
        assert P2PConsensusNetwork is not None
