"""assurance_common.py —— 毕设「全员保障」工程的双线保障共享库。

职责（架构文档 §3.1 / §7）：

* **口径常量**：全团队唯一真源；任何模块**禁止**手写这些字段名字面量。
* **退出码规范**：verifier / scanner / harness 统一复用。
* **防覆盖写**：``safe_write_json`` / ``safe_write_text`` —— 沿用仓库既有
  ``_safe_write_json`` 语义（同名存在则另存 ``<stem>_<时间戳>``），默认**绝不覆盖**。
* **只读读取**：``load_json`` / ``load_text`` / ``resolve_glob``。
* **路径解析**：Windows 一致性（``pathlib``、``-X utf8``、``MPLCONFIGDIR``）。
* **统计 helper**：Welch / Cohen's d / 95%CI / post-hoc 检验力，**仅依赖标准库**。
* **外置配置加载**：``load_blacklist`` / ``load_scan_targets`` —— 真名 / QQ /
  作废令牌只存在于此二文件，公开库代码内**一个明文敏感串都不许留**。

设计约束
--------
1. **被 import 时零副作用**：模块顶层不建目录、不写文件、不起子进程；所有
   副作用都发生在调用方 ``if __name__ == '__main__':`` 之后。
2. **不依赖 numpy / scipy**：仓库内 ``.venv`` 的 torch 已损坏（WinError 1114），
   系统解释器（Python 3.12）才是基准环境；因此统计函数全部用标准库实现，
   Student-t 分布经正则化不完全 Beta 函数求解，非中心 t 用数值积分。
3. 路径基准：``REPO_ROOT`` = ``marl-ecdsa-consensus-chain/``；
   ``WORKSPACE_ROOT`` = 其**父目录**（工作区根，本身不是 git 仓库）。

作者：毕设双线保障工程（自动化工具集）　　日期：2026-09-17
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    # 路径
    "REPO_ROOT", "WORKSPACE_ROOT", "RESULTS_DIR", "DELIVERABLES_DIR",
    "ASSURANCE_DIR", "CONFIG_DIR", "REPORTS_DIR", "BLACKLIST_PATH",
    "SCAN_TARGETS_PATH", "PUBLIC_CONFIG_DIR", "PUBLIC_BLACKLIST_PATH",
    "PUBLIC_SCAN_TARGETS_PATH", "REGISTRY_PATH", "MIRROR_ROOT", "THESIS_DRAFTS_DIR",
    "HELD_DRAFTS_DIR", "MPL_CACHE_DIR",
    # 口径
    "PRIMARY_FIELD", "SECONDARY_FIELD", "TOTAL_FIELD", "COOP_ALL_FIELD",
    "COOP_LAST50_EXPR", "ENV_REWARD_ARRAY", "TOTAL_INCL_BC_FIELDS",
    "ENV_EXCL_BC_FIELDS",
    # 退出码 / 严重度
    "EXIT_OK", "EXIT_FAIL", "EXIT_USAGE", "EXIT_DATA_MISSING", "EXIT_STRICT_PENDING",
    "SEV_BLOCK", "SEV_WARN", "SEV_SNAPSHOT", "SEV_INFO",
    # 工具
    "get_logger", "now_iso", "slug_ts", "load_json", "load_text",
    "safe_write_json", "safe_write_text", "resolve_glob", "navigate",
    "extract_field", "parse_result_name", "iter_files",
    # 统计
    "mean", "variance", "stdev", "welch_ttest", "cohens_d", "ci95_diff",
    "posthoc_power", "improvement_pct", "two_sample_stats", "one_sample_stats",
    "student_t_cdf", "student_t_sf", "student_t_ppf",
    # 配置
    "load_blacklist", "load_scan_targets", "rel_to_workspace",
]

# --------------------------------------------------------------------------- #
# 1. 路径基准
# --------------------------------------------------------------------------- #
#: 仓库根：scripts/ 的上一级（marl-ecdsa-consensus-chain/）
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
#: 工作区根：仓库的父目录（【CCF】区块链AI协同…/，本身不是 git 仓库）
WORKSPACE_ROOT: Path = REPO_ROOT.parent

RESULTS_DIR: Path = REPO_ROOT / "results"
DELIVERABLES_DIR: Path = WORKSPACE_ROOT / "deliverables"
ASSURANCE_DIR: Path = DELIVERABLES_DIR / "assurance"
CONFIG_DIR: Path = ASSURANCE_DIR / "config"
REPORTS_DIR: Path = ASSURANCE_DIR / "reports"
BLACKLIST_PATH: Path = CONFIG_DIR / "assurance_blacklist.json"
SCAN_TARGETS_PATH: Path = CONFIG_DIR / "scan_targets.json"
REGISTRY_PATH: Path = DELIVERABLES_DIR / "number_registry.json"
MIRROR_ROOT: Path = WORKSPACE_ROOT / "backup" / "pkg_old_src_20260917" / "results"
THESIS_DRAFTS_DIR: Path = DELIVERABLES_DIR / "thesis_drafts"
HELD_DRAFTS_DIR: Path = ASSURANCE_DIR / "held_drafts"
MPL_CACHE_DIR: Path = REPO_ROOT / ".mpl_cache"

#: 口径门禁配置的**可公开层**（入库，CI 用）——由 ``scripts/gen_assurance_config.py`` 派生。
#: 私有层（``identity`` 真名/QQ、``thesis_inbox_dir`` 本机路径）仍在 ``CONFIG_DIR``，不进 git。
#: 叠加顺序：**public 基线 → private 覆盖**。开发机结果与分层前一致；CI 里 private 缺失时 public 兜底。
PUBLIC_CONFIG_DIR: Path = REPO_ROOT / "scripts" / "assurance_config"
PUBLIC_BLACKLIST_PATH: Path = PUBLIC_CONFIG_DIR / "assurance_rules.public.json"
PUBLIC_SCAN_TARGETS_PATH: Path = PUBLIC_CONFIG_DIR / "scan_targets.public.json"

#: 双数据源（repo 为准，backup 仅作一致性镜像）——架构 §9 U-7
DATA_ROOT_DEFAULT: Path = RESULTS_DIR


def rel_to_workspace(path: os.PathLike | str) -> str:
    """把任意路径转成相对工作区根的 POSIX 风格短路径，便于写入报告。"""
    p = Path(path)
    try:
        return p.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except ValueError:
        try:
            return p.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return p.as_posix()


# --------------------------------------------------------------------------- #
# 2. 口径常量（唯一真源）
# --------------------------------------------------------------------------- #
#: 预注册主口径：末 50 回合平均**环境**奖励（**不含** BC 激励）—— NR-1
PRIMARY_FIELD: str = "summary.avg_env_reward_last_50"
#: 全程副口径：平均**环境**奖励（不含 BC）—— NR-2，必须与主口径同时报告
SECONDARY_FIELD: str = "summary.avg_env_reward"
#: 含 BC 激励的**总**奖励末 50 回合—— NR-8 作废根因；**禁止**跨 λ 横比
TOTAL_FIELD: str = "summary.avg_reward_last_50"
#: 全程平均合作率 —— NR-3（口径以登记簿 number_registry.json 为准；
#: 旧表述"22 种子下唯一显著正面证据"基于已作废的 n=22 种子口径，不得再引用）
COOP_ALL_FIELD: str = "summary.avg_cooperation_rate"
#: 末 50 回合合作率切片表达式 —— NR-4
COOP_LAST50_EXPR: str = "cooperation_rates[-50:]"
#: 环境奖励数组字段（用于 [-50:] 切片口径）
ENV_REWARD_ARRAY: str = "env_rewards"

#: 含 BC 激励的字段集合（**禁止**与 ENV_EXCL_BC_FIELDS 混算）
TOTAL_INCL_BC_FIELDS = frozenset({TOTAL_FIELD, "summary.avg_reward"})
#: 不含 BC 激励的字段集合
ENV_EXCL_BC_FIELDS = frozenset({PRIMARY_FIELD, SECONDARY_FIELD, ENV_REWARD_ARRAY})

# --------------------------------------------------------------------------- #
# 3. 退出码 / 严重度规范（架构 §4.2 / §4.3）
# --------------------------------------------------------------------------- #
EXIT_OK: int = 0               # 通过
EXIT_FAIL: int = 1             # 至少一条 FAIL / scanner 存在 blocking 命中
EXIT_USAGE: int = 2            # 用法 / IO / schema / 配置错误
EXIT_DATA_MISSING: int = 3     # data-root 不可读 / 数据文件缺失
EXIT_STRICT_PENDING: int = 4   # --strict 下存在 PENDING / PLANNED

SEV_BLOCK: str = "block"       # 阻断级（对外材料红线）
SEV_WARN: str = "warn"         # 提示级（可推导线 / 无脚注）
SEV_SNAPSHOT: str = "snapshot" # 历史快照（打标不改写）
SEV_INFO: str = "info"         # 说明性命中（定义性文档 / 声明性提及）

# --------------------------------------------------------------------------- #
# 4. 日志 / 时间戳
# --------------------------------------------------------------------------- #
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def get_logger(name: str) -> logging.Logger:
    """返回带统一格式的 logger（沿用仓库既有风格，logger 名 = 模块名）。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def now_iso() -> str:
    """当前本地时间 ISO 字符串（秒级）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def slug_ts() -> str:
    """文件名安全的时间戳 ``YYYYmmdd_HHMMSS``。"""
    return time.strftime("%Y%m%d_%H%M%S")


# --------------------------------------------------------------------------- #
# 5. 只读读取
# --------------------------------------------------------------------------- #
def load_json(path: os.PathLike | str) -> Any:
    """读取 UTF-8 JSON 文件；失败抛 ``OSError`` / ``json.JSONDecodeError``。"""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_text(path: os.PathLike | str) -> str:
    """读取文本（容错解码，绝不用 ignore 之外的策略掩盖编码错误）。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# 6. 防覆盖写（C-3：绝不覆盖已有实验数据 / 报告）
