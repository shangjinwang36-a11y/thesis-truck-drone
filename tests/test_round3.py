"""第三轮：机体航次链次序修复（早于链内已有航次的新航次必须插在其前面）."""
import json
from pathlib import Path

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.plan import ground_only_plan
from tdr.schedule import initial_state, schedule_plan
from tdr.evaluate import evaluate_plan

ROOT = Path(__file__).resolve().parents[1]


def _setup():
    pkg = json.load(open(ROOT / "data" / "package.json"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    inst = load_instance(pkg, "C50")
    return inst, phys, ground_only_plan(inst)


def test_chain_insert_follows_route_order():
    inst, phys, plan = _setup()
    truck = max(plan.routes, key=lambda k: len(plan.routes[k]))
    r = plan.routes[truck]
    assert len(r) >= 8
    drone = phys.home_drone if hasattr(phys, "home_drone") else f"d{int(truck[1:])}"
    late = plan.add_sortie(drone, truck, r[5], "STOP", 0.0, [], r[7])
    early = plan.add_sortie(drone, truck, r[1], "STOP", 0.0, [], r[3])
    assert plan.drone_sorties[drone] == [early.sid, late.sid]
    # 时刻表固定点必须收敛(此前顺序颠倒会每轮漂移约 1300 s，14 轮不收敛)
    tl = schedule_plan(plan, inst, phys, initial_state(inst, phys))
    assert tl.iterations < 14


# =============================================================== 轻型机/换电配置
import copy
import math

import pytest

from tdr.config import AlgorithmConfig
from tdr.schedule import Timeline, allocate_charging
from tdr.evaluate import truck_slot_check
from tdr.experiment import build_case_nominal
from tdr.experiment import load_case_nominal


def _light(trucks100=8):
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    return pkg, phys


def test_light_energy_model():
    pkg, phys = _light()
    assert phys.swap_mode and phys.truck_drone_slots == 3 and phys.drones_per_truck_initial == 2
    assert abs(phys.e_cap - 0.5) < 1e-12 and abs(phys.e_min - 0.1) < 1e-12
    # 可用航程 R_use(m)=18000-1500m：飞到 20% 应急电量恰好用掉 80% 电量
    for m in (0.0, 2.0, 4.0):
        r_use = 18000.0 - 1500.0 * m
        assert abs(phys.fly_energy_kwh(r_use, m) - 0.8 * phys.e_cap) < 1e-9
    # 悬停至 0%：空载 22.5 min，4 kg 时 15 min，线性插值
    assert abs(phys.hover_energy_kwh(22.5 * 60, 0.0) - phys.e_cap) < 1e-9
    assert abs(phys.hover_energy_kwh(15 * 60, 4.0) - phys.e_cap) < 1e-9
    p0, p4, p2 = phys.hover_power(0.0), phys.hover_power(4.0), phys.hover_power(2.0)
    assert abs(p2 - 0.5 * (p0 + p4)) < 1e-9
    assert abs(phys.drone_speed_m_s - 60 / 3.6) < 1e-9


def test_light_weights_scaled_and_spec_untouched():
    spec = json.load(open(ROOT / "data" / "package.json"))
    pkg, _ = _light()
    n_changed = 0
    for cs, cl in zip(spec["cases"], pkg["cases"]):
        for rs, rl in zip(cs["customers"], cl["customers"]):
            assert abs(rl[3] - 0.8 * rs[3]) < 1e-9 and rl[3] <= 4.0 + 1e-12
            n_changed += rl[3] != rs[3]
    assert n_changed == 450
    assert max(r[3] for c in spec["cases"] for r in c["customers"]) == 5.0     # 原数据未改动
    # 规范配置不含换电
    sp = PhysicalConfig.from_dict(spec["config"])
    assert not sp.swap_mode and sp.truck_drone_slots == 2 and sp.drone_count == 5


def test_fleet_and_home_truck_mapping():
    pkg, phys = _light()
    p100 = phys.for_case(pkg["case_fleet"], "R100")
    p50 = phys.for_case(pkg["case_fleet"], "R50")
    assert (p50.truck_count, p50.drone_count) == (5, 10)
    assert (p100.truck_count, p100.drone_count) == (8, 16)
    assert p100.home_truck("d1") == "t1" and p100.home_truck("d2") == "t1"
    assert p100.home_truck("d3") == "t2" and p100.home_truck("d16") == "t8"
    assert p100.home_drones("t8") == ["d15", "d16"]
    st = initial_state(load_instance(pkg, "R100"), p100)
    assert st.drone_start["d16"].truck == "t8" and st.truck_ac["t3"] == 4.0   # 4 块备用电池


def test_three_slot_capacity():
    pkg, phys = _light()
    inst = load_instance(pkg, "C50")
    plan = ground_only_plan(inst)
    t1, t2 = plan.routes["t1"], plan.routes["t2"]
    assert len(t1) >= 4 and len(t2) >= 4

    def tl_with(n_rec):
        plan2 = plan.clone()
        tl = Timeline(t0=0.0)
        tl.truck_finish = {k: 5000.0 for k in plan2.routes}
        for i, d in enumerate(["d3", "d4", "d5"][:n_rec]):
            s = plan2.add_sortie(d, "t2", t2[0], "STOP", 0.0, [], t1[2])
            tl.launch_times[s.sid] = (100.0, 110.0, (0.0, 0.0))
            tl.rec_times[s.sid] = (1000.0, 1030.0)        # 同时回收到 t1
        return plan2, tl
    st = initial_state(inst, phys)
    # t1 开局 2 架(d1,d2 空闲在车)；再同时回收 1 架 = 3 架，未超 3 槽
    p, tl = tl_with(1)
    assert not [e for e in truck_slot_check(p, inst, phys, tl, st) if e.startswith("SLOT_OVER:t1")]
    # 同时回收 2 架 = 4 架 > 3：必须报超限
    p, tl = tl_with(2)
    assert any(e.startswith("SLOT_OVER:t1") for e in truck_slot_check(p, inst, phys, tl, st))
    # 对照：规范配置(2 槽、每车 1 机)：1 架在车 + 回收 1 架 = 2 未超，回收 2 架 = 3 超
    spec = json.load(open(ROOT / "data" / "package.json"))
    sp = PhysicalConfig.from_dict(spec["config"])
    sinst = load_instance(spec, "C50")
    splan = ground_only_plan(sinst)
    def sp_case(n):
        pl = splan.clone()
        tl = Timeline(t0=0.0)
        tl.truck_finish = {k: 5000.0 for k in pl.routes}
        for d in ["d2", "d3"][:n]:
            s = pl.add_sortie(d, "t2", pl.routes["t2"][0], "STOP", 0.0, [], pl.routes["t1"][2])
            tl.launch_times[s.sid] = (100.0, 110.0, (0.0, 0.0))
            tl.rec_times[s.sid] = (1000.0, 1030.0)
        return pl, tl
    sst = initial_state(sinst, sp)
    pl, tl = sp_case(1)
    assert not [e for e in truck_slot_check(pl, sinst, sp, tl, sst) if e.startswith("SLOT_OVER:t1")]
    pl, tl = sp_case(2)
    assert any(e.startswith("SLOT_OVER:t1") for e in truck_slot_check(pl, sinst, sp, tl, sst))


@pytest.fixture(scope="module")
def light_nominal(tmp_path_factory):
    pkg, phys = _light()
    case = "R100"
    p100 = phys.for_case(pkg["case_fleet"], case)
    inst = load_instance(pkg, case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    out = tmp_path_factory.mktemp("lnom")
    m = build_case_nominal(inst, p100, alg, out / case, eval_budget=700)
    plan, cost, H = load_case_nominal(inst, out / case)
    return inst, p100, plan, cost, H, m


def test_swap_logic(light_nominal):
    inst, phys, plan, cost, H, meta = light_nominal
    assert meta["status"] == "FEASIBLE" and meta["verified"]       # verify_plan + 回放均通过
    st = initial_state(inst, phys)
    ev = evaluate_plan(plan, inst, phys, st, H)
    assert ev.feasible
    tl = ev.timeline
    ws = [a for a in tl.actions if a.kind == "W"]
    assert len(ws) >= 1, "100 客户轻型机名义解应至少用一次换电"
    assert ev.cost_breakdown["ac_kwh"] == 0.0 and ev.cost_breakdown["c_vehicle"] == 0.0   # 无车载充电
    for w in ws:
        assert abs((w.end - w.start) - 60.0) < 1e-9               # 换电 60 s
        sid = int(w.ref[1:])
        ps = [a for a in tl.actions if a.kind == "P" and a.ref == w.ref]
        assert len(ps) == 1 and abs(ps[0].start - w.end) < 1e-6   # 紧接 P：司机人工串行
        others = [a for a in tl.actions if a.actor == w.actor and a is not w and a.kind in ("G", "P", "R", "U", "W")
                  and a.start < w.end - 1e-9 and w.start < a.end - 1e-9]
        assert not others                                          # 与其它人工动作不重叠
    # 换电后满电；每车换电次数 ≤ 备用电池数
    for d, stages in tl.drone_stages.items():
        e = tl.drone_energy[d]
        for i, s in enumerate(stages):
            if s.kind == "SWAP":
                assert abs(e[i + 1] - phys.e_cap) < 1e-9 and e[i] < phys.e_cap - 1e-9
    for k, n in tl.swap_count_by_truck.items():
        assert n <= phys.spare_batteries
    # 备用电池用尽 → 不可行（ENERGY_INFEASIBLE / SWAP_SPARES）
    st0 = initial_state(inst, phys)
    t_swap = next(iter(tl.swap_count_by_truck))
    st0.truck_ac[t_swap] = 0.0
    ev0 = evaluate_plan(plan, inst, phys, st0, H)
    assert not ev0.feasible and "SWAP" in " ".join(ev0.violations)
    # 补电成本：换下电池 + 回库电池都计入仓库补电量
    assert ev.cost_breakdown["depot_refill_kwh"] > 0
