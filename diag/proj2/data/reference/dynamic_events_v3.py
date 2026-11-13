#!/usr/bin/env python3
"""1—2个客户订单随机失效、运行中揭示：Python 3.10+标准库示例。

    python dynamic_events_v3.py --seed 1
    python dynamic_events_v3.py --seed-summary
    python dynamic_events_v3.py --self-test

默认从全部具备空送资格的客户订单中抽样，包括名义地送订单。候选数>=2
时，失效点数在{1,2}中等概率选择，再无放回选择客户；0/1个候选分别设
0/1个失效点。这是研究情景分配，不是实测故障率。

隐藏结果绑定稳定的客户/包裹ID，不绑定名义航次、到达序号或搜索调用。
两策略使用相同case_id和环境seed即可面对同一外生环境；路线分化后，
各自在实际到达时观察。如果某个隐藏失效订单直接地送，就不产生该次
空送失败，也不补抽新点。设置失效点数和实际观察失败数分别报告。

规划器仅收到不可变的公开状态与已发生观察，不接收环境对象、环境seed、
未来失效集合或未来修复时间。Python双下划线仅提供封装；完整系统仍应
使用白名单消息/进程接口隔离未来信息。回合关闭后才返回独立审计信息。

演示从两架已载货的在途机和两件车上地送货物开始，回放人工事件夹具。
失败票保持在机上并累计ground_required；其他包裹可继续配送。未优化
S/X，未计算距离、能耗、回收、放飞位置或最终成本，也未证明物理可行。
--seed-summary只统计十个环境的事件表现，不是十种子的恢复成本实验。
没有等待改投、固定场站、额外空送票数或航次数的政策上限。
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import platform
import random
import sys
import unittest
from dataclasses import asdict, dataclass, replace


GENERATOR_VERSION = "customer-failure-v3-1"


@dataclass(frozen=True)
class Order:
    parcel_id: str
    customer_id: str
    mass_kg: float
    air_eligible: bool = True
    nominal_mode: str = "AIR"


@dataclass(frozen=True)
class Observation:
    time_s: float
    kind: str
    parcel_id: str
    customer_id: str
    air_delivery_available: bool | None
    ground_delivery_available: bool = True
    truck_recovery_available: bool = True


@dataclass(frozen=True)
class EpisodeAudit:
    """环境关闭后交给实验记录器；不属于PlannerInput。"""

    case_id: str
    environment_seed: int
    generator_version: str
    python_version: str
    sampling_population: str
    eligible_customers: int
    configured_failure_count: int
    hidden_failure_parcels: tuple[str, ...]
    observed_air_failure_parcels: tuple[str, ...]
    note: str


class HiddenFailureEnvironment:
    """环境私有场景固定；观察次数和访问顺序不会改变失效客户。"""

    def __init__(self, orders: tuple[Order, ...], case_id: str, seed: int):
        if len({o.parcel_id for o in orders}) != len(orders):
            raise ValueError("包裹ID必须唯一。")
        if len({o.customer_id for o in orders}) != len(orders):
            raise ValueError("本例按一客一件建模，客户ID必须唯一。")
        self.__orders = {o.parcel_id: o for o in orders}
        eligible = sorted((o for o in orders if o.air_eligible),
                          key=lambda o: (o.customer_id, o.parcel_id))
        encoded = json.dumps([GENERATOR_VERSION, case_id, seed],
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        derived_seed = int.from_bytes(hashlib.sha256(encoded).digest(), "big")
        rng = random.Random(derived_seed)
        count = rng.choice((1, 2)) if len(eligible) >= 2 else len(eligible)
        self.__failed = frozenset(o.parcel_id for o in rng.sample(eligible, count))
        self.__eligible_count = len(eligible)
        self.__case_id = case_id
        self.__seed = seed
        self.__observed_failures: set[str] = set()
        self.__arrivals: dict[str, Observation] = {}
        self.__closed = False

    def observe_air_arrival(self, parcel_id: str, now_s: float,
                            attempt_id: str) -> Observation:
        if self.__closed:
            raise RuntimeError("回合已经关闭，不能继续访问该环境。")
        if attempt_id in self.__arrivals:
            old = self.__arrivals[attempt_id]
            if old.parcel_id != parcel_id:
                raise ValueError("同一到达事件ID不能对应不同包裹。")
            return old
        order = self.__orders[parcel_id]
        if not order.air_eligible:
            raise ValueError("静态不具备空送资格的订单不能被派作空送。")
        failed = parcel_id in self.__failed
        observation = Observation(
            now_s, "DELIVERY_UNAVAILABLE" if failed else "AIR_DELIVERY_ACCEPTED",
            parcel_id, order.customer_id, not failed,
        )
        if failed:
            self.__observed_failures.add(parcel_id)
        self.__arrivals[attempt_id] = observation
        return observation

    def finish_episode(self) -> EpisodeAudit:
        """由实验执行器关闭回合后调用；返回值绝不能再发给规划器。"""
        if self.__closed:
            raise RuntimeError("回合审计已取回，不重复结束。")
        self.__closed = True
        note = ("候选>=2，M在{1,2}中等概率；客户无放回抽样。"
                if self.__eligible_count >= 2 else
                "候选不足2个，M等于候选数量；没有强造故障。")
        return EpisodeAudit(
            self.__case_id, self.__seed, GENERATOR_VERSION, platform.python_version(),
            "ALL_AIR_ELIGIBLE_CUSTOMERS_INCLUDING_NOMINAL_GROUND",
            self.__eligible_count, len(self.__failed), tuple(sorted(self.__failed)),
            tuple(sorted(self.__observed_failures)), note,
        )


@dataclass(frozen=True)
class PublicParcel:
    parcel_id: str
    customer_id: str
    mass_kg: float
    holder: str
    air_eligible: bool
    ground_required: bool = False
    delivered: bool = False


@dataclass(frozen=True)
class PublicDrone:
    drone_id: str
    manifest: tuple[str, ...]
    payload_kg: float


@dataclass(frozen=True)
class PlannerInput:
    time_s: float
    observations: tuple[Observation, ...]
    parcels: tuple[PublicParcel, ...]
    drones: tuple[PublicDrone, ...]
    ground_required_parcels: tuple[str, ...]


@dataclass(frozen=True)
class ReplanRequest:
    time_s: float
    newly_failed_parcels: tuple[str, ...]
    all_known_ground_required: tuple[str, ...]
    remaining_manifests: tuple[PublicDrone, ...]
    status: str = "REPLAN_REQUIRED_NOT_SOLVED"


class RecoveryPlanner:
    """信息边界示例：只记录已知状态及重排请求，不求解路线。"""

    def __init__(self):
        self.transcript: list[PlannerInput] = []
        self.requests: list[ReplanRequest] = []

    def on_observation(self, state: PlannerInput) -> None:
        self.transcript.append(state)
        failures = tuple(sorted(o.parcel_id for o in state.observations
                                if o.kind == "DELIVERY_UNAVAILABLE"))
        if failures:
            self.requests.append(ReplanRequest(
                state.time_s, failures, state.ground_required_parcels, state.drones,
            ))


@dataclass(frozen=True)
class Action:
    time_s: float
    mode: str
    parcel_id: str
    actor_id: str


@dataclass(frozen=True)
class DemoResult:
    public_transcript: tuple[PlannerInput, ...]
    replan_requests: tuple[ReplanRequest, ...]
    audit_after_episode: EpisodeAudit
    scope: str = "人工事件夹具；未优化S/X、未核算物理可行性或成本"


def example_orders() -> tuple[Order, ...]:
    masses = (1.0, 2.0, 0.5, 1.0, 0.2, 3.0, 1.0, 0.5, 1.0, 2.0)
    return tuple(Order(f"p{i:03d}", f"c{i:03d}", mass,
                       nominal_mode="AIR" if i <= 8 else "GROUND")
                 for i, mass in enumerate(masses, start=1))


def example_actions() -> tuple[Action, ...]:
    actions = [Action(100.0 + 100.0 * i, "AIR", f"p{i+1:03d}", "d1")
               for i in range(4)]
    actions += [Action(150.0 + 100.0 * i, "AIR", f"p{i+5:03d}", "d2")
                for i in range(4)]
    actions += [Action(125.0, "GROUND", "p009", "t1"),
                Action(425.0, "GROUND", "p010", "t2")]
    return tuple(sorted(actions, key=lambda a: (a.time_s, a.parcel_id)))


def _run_fixture(orders: tuple[Order, ...], actions: tuple[Action, ...],
                 environment: HiddenFailureEnvironment) -> DemoResult:
    """回放给定动作；失败后继续脚本只为验证事件，不代表安全恢复策略。"""
    parcels: dict[str, PublicParcel] = {}
    for order in orders:
        action = next((a for a in actions if a.parcel_id == order.parcel_id), None)
        holder = (("drone:" if action.mode == "AIR" else "truck:") + action.actor_id
                  if action is not None else "truck:t1")
        parcels[order.parcel_id] = PublicParcel(
            order.parcel_id, order.customer_id, order.mass_kg, holder, order.air_eligible,
        )
    planner = RecoveryPlanner()  # 无环境、种子或隐藏失效集合参数。
    # 货物清空不等于实体飞机消失，空载机仍保留在公开状态中。
    known_drone_ids = sorted({action.actor_id for action in actions if action.mode == "AIR"})

    def publish(now_s: float, observations: tuple[Observation, ...]) -> None:
        drones = tuple(PublicDrone(
            drone_id,
            tuple(sorted(p.parcel_id for p in parcels.values()
                         if p.holder == "drone:" + drone_id)),
            sum(p.mass_kg for p in parcels.values() if p.holder == "drone:" + drone_id),
        ) for drone_id in known_drone_ids)
        planner.on_observation(PlannerInput(
            now_s, observations, tuple(parcels[key] for key in sorted(parcels)), drones,
            tuple(sorted(p.parcel_id for p in parcels.values() if p.ground_required)),
        ))

    publish(0.0, ())
    queue: list[tuple[float, int, str, str, str]] = []
    for i, action in enumerate(actions):
        heapq.heappush(queue, (action.time_s, 1, f"a{i:03d}", action.mode,
                               action.parcel_id))

    while queue:
        now_s = queue[0][0]
        same_time = []
        while queue and queue[0][0] == now_s:
            same_time.append(heapq.heappop(queue))
        observations = []
        # 同刻先处理完成事件，再处理全部到达，最后只发布一次公开快照。
        for _, _, action_id, mode, parcel_id in sorted(same_time):
            parcel = parcels[parcel_id]
            if mode == "AIR":
                if parcel.delivered or parcel.ground_required:
                    raise ValueError("不能重复空送已完成或已知需要地送的包裹。")
                if not parcel.holder.startswith("drone:"):
                    raise ValueError("空送包裹必须实际在无人机上。")
                observation = environment.observe_air_arrival(parcel_id, now_s, action_id)
                observations.append(observation)
                if observation.kind == "DELIVERY_UNAVAILABLE":
                    parcels[parcel_id] = replace(parcel, air_eligible=False,
                                                 ground_required=True)
                else:
                    heapq.heappush(queue, (now_s + 60.0, 0, action_id + "_done",
                                          "AIR_COMPLETE", parcel_id))
            elif mode == "AIR_COMPLETE":
                if parcel.delivered or parcel.ground_required:
                    raise ValueError("失败票不能被登记为成功空送。")
                parcels[parcel_id] = replace(parcel, holder="delivered", delivered=True)
                observations.append(Observation(now_s, "AIR_DELIVERED", parcel_id,
                                                 parcel.customer_id, True))
            elif mode == "GROUND":
                if parcel.delivered or not parcel.holder.startswith("truck:"):
                    raise ValueError("地送开始前必须由车辆实际持货且尚未交付。")
                # 地送不查询隐藏空送状态，不能透露尚未观察到的失效客户。
                heapq.heappush(queue, (now_s + 50.0, 0, action_id + "_done",
                                      "GROUND_COMPLETE", parcel_id))
                observations.append(Observation(now_s, "GROUND_SERVICE_STARTED", parcel_id,
                                                 parcel.customer_id, None))
            elif mode == "GROUND_COMPLETE":
                parcels[parcel_id] = replace(parcel, holder="delivered", delivered=True)
                observations.append(Observation(now_s, "GROUND_DELIVERED", parcel_id,
                                                 parcel.customer_id, None))
            else:
                raise ValueError("未知人工事件类型。")
        publish(now_s, tuple(observations))

    # 审计只交给外层记录器；规划器从来没有拿到这些字段。
    audit = environment.finish_episode()
    return DemoResult(tuple(planner.transcript), tuple(planner.requests), audit)


def run_demo(seed: int, case_id: str = "DEMO10") -> DemoResult:
    orders = example_orders()
    return _run_fixture(orders, example_actions(),
                        HiddenFailureEnvironment(orders, case_id, seed))


class DynamicEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 定位有针对性的边界测试夹具，不是正式实验选种子或筛收益。
        wanted = {frozenset(x) for x in (("p001", "p002"), ("p001", "p005"),
                                        ("p009", "p010"), ("p003",), ("p004",))}
        cls.seeds: dict[frozenset[str], int] = {}
        for seed in range(10000):
            audit = HiddenFailureEnvironment(example_orders(), "DEMO10", seed).finish_episode()
            key = frozenset(audit.hidden_failure_parcels)
            if key in wanted:
                cls.seeds.setdefault(key, seed)
            if len(cls.seeds) == len(wanted):
                break
        if len(cls.seeds) != len(wanted):
            raise AssertionError("未找到测试所需的事件夹具。")

    def test_same_seed_reproduces_environment_and_public_history(self):
        self.assertEqual(run_demo(1), run_demo(1))

    def test_sampling_has_one_or_two_distinct_customers_including_ground_orders(self):
        audits = [HiddenFailureEnvironment(example_orders(), "DEMO10", seed).finish_episode()
                  for seed in range(256)]
        self.assertEqual({a.configured_failure_count for a in audits}, {1, 2})
        self.assertEqual({p for a in audits for p in a.hidden_failure_parcels},
                         {o.parcel_id for o in example_orders()})
        for audit in audits:
            self.assertEqual(len(set(audit.hidden_failure_parcels)), audit.configured_failure_count)

    def test_candidate_shortages_are_explicit(self):
        empty = HiddenFailureEnvironment((), "EMPTY", 1).finish_episode()
        one = HiddenFailureEnvironment(example_orders()[:1], "ONE", 1).finish_episode()
        self.assertEqual(empty.configured_failure_count, 0)
        self.assertEqual(one.configured_failure_count, 1)

    def test_input_order_does_not_change_failure_environment(self):
        orders = example_orders()
        left = HiddenFailureEnvironment(orders, "DEMO10", 18).finish_episode()
        right = HiddenFailureEnvironment(tuple(reversed(orders)), "DEMO10", 18).finish_episode()
        self.assertEqual(left, right)

    def test_different_strategy_visit_orders_share_customer_outcomes(self):
        orders = example_orders()
        s_world = HiddenFailureEnvironment(orders, "PAIRED", 4)
        x_world = HiddenFailureEnvironment(orders, "PAIRED", 4)
        s_outcomes = {o.parcel_id: s_world.observe_air_arrival(o.parcel_id, i * 10.0,
                                                              f"S{i}").air_delivery_available
                      for i, o in enumerate(orders)}
        x_outcomes = {o.parcel_id: x_world.observe_air_arrival(o.parcel_id, i * 15.0,
                                                              f"X{i}").air_delivery_available
                      for i, o in enumerate(reversed(orders))}
        self.assertEqual(s_outcomes, x_outcomes)
        self.assertEqual(s_world.finish_episode().hidden_failure_parcels,
                         x_world.finish_episode().hidden_failure_parcels)

    def test_latent_ground_failures_are_not_observed_or_replaced(self):
        result = run_demo(self.seeds[frozenset(("p009", "p010"))])
        self.assertEqual(result.audit_after_episode.configured_failure_count, 2)
        self.assertEqual(result.audit_after_episode.observed_air_failure_parcels, ())
        self.assertEqual(result.replan_requests, ())
        self.assertTrue(all(p.delivered for p in result.public_transcript[-1].parcels))

    def test_second_failure_accumulates_without_losing_first_failed_parcel(self):
        result = run_demo(self.seeds[frozenset(("p001", "p002"))])
        self.assertEqual(len(result.replan_requests), 2)
        last = result.replan_requests[-1]
        self.assertEqual(last.all_known_ground_required, ("p001", "p002"))
        parcels = {p.parcel_id: p for p in result.public_transcript[-1].parcels}
        for key in ("p001", "p002"):
            self.assertFalse(parcels[key].delivered)
            self.assertEqual(parcels[key].holder, "drone:d1")
        self.assertTrue(parcels["p003"].delivered)
        self.assertTrue(parcels["p004"].delivered)

    def test_failures_can_affect_two_different_drones(self):
        result = run_demo(self.seeds[frozenset(("p001", "p005"))])
        last = {d.drone_id: d.manifest for d in result.public_transcript[-1].drones}
        self.assertEqual(last, {"d1": ("p001",), "d2": ("p005",)})

    def test_same_time_observations_are_merged_before_replanning(self):
        seed = self.seeds[frozenset(("p001", "p005"))]
        orders = example_orders()
        actions = (Action(100.0, "AIR", "p001", "d1"),
                   Action(100.0, "AIR", "p005", "d2"))
        result = _run_fixture(orders, actions, HiddenFailureEnvironment(orders, "DEMO10", seed))
        self.assertEqual(len(result.replan_requests), 1)
        self.assertEqual(result.replan_requests[0].newly_failed_parcels, ("p001", "p005"))

    def test_different_hidden_futures_have_identical_earlier_public_inputs(self):
        first = run_demo(self.seeds[frozenset(("p003",))])
        second = run_demo(self.seeds[frozenset(("p004",))])
        before = lambda result: tuple(s for s in result.public_transcript if s.time_s < 300.0)
        self.assertGreater(len(before(first)), 3)
        self.assertEqual(before(first), before(second))

    def test_public_inputs_contain_no_future_failures_or_environment_seed(self):
        result = run_demo(20261111)
        forbidden = {"seed", "environment_seed", "hidden_failure_parcels", "environment",
                     "configured_failure_count", "rng", "audit_after_episode"}

        def inspect(value):
            if isinstance(value, dict):
                self.assertTrue(forbidden.isdisjoint(value))
                for child in value.values():
                    inspect(child)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    inspect(child)

        for state in result.public_transcript:
            inspect(asdict(state))

    def test_delivery_failure_does_not_disable_truck_recovery(self):
        result = run_demo(self.seeds[frozenset(("p001", "p002"))])
        failures = [o for s in result.public_transcript for o in s.observations
                    if o.kind == "DELIVERY_UNAVAILABLE"]
        self.assertTrue(failures)
        self.assertTrue(all(o.ground_delivery_available and o.truck_recovery_available
                            for o in failures))

    def test_observation_uses_actual_arrival_and_duplicate_query_is_idempotent(self):
        world = HiddenFailureEnvironment(example_orders(), "DEMO10", 3)
        first = world.observe_air_arrival("p001", 127.0, "actual_1")
        repeated = world.observe_air_arrival("p001", 999.0, "actual_1")
        self.assertEqual(first, repeated)
        self.assertEqual(first.time_s, 127.0)

    def test_episode_audit_closes_future_observation_access(self):
        world = HiddenFailureEnvironment(example_orders(), "DEMO10", 1)
        world.finish_episode()
        with self.assertRaises(RuntimeError):
            world.observe_air_arrival("p001", 100.0, "late_call")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--seed-summary", action="store_true",
                        help="只汇总种子1—10的环境及观察数量，不运行S/X优化。")
    parser.add_argument("--json", action="store_true", help="公开事件记录及回合结束后的独立审计JSON。")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(DynamicEventTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if args.seed_summary:
        records = [run_demo(seed) for seed in range(1, 11)]
        if args.json:
            print(json.dumps({"scope": "十个环境的事件统计，不是S/X成本实验", "records": [
                {"seed": r.audit_after_episode.environment_seed,
                 "configured_failure_count": r.audit_after_episode.configured_failure_count,
                 "hidden_failure_parcels": r.audit_after_episode.hidden_failure_parcels,
                 "observed_air_failure_parcels": r.audit_after_episode.observed_air_failure_parcels}
                for r in records]}, ensure_ascii=False, indent=2))
        else:
            print("仅统计人工夹具的十个随机环境；未求解S/X、未计算平均成本差。")
            print("seed  设置点数  实际观察数  回合结束后审计的失效票    已观察失败票")
            for record in records:
                audit = record.audit_after_episode
                print(f"{audit.environment_seed:4d}  {audit.configured_failure_count:8d}  "
                      f"{len(audit.observed_air_failure_parcels):10d}  "
                      f"{','.join(audit.hidden_failure_parcels):22s}  "
                      f"{','.join(audit.observed_air_failure_parcels) or '无'}")
            print("原地送的隐藏失效客户不会触发空送失败，程序不会为凑数重新抽样。")
        return 0

    result = run_demo(args.seed)
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0
    print(result.scope)
    print("两机在途载货，8票按示意空送事件回放，另2票地送；全部10票均可被抽为失效点。")
    print("规划器输入不含未来失效集合和环境seed；下列记录按到达/服务时刻揭示。")
    labels = {"DELIVERY_UNAVAILABLE": "到点发现不能空送，货物留机，立即触发重排",
              "AIR_DELIVERY_ACCEPTED": "到点正常，开始60秒空中交付",
              "AIR_DELIVERED": "空中交付完成",
              "GROUND_SERVICE_STARTED": "开始50秒地送服务，不查询空送失效信息",
              "GROUND_DELIVERED": "地面交付完成"}
    for state in result.public_transcript:
        for observation in state.observations:
            print(f"t={state.time_s:6.1f}s  {observation.parcel_id}  {labels[observation.kind]}")
    final_state = result.public_transcript[-1]
    print("\n累计已知必须地送的包裹：", ",".join(final_state.ground_required_parcels) or "无")
    print("本示例没有执行回收优化，失败货物仍保留在真实机体上：")
    for drone in final_state.drones:
        print(f"  {drone.drone_id}: {','.join(drone.manifest)}，载荷{drone.payload_kg:g}kg")
    audit = result.audit_after_episode
    print("回合结束后的环境审计（从未传入规划器）：")
    print(f"  设置{audit.configured_failure_count}个失效点，实际观察"
          f"{len(audit.observed_air_failure_parcels)}个空送失败。")
    print("  失效票：", ",".join(audit.hidden_failure_parcels))
    print("  环境seed：", audit.environment_seed)
    print("没有回收成本、S/X收益或实际在线控制性能结论。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