# --------------------------------------------------------------------------- #
def _unique_path(target: Path) -> Path:
    """返回一个**尚未存在**的路径：同名则加 ``_<时间戳>``，仍冲突则再加 ``_<n>``。"""
    if not target.exists():
        return target
    alt = target.with_name(f"{target.stem}_{slug_ts()}{target.suffix}")
    n = 1
    while alt.exists():
        alt = target.with_name(f"{target.stem}_{slug_ts()}_{n}{target.suffix}")
        n += 1
    return alt


def safe_write_json(
    obj: Any,
    target: os.PathLike | str,
    overwrite: bool = False,
    indent: int = 2,
) -> Path:
    """写 JSON，**默认绝不覆盖**：目标已存在且 ``overwrite=False`` 时另存
    ``<stem>_<时间戳><suffix>``（仍冲突则追加序号）。

    :param obj: 待序列化对象（``ensure_ascii=False``）。
    :param target: 目标路径。
    :param overwrite: 显式 True 才允许覆盖（对本工程数据一律保持 False）。
    :returns: 实际写入的路径。
    """
    target = Path(target)
    if not overwrite:
        orig = target
        target = _unique_path(target)
        if target != orig:
            get_logger("assurance_common").warning(
                "[保护] %s 已存在，本次另存为 %s", orig.name, target.name
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=indent, ensure_ascii=False, default=str)
        fh.write("\n")
    return target


