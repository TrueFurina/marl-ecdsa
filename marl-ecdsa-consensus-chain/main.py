"""
MARL-ECDSA 共识链 主入口
面向多智能体强化学习的区块链AI协同共识机制

快速启动：
    python main.py                  # 默认模式：MARL + 区块链
    python main.py --mode pure_marl  # 纯MARL对照
    python main.py --mode selfish    # 含自私智能体
    python main.py --dashboard       # 启动可视化面板
    python main.py --experiment      # 运行对比实验
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('main')


def load_config(config_path: str = None):
    """加载配置文件"""
    if config_path is None:
        config_path = ROOT_DIR / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def print_banner():
    """打印启动横幅"""
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    banner = r"""
    ╔══════════════════════════════════════════════════════════════╗
    ║     MARL-ECDSA 共识链                                       ║
    ║     面向多智能体强化学习的区块链AI协同共识机制               ║
    ║                                                              ║
    ║     核心特性：                                               ║
    ║     ✓ ECDSA 数字签名 (secp256r1 / FIPS 186-5)               ║
    ║     ✓ CW-PBFT 贡献加权共识                                  ║
    ║     ✓ 智能合约三件套（身份/激励/惩罚）                      ║
    ║     ✓ IQL 独立 Q-learning（CTDE 框架）                       ║
    ║     ✓ 双向协同：区块链⇄MARL                                 ║
    ║     ✓ 批量异步上链                                          ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def _load_config_defaults():
    """从 config.json 加载默认参数"""
    try:
        raw_config = load_config()
        bc_marl_cfg = raw_config.get('modes', {}).get('bc_marl', {})
        defaults = {
            'n_agents': bc_marl_cfg.get('n_agents', 3),
            'n_episodes': bc_marl_cfg.get('n_episodes', 500),
            'lambda_weight': bc_marl_cfg.get('lambda_weight', 0.1),
            'selfish_ratio': bc_marl_cfg.get('selfish_ratio', 0.0),
            'seed': bc_marl_cfg.get('seed', 42),
        }
        logger.info(f"[Config] 从 config.json 加载默认参数: {defaults}")
        return defaults
    except Exception as e:
        logger.warning(f"[Config] 加载 config.json 失败 ({e})，使用硬编码默认值")
        return {'n_agents': 3, 'n_episodes': 500, 'lambda_weight': 0.1, 'selfish_ratio': 0.0, 'seed': 42}


def _build_parser(config_defaults):
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description='MARL-ECDSA 共识链 — 区块链+多智能体强化学习双向协同框架',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python main.py                             # 默认训练（MARL+区块链）
  python main.py --mode pure_marl            # 纯MARL对照
  python main.py --mode selfish --selfish_ratio 0.3   # 含30%自私智能体
  python main.py --dashboard                 # 训练+实时可视化面板
  python main.py --experiment                # 运行正式对比实验
  python main.py --demo                      # 快速验证（30回合演示）
  python main.py --use-p2p                   # 启用P2P网络共识（TCP Socket）"""
    )
    parser.add_argument('--mode', type=str, default='bc_marl', choices=['pure_marl', 'bc_marl', 'selfish'])
    parser.add_argument('--use-p2p', action='store_true', help='启用P2P网络共识')
    parser.add_argument('--experiment', action='store_true', help='运行对比实验')
    parser.add_argument('--demo', action='store_true', help='快速演示（30回合）')
    parser.add_argument('--dashboard', action='store_true', help='启动可视化监控面板')
    parser.add_argument('--n_agents', type=int, default=config_defaults.get('n_agents', 3))
    parser.add_argument('--n_episodes', type=int, default=config_defaults.get('n_episodes', 500))
    parser.add_argument('--lambda_weight', type=float, default=config_defaults.get('lambda_weight', 0.1))
    parser.add_argument('--selfish_ratio', type=float, default=config_defaults.get('selfish_ratio', 0.0))
    parser.add_argument('--seed', type=int, default=config_defaults.get('seed', 42))
    parser.add_argument('--save', type=str, default='training_results.json')
    return parser


def _run_experiment_mode(args):
    """实验模式"""
    logger.info("=" * 60)
    logger.info("启动对比实验模式")
    logger.info("=" * 60)
    from experiments.run_experiment import run_experiment
    run_experiment(n_agents=args.n_agents, n_episodes=args.n_episodes, dashboard=args.dashboard)


def _run_training_mode(args):
    """标准训练模式"""
    if args.demo:
        args.n_episodes = 30
        logger.info(f"快速演示模式：{args.n_episodes} 回合")
    from train import TrainingConfig, MARLBlockchainTrainer
    config = TrainingConfig(
        n_agents=args.n_agents, n_episodes=args.n_episodes, mode=args.mode,
        lambda_weight=args.lambda_weight, selfish_ratio=args.selfish_ratio,
        seed=args.seed, use_p2p=args.use_p2p,
    )
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()
    trainer.export_results(args.save)
    try:
        trainer.cleanup()
    except Exception as e:
        logger.debug(f"资源清理异常: {e}")
    if args.dashboard:
        try:
            from visualization.dashboard import start_dashboard
            start_dashboard(stats, trainer)
        except Exception as e:
            logger.error(f"Dashboard启动失败: {e}")


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    config_defaults = _load_config_defaults()
    parser = _build_parser(config_defaults)
    args = parser.parse_args()
    print_banner()
    if args.experiment:
        _run_experiment_mode(args)
        return
    _run_training_mode(args)


if __name__ == '__main__':
    main()
