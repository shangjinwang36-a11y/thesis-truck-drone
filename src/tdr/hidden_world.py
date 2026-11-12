"""隐藏失效环境（customer-failure-v3-1）与公开观察."""
from __future__ import annotations

import hashlib
import json
import platform
import random
from dataclasses import dataclass

from . import GENERATOR_VERSION
from .data import Instance


@dataclass(frozen=True)
class Observation:
    time_s: float
    kind: str                    # "DELIVERY_UNAVAILABLE" | "AIR_DELIVERY_ACCEPTED"
    parcel_id: str
    customer_id: str
    air_delivery_available: bool
    ground_delivery_available: bool = True
    truck_recovery_available: bool = True
    drone_id: str = ""
    flight_id: str = ""


@dataclass(frozen=True)
class EpisodeAudit:
    case_id: str
    environment_seed: int
    generator_version: str
    python_version: str
    eligible_customers: int
    configured_failure_count: int
    hidden_failure_parcels: tuple[str, ...]
    observed_air_failure_parcels: tuple[str, ...]


class HiddenWorld:
    """环境私有：seed、未揭示失败集合、观察记录；规划器永远拿不到这些字段."""

    def __init__(self, inst: Instance, case_id: str, environment_seed: int):
        self.__case_id = case_id
        self.__seed = environment_seed
        eligible = sorted((c for c in inst.customers), key=lambda c: (c.customer_id, c.parcel_id))
        encoded = json.dumps([GENERATOR_VERSION, case_id, environment_seed],
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        derived = int.from_bytes(hashlib.sha256(encoded).digest(), "big")
        rng = random.Random(derived)
        count = rng.choice((1, 2)) if len(eligible) >= 2 else len(eligible)
        chosen = rng.sample(eligible, count) if count > 0 else []
        self.__failed = frozenset(c.parcel_id for c in chosen)
        self.__observed: set[str] = set()
        self.__arrivals: dict[str, Observation] = {}
        self.__closed = False
        self.__eligible_count = len(eligible)

    @property
    def configured_failure_count(self) -> int:
        return len(self.__failed)

    def observe_air_arrival(self, parcel_id: str, now_s: float, attempt_id: str,
                            customer_id: str, drone_id: str) -> Observation:
        if self.__closed:
            raise RuntimeError("回合已关闭")
        if attempt_id in self.__arrivals:
            return self.__arrivals[attempt_id]
        failed = parcel_id in self.__failed
        obs = Observation(now_s, "DELIVERY_UNAVAILABLE" if failed else "AIR_DELIVERY_ACCEPTED",
                          parcel_id, customer_id, not failed, True, True, drone_id, attempt_id)
        if failed:
            self.__observed.add(parcel_id)
        self.__arrivals[attempt_id] = obs
        return obs

    def finish_episode(self) -> EpisodeAudit:
        if self.__closed:
            raise RuntimeError("审计已取回")
        self.__closed = True
        return EpisodeAudit(self.__case_id, self.__seed, GENERATOR_VERSION,
                            platform.python_version(), self.__eligible_count,
                            len(self.__failed), tuple(sorted(self.__failed)),
                            tuple(sorted(self.__observed)))


class TestWorld:
    """测试夹具：显式给定失败包裹集合（仅用于自动化测试，不用于正式实验）."""

    def __init__(self, inst: Instance, case_id: str, failed_parcels: tuple[str, ...]):
        self.__case_id = case_id
        self.__seed = -1
        self.__failed = frozenset(failed_parcels)
        self.__observed: set[str] = set()
        self.__arrivals: dict[str, Observation] = {}
        self.__closed = False
        self.__eligible_count = inst.n

    @property
    def configured_failure_count(self) -> int:
        return len(self.__failed)

    def observe_air_arrival(self, parcel_id, now_s, attempt_id, customer_id, drone_id):
        if attempt_id in self.__arrivals:
            return self.__arrivals[attempt_id]
        failed = parcel_id in self.__failed
        obs = Observation(now_s, "DELIVERY_UNAVAILABLE" if failed else "AIR_DELIVERY_ACCEPTED",
                          parcel_id, customer_id, not failed, True, True, drone_id, attempt_id)
        if failed:
            self.__observed.add(parcel_id)
        self.__arrivals[attempt_id] = obs
        return obs

    def finish_episode(self) -> EpisodeAudit:
        self.__closed = True
        return EpisodeAudit(self.__case_id, -1, GENERATOR_VERSION, platform.python_version(),
                            self.__eligible_count, len(self.__failed),
                            tuple(sorted(self.__failed)), tuple(sorted(self.__observed)))


def bernoulli_failure_flags(case_id: str, environment_seed: int, parcel_ids, p: float) -> frozenset:
    """每个包裹独立以概率 p 失败：u(parcel)=SHA256([版本,'bernoulli',case,seed,parcel])/2^256，失败 iff u<p.
    u 与 p、计划、策略(S/X)均无关 → (a) S/X 完全相同；(b) 不同 p 之间失败集合嵌套（共同随机数）."""
    failed = []
    for pid in sorted(parcel_ids):
        enc = json.dumps([GENERATOR_VERSION, "bernoulli", case_id, environment_seed, pid],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        u = int.from_bytes(hashlib.sha256(enc).digest(), "big") / float(1 << 256)
        if u < p:
            failed.append(pid)
    return frozenset(failed)


class BernoulliWorld(HiddenWorld):
    """失败模式 'bernoulli'：每个（若被空送的）客户独立以概率 p 失败；失败在无人机到达时才揭示.
    只有被计划空送并实际到达的包裹会被观察到；configured_failure_count 为全部客户中被标记者数(含从未被空送者)."""

    def __init__(self, inst: Instance, case_id: str, environment_seed: int, p: float):
        if not 0.0 <= p <= 1.0:
            raise ValueError("p 必须在 [0,1]")
        # 不调用 HiddenWorld.__init__（其 M∈{1,2} 抽样不适用）；name-mangled 字段在此初始化
        self._HiddenWorld__case_id = case_id
        self._HiddenWorld__seed = environment_seed
        self.p = p
        self._HiddenWorld__failed = bernoulli_failure_flags(
            case_id, environment_seed, [c.parcel_id for c in inst.customers], p)
        self._HiddenWorld__observed = set()
        self._HiddenWorld__arrivals = {}
        self._HiddenWorld__closed = False
        self._HiddenWorld__eligible_count = len(inst.customers)


def make_world(inst: Instance, case_id: str, environment_seed: int, failure_mode: str = "default",
               p: float | None = None):
    """失败模式工厂：'default'(规范：M∈{1,2}) | 'bernoulli'(每个空送客户独立概率 p)."""
    if failure_mode == "default":
        return HiddenWorld(inst, case_id, environment_seed)
    if failure_mode == "bernoulli":
        if p is None:
            raise ValueError("bernoulli 模式需要 p")
        return BernoulliWorld(inst, case_id, environment_seed, p)
    raise ValueError(f"未知失败模式 {failure_mode}")