def safe_write_text(
    text: str,
    target: os.PathLike | str,
    overwrite: bool = False,
) -> Path:
    """写文本，**默认绝不覆盖**：语义同 :func:`safe_write_json`。"""
    target = Path(target)
    if not overwrite:
        orig = target
        target = _unique_path(target)
        if target != orig:
            get_logger("assurance_common").warning(
                "[保护] %s 已存在，本次另存为 %s", orig.name, target.name
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return target


# --------------------------------------------------------------------------- #
# 7. 字段读取 / 文件名解析
# --------------------------------------------------------------------------- #
_SLICE_RE = re.compile(r"^(?P<base>[A-Za-z_][\w.]*)\[(?P<start>-?\d*):(?P<end>-?\d*)\]$")


def navigate(data: Any, dotted: str) -> Any:
    """按点路径取值，如 ``summary.avg_env_reward_last_50``。"""
    cur = data
    for key in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur[key]
        else:
            cur = getattr(cur, key)
    return cur


def extract_field(data: Any, expr: str) -> Any:
    """取字段值，支持：

    * 点路径：``summary.avg_env_reward_last_50``
    * 切片表达式：``cooperation_rates[-50:]``（返回 list）

    :raises KeyError/TypeError: 路径不存在时。
    """
    expr = expr.strip()
    m = _SLICE_RE.match(expr)
    if m:
        seq = navigate(data, m.group("base"))
        start = int(m.group("start")) if m.group("start") not in ("", None) else None
        end = int(m.group("end")) if m.group("end") not in ("", None) else None
        return list(seq[start:end])
    return navigate(data, expr)


#: 结果文件名解析规则（架构 §7.2）
_NAME_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("convergence", re.compile(r"^(?P<arm>bc_marl|pure_marl)_seed(?P<seed>\d+)\.json$")),
    ("lambda", re.compile(r"^lambda_(?P<lam>[\d.]+)_seed(?P<seed>\d+)\.json$")),
    ("adaptive", re.compile(r"^adaptive_seed(?P<seed>\d+)\.json$")),
    ("ablate_legacy", re.compile(r"^ablate_(?P<arm>\w+)_seed(?P<seed>\d+)\.json$")),
    ("ablation", re.compile(r"^(?P<arm>baseline|security|consensus|incentive)_seed(?P<seed>\d+)\.json$")),
    ("cars", re.compile(r"^bc_marl_(?P<eta>baseline|cars_[\d]+)_seed(?P<seed>\d+)\.json$")),
    ("algo", re.compile(r"^(?P<algo>iql|vdn|qmix)_(?P<arm>bc_marl|pure_marl)_seed(?P<seed>\d+)\.json$")),
)


