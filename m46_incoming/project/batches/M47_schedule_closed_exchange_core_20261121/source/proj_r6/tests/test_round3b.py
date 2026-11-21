"""第三轮第二批修复的回归测试（轻型机/换电配置）.

1 能量比较容差统一为 phys.energy_tol；
2 截断点落在别机空中服务内部时，残段只补完剩余服务（不重做整段）；
3 贪心修复向同一航次连续并入多票时，载荷/能量按并入后重新核对（不再产生 4.72 kg 之类的超载候选）；
4 恢复目录的 launch_truck 取真正放飞车；X 的兜底触发按“有无 S 资格可行解”；
5 STOPPED 时记录原因；每次运行输出失败包裹时延、makespan、z。
"""
import json
import random
import zlib
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import episode_metrics, load_case_nominal
from tdr.hidden_world import TestWorld
from tdr.schedule import DroneStage, StartState, Timeline, _swap_pass, initial_state, stage_energy
from tdr import simulate

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "light"


def _light(case):
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 1000
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, FIX / case)
    return pkg, phys, alg, inst, plan, H


def _episode(case, failed, strat):
    pkg, phys, alg, inst, plan, H = _light(case)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    assert nom.feasible
    world = TestWorld(inst, case, tuple(failed))
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    ep = simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg, rngs, recovery_eval_budget=1000)
    return inst, phys, ep


# ---------------------------------------------------------------- 1 容差
def test_energy_tolerance_single_source():
    phys = PhysicalConfig.from_dict(dict(json.load(open(ROOT / "data" / "package_light.json"))["config"]))
    assert phys.energy_tol == phys.tolerance_energy_kwh > 0
    stage = DroneStage("R", 0.0, phys.recovery_s, mass=0.0, sid=7)
    need = stage_energy(stage, phys)

    def run(shortfall):
        e0 = phys.e_min + need - shortfall            # R 结束余电 = e_min - shortfall
        st = StartState(t0=1.0, drone_energy={"d1": e0})
        tl = Timeline(t0=1.0)
        tl.drone_stages = {"d1": [stage]}

        class P:
            sorties = {}
        return _swap_pass(tl, P(), phys, st, set())[1]

    assert run(0.5 * phys.energy_tol) == ""            # 容差内：通过
    assert run(0.0) == ""                              # 恰在边界：通过（不是 0.100<0.100 的误报）
    msg = run(4 * phys.energy_tol)
    assert msg.startswith("SWAP_CANNOT_FIX") and "e=" in msg   # 超出容差：报告，且保留 6 位小数


# ---------------------------------------------------------------- 2 服务截断后续
def test_cut_inside_other_drone_service_resumes_remaining_only():
    # C50 / TestWorld：首次失败的截断点落在无人机 d3 正在进行的空中服务中（修复前整段服务重做，
    # 多算 34 s 和一次服务能耗，使 d3 回收余电低于 E_min，S/X 全部候选不可行 → STOPPED）
    failed = ("p020", "p013", "p033", "p014", "p049")
    seen = []
    orig = simulate.truncate

    def spy(*a, **k):
        r = orig(*a, **k)
        seen.append({d: (ds.service_parcel, ds.service_done_s) for d, ds in r[1].drone_start.items()
                     if getattr(ds, "service_parcel", None)})
        return r
    simulate.truncate = spy
    try:
        inst, phys, ep = _episode("C50", failed, "S")
    finally:
        simulate.truncate = orig
    resumed = [x for x in seen if x]
    assert resumed, "应出现至少一次截断落在别机空中服务内部"
    for x in resumed:
        for parcel, done in x.values():
            assert 0.0 < done < phys.air_service_s
    assert ep.status == "COMPLETED_VERIFIED"
    assert ep.replay is not None and ep.replay.ok


# ---------------------------------------------------------------- 3 载荷
def test_apply_air_rechecks_payload_after_previous_insertions():
    from tdr.moves import AirCandidate, apply_air
    pkg, phys, alg, inst, plan, H = _light("C50")
    s = next(x for x in plan.sorties.values() if not x.started and len(x.air) >= 2
             and sum(inst.parcel_mass[p] for p in x.air) > 0.5)
    heavy = next(c.parcel_id for c in inst.customers if c.mass_kg >= phys.drone_payload_limit_kg - 1e-9
                 and c.parcel_id not in s.air)
    cand = AirCandidate("EXTEND", s.truck or "", s.launch_vid, s.mode, s.lam, s.rec_vid, sid=s.sid, pos=0,
                        proxy=0.0, energy=0.0, drone=s.drone)
    p2 = plan.clone()
    assert apply_air(p2, inst, heavy, cand, phys=phys) is False        # 超载：拒绝
    assert heavy not in p2.sorties[s.sid].air
    p3 = plan.clone()
    assert apply_air(p3, inst, heavy, cand) is True                    # 旧调用（无 phys）行为不变


def test_greedy_repair_never_builds_overloaded_sortie():
    from tdr.moves import repair_greedy
    pkg, phys, alg, inst, plan, H = _light("R50")
    base = plan.clone()
    pool = []
    for s in list(base.sorties.values()):
        pool += s.air
        base.remove_sortie(s.sid)
    for v in base.visits.values():
        v.ground = []
    out, left = repair_greedy(base, inst, phys, [c.parcel_id for c in inst.customers], state=None)
    for s in out.sorties.values():
        assert sum(inst.parcel_mass[p] for p in s.payload_ids) <= phys.drone_payload_limit_kg + 1e-9


# ---------------------------------------------------------------- 4 X ⊇ S 覆盖
def test_catalog_launch_truck_is_true_launch_truck():
    from tdr.plan import Sortie
    from tdr.recovery import RecoveryCatalog
    pkg, phys, alg, inst, plan, H = _light("C50")
    frag = Sortie(99, "d1", "t3", None, "AIR", 0.0, ["p001"], next(iter(plan.visits)), [], True, 100.0,
                  (inst.depot_x, inst.depot_y), 0, 0, "t1")         # 已改派到 t3 接机，但真正放飞车是 t1
    cat = RecoveryCatalog(plan, frag, inst, "X")
    assert cat.launch_truck == "t1"


# ---------------------------------------------------------------- 5 记录与指标
def test_stopped_reason_recorded_and_metrics():
    # R50 强制 5 次失败：第二次重规划因 d4 在途、卡车被拖后悬停超限而无可行后缀（真实的能量紧张）
    pkg, phys, alg, inst, plan, H = _light("R50")
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    rng = random.Random(zlib.crc32(b"R50:1:5"))
    failed = tuple(rng.sample(air, 5))
    inst, phys, ep = _episode("R50", failed, "S")
    m = episode_metrics(ep)
    if ep.status != "COMPLETED_VERIFIED":
        assert m["stop_reason"] and "STOP_CONTEXT" in m["stop_reason"]
        assert "INITIAL_RECOVERY_FAILED" in m["stop_reason"]
        assert m["makespan_s"] is None
    # 已完成的运行：指标自洽
    failed2 = ("p020", "p013", "p033", "p014", "p049")
    inst, phys, ep2 = _episode("C50", failed2, "S")
    assert ep2.status == "COMPLETED_VERIFIED"
    m2 = episode_metrics(ep2)
    assert len(m2["failed_delivery_delays_s"]) >= 1 and all(x > 0 for x in m2["failed_delivery_delays_s"])
    assert m2["makespan_s"] >= m2["z_s_metric"] - 1e-6
    assert m2["stop_reason"] is None
