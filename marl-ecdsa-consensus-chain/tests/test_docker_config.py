"""
Docker 配置完整性测试（RalphLoop 原子任务 AL）
覆盖：Dockerfile 关键指令、docker-compose 服务结构、端口/入口一致性
通过标准：新增 ≥6 项测试全过
"""
import logging
from pathlib import Path

import pytest

logging.basicConfig(level=logging.CRITICAL)

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / 'Dockerfile'
COMPOSE = ROOT / 'docker-compose.yml'


class TestDockerfile:
    def test_dockerfile_exists(self):
        assert DOCKERFILE.exists()

    def test_base_image_python312(self):
        """基础镜像 python:3.12-slim"""
        content = DOCKERFILE.read_text(encoding='utf-8')
        assert 'FROM python:3.12-slim' in content

    def test_expose_dashboard_port(self):
        """暴露 9090 仪表盘端口"""
        content = DOCKERFILE.read_text(encoding='utf-8')
        assert 'EXPOSE 9090' in content

    def test_entrypoint_main(self):
        """入口 main.py"""
        content = DOCKERFILE.read_text(encoding='utf-8')
        assert 'ENTRYPOINT ["python", "main.py"]' in content

    def test_default_cmd_demo(self):
        """默认命令 --demo（快速演示）"""
        content = DOCKERFILE.read_text(encoding='utf-8')
        assert 'CMD ["--demo"]' in content

    def test_copy_requirements_before_source(self):
        """先 COPY requirements.txt 再 COPY 源码（缓存优化）"""
        content = DOCKERFILE.read_text(encoding='utf-8')
        req_idx = content.find('COPY requirements.txt')
        src_idx = content.find('COPY . .')
        assert req_idx != -1 and src_idx != -1
        assert req_idx < src_idx

    def test_workdir_app(self):
        content = DOCKERFILE.read_text(encoding='utf-8')
        assert 'WORKDIR /app' in content


class TestDockerCompose:
    def test_compose_exists(self):
        assert COMPOSE.exists()

    def test_three_services(self):
        """三个服务：app/experiment/dashboard"""
        content = COMPOSE.read_text(encoding='utf-8')
        assert 'marl-ecdsa-app' in content
        assert 'marl-ecdsa-experiment' in content
        assert 'marl-ecdsa-dashboard' in content

    def test_services_use_same_image(self):
        """所有服务引用 marl-ecdsa-chain:latest"""
        content = COMPOSE.read_text(encoding='utf-8')
        assert content.count('marl-ecdsa-chain:latest') >= 3

    def test_dashboard_port_mapping(self):
        """仪表盘服务映射 9090"""
        content = COMPOSE.read_text(encoding='utf-8')
        assert '9090:9090' in content

    def test_compose_valid_yaml(self):
        """docker-compose.yml 可被 YAML 解析（4 服务：app/experiment/dashboard/p2p-demo）"""
        import yaml
        data = yaml.safe_load(COMPOSE.read_text(encoding='utf-8'))
        assert 'services' in data
        assert len(data['services']) == 4
        assert 'p2p-demo' in data['services']  # p2p 服务键名（profiles 为 ['p2p']）
        assert data['services']['p2p-demo'].get('profiles') == ['p2p']