def parse_result_name(filename: str) -> Dict[str, Any]:
    """从结果文件名解析分组元数据（arm / seed / lambda / eta / algo）。

    解析失败返回 ``{}``（调用方据此报错，绝不静默）。
    """
    base = Path(filename).name
    for kind, pat in _NAME_PATTERNS:
        m = pat.match(base)
        if m:
            info: Dict[str, Any] = {"kind": kind}
            info.update(m.groupdict())
            return info
    return {}


def resolve_glob(root: os.PathLike | str, pattern: str) -> List[Path]:
    """在 ``root`` 下按 glob 取文件，返回**排序后**的列表（确定性）。"""
    root_p = Path(root)
    if not root_p.exists():
        return []
    return sorted(Path(p) for p in root_p.glob(pattern))


# --------------------------------------------------------------------------- #
# 8. 统计 helper（仅标准库）
# --------------------------------------------------------------------------- #
def mean(xs: Sequence[float]) -> float:
    """算术平均。"""
    return sum(xs) / len(xs) if xs else float("nan")


def variance(xs: Sequence[float], ddof: int = 1) -> float:
    """样本方差（``ddof=1`` 为无偏）。"""
    n = len(xs)
    if n - ddof <= 0:
        return 0.0
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - ddof)


def stdev(xs: Sequence[float], ddof: int = 1) -> float:
    """样本标准差（``ddof=1``）。"""
    return math.sqrt(variance(xs, ddof))


# --- Student-t / 非中心 t（标准库数值实现） ------------------------------- #
_LANCZOS = (
    76.18009172947146, -86.50532032941677, 24.01409824083091,
    -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5,
)


