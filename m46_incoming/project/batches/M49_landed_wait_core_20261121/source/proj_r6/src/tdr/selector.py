"""变体 A：用“学习得到的选择器”代替自适应轮盘赌来挑选（移除算子, 修复算子）.

做法（表格型 Q-learning，状态很小，便于讲清楚）：
  状态 s = (停滞档, 温度档, 失败类型)
    停滞档：连续多少轮没有改进（0 / 1–9 / 10–24 / ≥25）
    温度档：模拟退火进度（前 1/3 = 高温、中间 = 中温、后 1/3 = 低温）；只由 ALNS 主循环进度决定
    失败类型：已观察失败票数是否 ≥2、失败航次是否还有可继续空送的余票（共 4 类）
  动作 a = (移除算子, 修复算子) 的组合，6×2 = 12 个
  奖励 r = 原来 ALNS 的得分（全局最好 33 / 改进当前解 9 / 被接受 3 / 否则 0），再除以 33 归一化
  更新  Q(s,a) ← Q(s,a) + α·( r + γ·max_a' Q(s',a') − Q(s,a) )

训练与评价严格分开（避免“在测试环境上训练”）：
  * 训练：scripts/train_selector.py 在环境种子 101–115（与评价用的 1–10 不重叠）上跑若干回合，
    ε-greedy 探索 + 在线更新，保存 Q 表（JSON）。
  * 评价：加载 Q 表后**冻结**（不再更新），只保留小概率 ε 随机探索；
    某状态在训练中从未见过时退化为均匀随机选择（等价于不加偏好）。
基线（operator_selector="roulette"）仍是原来的普通自适应权重轮盘赌，代码路径完全不变。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

N_STAG = 4
N_TEMP = 3
N_FTYPE = 4


def stag_bucket(stagnation: int) -> int:
    if stagnation <= 0:
        return 0
    if stagnation < 10:
        return 1
    if stagnation < 25:
        return 2
    return 3


def temp_bucket(progress: float) -> int:
    return 0 if progress < 1.0 / 3 else (1 if progress < 2.0 / 3 else 2)


def failure_type(n_failed: int, has_remaining_air: bool) -> int:
    return (1 if n_failed >= 2 else 0) * 2 + (1 if has_remaining_air else 0)


class QSelector:
    def __init__(self, destroy_ops: list[str], repair_ops: list[str], eps: float = 0.05,
                 alpha: float = 0.2, gamma: float = 0.9, learn: bool = False):
        self.actions = [(d, r) for d in destroy_ops for r in repair_ops]
        self.eps = eps
        self.alpha = alpha
        self.gamma = gamma
        self.learn = learn
        self.q: dict[str, list[float]] = {}
        self.n: dict[str, list[int]] = {}
        self.n_updates = 0

    # ---- 状态编码 ----
    @staticmethod
    def key(stagnation: int, progress: float, ftype: int) -> str:
        return f"{stag_bucket(stagnation)}|{temp_bucket(progress)}|{ftype}"

    def _row(self, key: str, create: bool = False):
        if key not in self.q and create:
            self.q[key] = [0.0] * len(self.actions)
            self.n[key] = [0] * len(self.actions)
        return self.q.get(key)

    # ---- 选择 ----
    def choose(self, key: str, rng: random.Random) -> tuple[str, str, int]:
        row = self._row(key, create=self.learn)
        if row is None or rng.random() < self.eps:
            a = rng.randrange(len(self.actions))
        else:
            counts = self.n[key]
            if self.learn and min(counts) == 0:
                a = rng.choice([i for i, c in enumerate(counts) if c == 0])   # 先把每个动作试一遍
            else:
                best = max(row)
                a = rng.choice([i for i, v in enumerate(row) if v >= best - 1e-12])
        d, r = self.actions[a]
        return d, r, a

    # ---- 学习 ----
    def update(self, key: str, a: int, reward: float, next_key: str | None) -> None:
        if not self.learn:
            return
        row = self._row(key, create=True)
        nxt = 0.0
        if next_key is not None:
            nrow = self._row(next_key, create=True)
            nxt = max(nrow)
        row[a] += self.alpha * (reward + self.gamma * nxt - row[a])
        self.n[key][a] += 1
        self.n_updates += 1

    # ---- 保存/加载/合并 ----
    def to_json(self) -> dict:
        return {"actions": self.actions, "q": self.q, "n": self.n, "n_updates": self.n_updates,
                "alpha": self.alpha, "gamma": self.gamma}

    def load_json(self, d: dict) -> None:
        acts = [tuple(a) for a in d["actions"]]
        if acts != [tuple(a) for a in self.actions]:
            raise ValueError("Q 表的动作集合与当前算子配置不一致")
        self.q = {k: list(v) for k, v in d["q"].items()}
        self.n = {k: list(v) for k, v in d["n"].items()}
        self.n_updates = int(d.get("n_updates", 0))

    @staticmethod
    def merge(tables: list[dict]) -> dict:
        """按访问次数加权平均合并若干 Q 表（并行训练后使用）."""
        out = {"actions": tables[0]["actions"], "q": {}, "n": {}, "n_updates": 0,
               "alpha": tables[0].get("alpha"), "gamma": tables[0].get("gamma")}
        for t in tables:
            out["n_updates"] += t.get("n_updates", 0)
            for k, row in t["q"].items():
                nrow = t["n"][k]
                if k not in out["q"]:
                    out["q"][k] = [0.0] * len(row)
                    out["n"][k] = [0] * len(row)
                for i, (qv, nv) in enumerate(zip(row, nrow)):
                    tot = out["n"][k][i] + nv
                    if tot > 0:
                        out["q"][k][i] = (out["q"][k][i] * out["n"][k][i] + qv * nv) / tot
                    out["n"][k][i] = tot
        return out


# ---- 运行时选择器获取（训练脚本可注入全局学习器）----
TRAINING_SELECTOR: QSelector | None = None
_FROZEN_CACHE: dict[str, dict] = {}


def get_selector(alg, destroy_ops: list[str], repair_ops: list[str]) -> QSelector | None:
    """operator_selector == "qlearn" 时返回选择器；否则返回 None（走原轮盘赌）."""
    if getattr(alg, "operator_selector", "roulette") != "qlearn":
        return None
    if TRAINING_SELECTOR is not None:
        return TRAINING_SELECTOR
    sel = QSelector(destroy_ops, repair_ops, eps=getattr(alg, "qlearn_eval_epsilon", 0.05),
                    learn=False)
    path = getattr(alg, "qtable_path", None)
    if path:
        if path not in _FROZEN_CACHE:
            _FROZEN_CACHE[path] = json.loads(Path(path).read_text(encoding="utf-8"))
        sel.load_json(_FROZEN_CACHE[path])
    return sel
