"""
可视化模块
"""
from .dashboard import start_dashboard, update_data

# plot_results 延迟导入（避免启动时加载 matplotlib）
__all__ = [
    'start_dashboard', 'update_data',
    'generate_all_plots', 'plot_training_curve', 'plot_cooperation_rate',
]


def __getattr__(name):
    if name in ('generate_all_plots', 'plot_training_curve', 'plot_cooperation_rate'):
        from .plot_results import generate_all_plots, plot_training_curve, plot_cooperation_rate
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
