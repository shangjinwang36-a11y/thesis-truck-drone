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
