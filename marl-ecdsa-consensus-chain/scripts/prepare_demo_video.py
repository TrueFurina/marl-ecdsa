"""
演示视频录制准备脚本
====================
1. 跑一轮 bc_marl 50ep 生成演示数据
2. 启动 Dashboard v3.9（端口9090）
3. 提示用户用 OBS/系统录屏录制 P 键演示模式

用法: python scripts/prepare_demo_video.py
"""
import sys
import os
import time
import logging
import threading

# 添加项目根目录到 path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def generate_demo_data():
    """跑一轮 bc_marl 50ep 生成演示数据"""
    logger.info("=" * 60)
    logger.info("步骤1: 生成演示数据 (bc_marl 50ep)")
    logger.info("=" * 60)
    
    from train import MARLBlockchainTrainer, TrainingConfig
    
    config = TrainingConfig(
        mode='bc_marl', n_episodes=50, max_steps=25,
        n_agents=3, n_landmarks=3, hidden_dim=64, lr=0.001,
        gamma=0.8, batch_size=32, epsilon_decay=500,
        lambda_weight=0.1, selfish_ratio=0.0, replay_capacity=1000,
        consensus_mode='simulated',
    )
    
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()
    s = stats.summary()
    
    logger.info(f"演示数据生成完成:")
    logger.info(f"  avg_reward = {s.get('avg_reward_per_episode', 0):.2f}")
    logger.info(f"  coop_rate  = {s.get('cooperation_rate', 0)*100:.1f}%")
    logger.info(f"  blocks     = {trainer.bridge.get_stats().get('blocks', 0)}")
    
    return trainer


def start_dashboard(trainer):
    """启动 Dashboard"""
    logger.info("=" * 60)
    logger.info("步骤2: 启动 Dashboard v3.9 (端口9090)")
    logger.info("=" * 60)
    
    from visualization.dashboard import start_dashboard as _start, update_data
    
    # 注入训练器数据
    update_data(trainer.stats, trainer)
    
    # 启动 Flask
    logger.info("Dashboard 启动中... http://127.0.0.1:9090")
    logger.info("")
    logger.info("=" * 60)
    logger.info("录屏指南:")
    logger.info("  1. 打开浏览器访问 http://127.0.0.1:9090")
    logger.info("  2. 按 P 键开启演示模式（自动轮播9标签页，6秒间隔）")
    logger.info("  3. 用 OBS / Win+G 系统录屏录制 5-8 分钟")
    logger.info("  4. 录制完成后 Ctrl+C 停止此脚本")
    logger.info("=" * 60)
    logger.info("")
    
    _start(trainer.stats, trainer, host='127.0.0.1', port=9090)


def main():
    try:
        trainer = generate_demo_data()
        start_dashboard(trainer)
    except KeyboardInterrupt:
        logger.info("\n录屏完成，Dashboard 已停止。")
    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