def _gammaln(x: float) -> float:
    """自然对数 Γ(x)（Lanczos 近似，Numerical Recipes 系数）。"""
    y = x
    tmp = x + 5.5
    tmp -= (x + 0.5) * math.log(tmp)
    ser = 1.000000000190015
    for cof in _LANCZOS:
        y += 1.0
        ser += cof / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def _betacf(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 的连分式展开（Lentz 法）。"""
    maxit, eps, fpmin = 200, 3.0e-14, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        _gammaln(a + b) - _gammaln(a) - _gammaln(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(t: float, df: float) -> float:
    """Student-t 累积分布函数 P(T <= t)。"""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    ib = _betai(df / 2.0, 0.5, x)
    return 1.0 - 0.5 * ib if t > 0 else 0.5 * ib


def student_t_sf(t: float, df: float) -> float:
    """Student-t 生存函数 P(T > t)。"""
    return 1.0 - student_t_cdf(t, df)


def student_t_ppf(p: float, df: float) -> float:
    """Student-t 分位函数（二分求逆，精度 1e-10）。"""
    if not 0.0 < p < 1.0:
        raise ValueError("p 必须在 (0, 1) 内")
    lo, hi = -1.0e3, 1.0e3
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if student_t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    return 0.5 * (lo + hi)


def _norm_cdf(z: float) -> float:
    """标准正态累积分布函数。"""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _chi2_pdf(v: float, df: float) -> float:
    """卡方分布概率密度。"""
    if v <= 0.0:
        return 0.0
    k = df / 2.0
    return math.exp((k - 1.0) * math.log(v) - v / 2.0 - (k * math.log(2.0) + _gammaln(k)))


def _noncentral_t_cdf(t: float, df: float, nc: float) -> float:
    """非中心 t 累积分布（数值积分：E_V[Φ(t·√(V/df) − nc)]）。

    Simpson 法，区间 ``[0, df + 12·√(2df) + 50]``，4096 段；精度优于 1e-6。
    """
    hi = df + 12.0 * math.sqrt(2.0 * df) + 50.0
    n = 4096
    h = hi / n
    total = 0.0
    for i in range(n + 1):
        v = i * h
        w = 1.0 if i in (0, n) else (4.0 if i % 2 else 2.0)
        total += w * _norm_cdf(t * math.sqrt(v / df) - nc) * _chi2_pdf(v, df)
    return total * h / 3.0


def welch_ttest(a: Sequence[float], b: Sequence[float]) -> Dict[str, float]:
    """Welch 两样本 t 检验（不等方差）。返回 ``{"t","df","p"}``。

    样本不足（任一组 < 2）时返回 ``{"t":0,"df":0,"p":1.0,"insufficient":1}``，
    **调用方必须 fail-closed**（架构 §4.4 教训：绝不产出空壳结论）。
    """
    if len(a) < 2 or len(b) < 2:
        return {"t": 0.0, "df": 0.0, "p": 1.0, "insufficient": 1.0}
    n1, n2 = len(a), len(b)
    v1, v2 = variance(a), variance(b)
    se2 = v1 / n1 + v2 / n2
    if se2 <= 0.0:
        return {"t": 0.0, "df": 0.0, "p": 1.0, "insufficient": 1.0}
    t = (mean(a) - mean(b)) / math.sqrt(se2)
    df = se2 ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    return {"t": t, "df": df, "p": 2.0 * student_t_sf(abs(t), df)}


def cohens_d(a: Sequence[float], b: Sequence[float]) -> float:
    """Cohen's d（合并标准差，ddof=1）。方向 = mean(a) − mean(b)。

    退化情形（与 ``ci95_diff`` / ``welch_ttest`` 的约定保持一致，禁止返回 NaN 让报告不可读）：
        样本 < 2                    → nan
        合并 SD == 0 且两组均值相等   → 0.0（两组完全同分布，效应量为零）
        合并 SD == 0 但两组均值不等   → nan（数学上为 ±∞，无法给出有限效应量，显式暴露）
    典型触发场景：路线C 的 ``contribution`` 档（R≈1）与 ``std`` 档逐 seed 完全相同
    （如 40% 省略故障下两臂全为 0.0），此时效应量应为 0 而非 NaN。
    """
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return float("nan")
    sp = math.sqrt(((n1 - 1) * variance(a) + (n2 - 1) * variance(b)) / (n1 + n2 - 2))
    if sp == 0.0:
        return 0.0 if mean(a) == mean(b) else float("nan")
    return (mean(a) - mean(b)) / sp


def ci95_diff(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    """差值的 95% 置信区间（Welch 自由度）。返回 ``(lo, hi, df)``。

    退化情形（与 welch_ttest:475 保持一致，禁止抛异常）：
        样本 < 2               → (nan, nan, 0.0)
        两组方差同时为 0（se==0）→ (d, d, 0.0)，即区间退化为点估计。
        典型触发场景：CW-PBFT 与 STD 逐 seed 结果**完全相同**（IDENTICAL 档），
        此时 v1 == v2 == 0，原实现会因 Welch 自由度分母为 0 抛 ZeroDivisionError。
        df=0.0 与 welch_ttest 的退化约定一致，调用方可据此判定"不可检验"。
    """
    if len(a) < 2 or len(b) < 2:
        return (float("nan"), float("nan"), 0.0)
    n1, n2 = len(a), len(b)
    v1, v2 = variance(a), variance(b)
    se2 = v1 / n1 + v2 / n2
    if se2 <= 0.0:
        d0 = mean(a) - mean(b)
        return (d0, d0, 0.0)
    se = math.sqrt(se2)
    df = se2 ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    tc = student_t_ppf(0.975, df)
    d = mean(a) - mean(b)
    return (d - tc * se, d + tc * se, df)


def posthoc_power(a: Sequence[float], b: Sequence[float], alpha: float = 0.05) -> float:
    """两样本 t 检验的事后检验力（非中心 t，df = n1+n2−2）。"""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return float("nan")
    sp = math.sqrt(((n1 - 1) * variance(a) + (n2 - 1) * variance(b)) / (n1 + n2 - 2))
    if sp == 0.0:
        return float("nan")
    d = (mean(a) - mean(b)) / sp
    df = n1 + n2 - 2
    delta = d * math.sqrt(n1 * n2 / (n1 + n2))
    tc = student_t_ppf(1.0 - alpha / 2.0, df)
    return 1.0 - _noncentral_t_cdf(tc, df, delta)


def improvement_pct(mean_a: float, mean_b: float) -> float:
    """相对提升率 ``(mean_a − mean_b) / |mean_b| · 100``（%）。"""
    if mean_b == 0 or math.isnan(mean_b) or math.isnan(mean_a):
        return float("nan")
    return (mean_a - mean_b) / abs(mean_b) * 100.0


def two_sample_stats(a: Sequence[float], b: Sequence[float]) -> Dict[str, Any]:
    """两样本全部统计量（NR-1/2/3/4 用）。"""
    w = welch_ttest(a, b)
    lo, hi, wdf = ci95_diff(a, b)
    return {
        "mean_a": mean(a), "sd_a": stdev(a), "n_a": len(a),
        "mean_b": mean(b), "sd_b": stdev(b), "n_b": len(b),
        "welch_t": w["t"], "welch_df": w["df"], "welch_p": w["p"],
        "cohens_d": cohens_d(a, b),
        "ci95_diff": [lo, hi],
        "improvement_pct": improvement_pct(mean(a), mean(b)),
        "posthoc_power": posthoc_power(a, b),
    }


def one_sample_stats(xs: Sequence[float]) -> Dict[str, Any]:
    """单样本统计量（多臂 / 单组用）。"""
    return {"mean": mean(xs), "sd": stdev(xs), "n": len(xs)}


# --------------------------------------------------------------------------- #
# 9. 文件遍历（排除规则集中管理）
# --------------------------------------------------------------------------- #
def iter_files(
    roots: Iterable[os.PathLike | str],
    include_ext: Iterable[str],
    exclude_dirs: Iterable[str] = (),
    exclude_globs: Iterable[str] = (),
) -> Iterable[Path]:
    """遍历 ``roots`` 下扩展名在白名单内的文件，支持目录名/glob 排除。

    只读、确定性（排序输出），不跟随符号链接目录。
    """
    inc = {e.lower() for e in include_ext}
    ex_dirs = set(exclude_dirs)
    ex_globs = list(exclude_globs)
    seen: set[Path] = set()
    for root in roots:
        root_p = Path(root)
        if not root_p.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_p, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in ex_dirs)
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if p.suffix.lower() not in inc:
                    continue
                if any(p.match(g) for g in ex_globs):
                    continue
                if p in seen:
                    continue
                seen.add(p)
                yield p


# --------------------------------------------------------------------------- #
# 10. 外置配置加载
# --------------------------------------------------------------------------- #
def _deep_overlay(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """深合并两个配置字典（``over`` 优先）。

    - ``dict`` 递归合并；
    - ``list`` 取**并集**（保序去重）——规则清单只增不减，避免私有层少写一条
      就把公开层已验证的规则整体抹掉；
    - 其余类型直接覆盖。
    """
    out = dict(base)
    for k, v in over.items():
        cur = out.get(k)
        if isinstance(cur, dict) and isinstance(v, dict):
            out[k] = _deep_overlay(cur, v)
        elif isinstance(cur, list) and isinstance(v, list):
            seen: set = set()
            merged: List[Any] = []
            for item in list(cur) + list(v):
                key = (json.dumps(item, sort_keys=True, ensure_ascii=False)
                       if isinstance(item, (dict, list)) else repr(item))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
            out[k] = merged
        else:
            out[k] = v
    return out


def _load_layered(public_path: os.PathLike | str, private_path: os.PathLike | str,
                  label: str) -> Dict[str, Any]:
    """分层加载配置：**public 基线（入库，CI 可用） → private 覆盖（仓库外，可缺）**。

    两份都不存在时抛 ``FileNotFoundError``（门禁 fail-closed，不静默放行）。
    """
    pub_p, priv_p = Path(public_path), Path(private_path)
    data: Dict[str, Any] = {}
    if pub_p.exists():
        data = load_json(pub_p)
    if priv_p.exists() and priv_p.resolve() != pub_p.resolve():
        data = _deep_overlay(data, load_json(priv_p))
    if not data:
        raise FileNotFoundError(
            f"{label}配置缺失：public={pub_p}（存在={pub_p.exists()}）、"
            f"private={priv_p}（存在={priv_p.exists()}）—— 门禁 fail-closed。")
    return data


def load_blacklist(path: os.PathLike | str = BLACKLIST_PATH) -> Dict[str, Any]:
    """加载口径门禁规则表（作废令牌 / 语义规则 / 引用黑名单 / 身份串）。

    分层来源：``scripts/assurance_config/assurance_rules.public.json``（**入库**）
    + ``deliverables/assurance/config/assurance_blacklist.json``（仓库外，可选，覆盖前者）。

    ``identity``（真名 / QQ / 邮箱后缀）**只存在于私有层**：CI 里私有层缺失时该键为空，
    身份扫描自然无命中，而**作废令牌与语义规则照常生效**——这正是门禁能在 CI 里跑起来的原因。
    """
    data = _load_layered(PUBLIC_BLACKLIST_PATH, path, "口径门禁规则")
    for key in ("identity", "void_tokens", "citation_blacklist", "semantic_rules"):
        data.setdefault(key, [] if key != "identity" else {})
    return data


def load_scan_targets(path: os.PathLike | str = SCAN_TARGETS_PATH) -> Dict[str, Any]:
    """加载扫描范围配置（目录白名单 / 排除项 / 严重度标记）。分层同 ``load_blacklist``。"""
    data = _load_layered(PUBLIC_SCAN_TARGETS_PATH, path, "扫描范围")
    data.setdefault("scan_roots", ["deliverables"])
    data.setdefault("include_ext", [".md", ".txt", ".json"])
    data.setdefault("exclude_dirs", [])
    data.setdefault("exclude_globs", [])
    return data


# --------------------------------------------------------------------------- #
# 11. 便捷 import 兼容（脚本既可 `python scripts/x.py` 也可 `-m scripts.x`）
# --------------------------------------------------------------------------- #
def ensure_script_dir_on_path() -> None:
    """把本文件所在目录加入 ``sys.path``（供同目录脚本直接 import）。"""
    import sys
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


# --------------------------------------------------------------------------- #
# 12. 扫描器共享工具（供 4 个 scan_*.py 复用，避免重复实现）
# --------------------------------------------------------------------------- #
def snippet(line: str, start: int, end: int, pad: int = 40) -> str:
    """截取命中处上下文片段（用于人读报告）。"""
    a = max(0, start - pad)
    b = min(len(line), end + pad)
    return ("…" if a > 0 else "") + line[a:b].strip() + ("…" if b < len(line) else "")


def scan_text_lines(path: os.PathLike | str):
    """逐行产出 ``(行号, 行文本)``；只读、容错解码。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            yield lineno, line.rstrip("\n")


def extract_pptx_strings(path: os.PathLike | str) -> List[Tuple[str, str]]:
    """解压 PPTX（zip），返回 ``[(part_name, text)]``。

    * ``docProps/core.xml``：标题/作者/最后修改者等元数据（NFR-4 重点）。
    * 所有 ``ppt/**/*.xml``：幻灯片正文（防止正文泄漏身份）。
    纯标准库（``zipfile`` + ``re``），不依赖 python-pptx。
    """
    import zipfile
    out: List[Tuple[str, str]] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                low = name.lower()
                if not low.endswith(".xml"):
                    continue
                if not (low == "docprops/core.xml" or low.startswith("docprops/")
                        or low.startswith("ppt/") or low.startswith("xl/")
                        or low.startswith("word/")):
                    continue
                try:
                    raw = zf.read(name).decode("utf-8", errors="replace")
                except (KeyError, OSError):
                    continue
                # 去掉标签，保留文本与属性值，避免匹配到命名空间噪声
                text = re.sub(r"<[^>]+>", " ", raw)
                out.append((name, text))
    except (zipfile.BadZipFile, OSError):
        return []
    return out


def extract_pdf_strings(path: os.PathLike | str) -> List[str]:
    """从 PDF 原始字节中抽取 ``/Title`` ``/Author`` 等元数据串（NFR-4）。

    兼容两类中文编码：
    1) PDF 规范的 UTF-16BE hex 串（``/Author <FEFF4E2D...>``）；
    2) 括号串 ``(...)`` 内的 UTF-8 字节（先按 latin-1 解码再还原 UTF-8，
       避免中文姓名被解成 mojibake 而漏报）。
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return []
    found: List[str] = []
    # 1) UTF-16BE hex 串：/Author <FEFF...>
    for m in re.finditer(rb"/(Title|Author|Subject|Keywords|Creator|Producer)\s*<([0-9A-Fa-f]+)>", raw):
        key = m.group(1).decode("ascii", "replace")
        try:
            val = bytes.fromhex(m.group(2).decode("ascii")).decode("utf-16-be", errors="replace")
            found.append(f"/{key} = {val}")
        except (ValueError, UnicodeDecodeError):
            pass
    # 2) 括号串（含 latin-1→utf-8 mojibake 还原）
    text = raw.decode("latin-1", errors="replace")
    for key in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer"):
        for m in re.finditer(r"/" + key + r"\s*\(([^)]*)\)", text):
            val = m.group(1)
            try:
                val = val.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
            found.append(f"/{key} = {val}")
    return found


def extract_pdf_body(path: os.PathLike | str) -> List[Tuple[int, str]]:
    """用 pypdf 抽取 PDF **正文**文本，返回 ``[(行号, 行文本)]``。

    补齐 ``extract_pdf_strings`` 只抽元数据（/Title /Author）的缺口——pre-commit
    门禁需要扫描 PDF 正文里的作废令牌（如提交包里残留的 ``1624`` / ``40.7``）。
    纯标准库 + pypdf（已确认环境可用）；pypdf 不可用或解析失败则返回空列表。
    """
    try:
        import pypdf  # noqa: WPS433
    except ImportError:
        return []
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:
        return []
    out: List[Tuple[int, str]] = []
    ln = 0
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            continue
        for line in txt.splitlines():
            ln += 1
            out.append((ln, line))
    return out


def scanner_severity_counts(hits: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """统计各 severity 命中数与 blocking 数。"""
    counts = {SEV_BLOCK: 0, SEV_WARN: 0, SEV_SNAPSHOT: 0, SEV_INFO: 0}
    for h in hits:
        counts[h.get("severity", SEV_WARN)] = counts.get(h.get("severity", SEV_WARN), 0) + 1
    return counts


def render_scanner_markdown(report: Dict[str, Any]) -> str:
    """把 scanner 报告渲染为人读 Markdown。"""
    s = report.get("summary", {})
    lines = [
        f"# 扫描报告：{report.get('scanner')}",
        "",
        f"- 生成时间：{report.get('generated_at')}",
        f"- 扫描根：`{report.get('root')}`",
        f"- 配置：`{report.get('config_ref')}`",
        f"- 汇总：files_scanned={s.get('files_scanned')} hits={s.get('hits')} "
        f"blocking={s.get('blocking')} (block={s.get('block')} warn={s.get('warn')} "
        f"snapshot={s.get('snapshot')} info={s.get('info')})",
        "",
    ]
    if report.get("excluded"):
        lines.append(f"- 已排除：{', '.join(report['excluded'])}")
        lines.append("")
    hits = report.get("hits", [])
    if not hits:
        lines.append("**无命中。**")
        return "\n".join(lines) + "\n"
    lines += [
        "| 文件 | 行 | 命中 | 规则 | 严重度 | 上下文 | 处置建议 |",
        "|---|---|---|---|---|---|---|",
    ]
    for h in hits:
        ctx = (h.get("snippet") or "").replace("|", "\\|")[:120]
        hint = (h.get("hint") or "").replace("|", "\\|")[:120]
        lines.append(
            f"| {h.get('file')} | {h.get('line')} | `{h.get('match')}` | {h.get('rule')} "
            f"| {h.get('severity')} | {ctx} | {hint} |"
        )
    lines.append("")
    return "\n".join(lines)


def emit_scanner_report(
    report: Dict[str, Any],
    report_json: os.PathLike | str,
    overwrite: bool = False,
) -> Path:
    """写出 scanner 的 json + md 报告，返回 json 路径。"""
    pj = safe_write_json(report, report_json, overwrite=overwrite)
    safe_write_text(render_scanner_markdown(report), pj.with_suffix(".md"), overwrite=overwrite)
    return pj


def classify_path_scope(path_str: str, cfg: Dict[str, Any]) -> str:
    """把文件路径归类为 ``external`` / ``snapshot`` / ``internal``，用于 severity 分级。

    * external：对外/论文材料（thesis_drafts、毕设深度研究、README、答辩/PPT）→ block
    * snapshot：历史快照（archive/backup/_legacy/赛前/冲刺/审计/核验/复验…）→ snapshot
    * internal：其余内部文档（PRD / 架构 / 审计底稿等）→ info
    """
    p = path_str.replace("\\", "/").lower()
    for d in cfg.get("snapshot_dir_markers", []):
        dl = d.lower()
        if f"/{dl}/" in p or p.endswith(f"/{dl}") or f"/{dl}_" in p:
            return "snapshot"
    for n in cfg.get("meta_name_markers", []):
        if n.lower() in p:
            return "internal"
    for n in cfg.get("snapshot_name_markers", []):
        if n.lower() in p:
            return "snapshot"
    for m in cfg.get("external_material_markers", []):
        if m.lower() in p:
            return "external"
    return "internal"


def scope_severity(scope: str) -> str:
    """scope → 默认 severity 映射。"""
    return {"external": SEV_BLOCK, "snapshot": SEV_SNAPSHOT}.get(scope, SEV_INFO)
