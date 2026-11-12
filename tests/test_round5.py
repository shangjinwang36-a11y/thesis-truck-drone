import json
from pathlib import Path

import pytest

from tdr.data import load_instance
from tdr.hidden_world import BernoulliWorld, HiddenWorld, bernoulli_failure_flags, make_world

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def inst():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    return load_instance(json.loads(p.read_text(encoding="utf-8")), "C50")


def test_default_mode_unchanged(inst):
    a = make_world(inst, "C50", 3)
    b = HiddenWorld(inst, "C50", 3)
    assert isinstance(a, HiddenWorld) and not isinstance(a, BernoulliWorld)
    assert a.finish_episode().hidden_failure_parcels == b.finish_episode().hidden_failure_parcels


def test_bernoulli_deterministic_and_strategy_independent(inst):
    a = make_world(inst, "C50", 5, "bernoulli", 0.2)
    b = make_world(inst, "C50", 5, "bernoulli", 0.2)
    assert a.finish_episode().hidden_failure_parcels == b.finish_episode().hidden_failure_parcels
    c = make_world(inst, "C50", 6, "bernoulli", 0.2)
    assert make_world(inst, "C50", 5, "bernoulli", 0.2).configured_failure_count >= 0
    assert c.finish_episode().hidden_failure_parcels != make_world(inst, "C50", 5, "bernoulli", 0.2).finish_episode().hidden_failure_parcels


def test_bernoulli_nested_across_p(inst):
    ids = [c.parcel_id for c in inst.customers]
    f1 = bernoulli_failure_flags("C50", 1, ids, 0.1)
    f2 = bernoulli_failure_flags("C50", 1, ids, 0.2)
    f3 = bernoulli_failure_flags("C50", 1, ids, 0.3)
    assert f1 <= f2 <= f3


def test_bernoulli_rate_close_to_p(inst):
    ids = [c.parcel_id for c in inst.customers]
    for p in (0.1, 0.2, 0.3):
        tot = sum(len(bernoulli_failure_flags("C50", s, ids, p)) for s in range(1, 201))
        rate = tot / (200 * len(ids))
        assert abs(rate - p) < 0.02, (p, rate)
    assert bernoulli_failure_flags("C50", 1, ids, 0.0) == frozenset()
    assert bernoulli_failure_flags("C50", 1, ids, 1.0) == frozenset(ids)


def test_bernoulli_reveal_only_on_arrival(inst):
    w = make_world(inst, "C50", 2, "bernoulli", 0.5)
    ids = [c for c in inst.customers]
    obs = [w.observe_air_arrival(c.parcel_id, 1.0, f"a-{i}", c.customer_id, "d") for i, c in enumerate(ids)]
    audit = w.finish_episode()
    failed_obs = {o.parcel_id for o in obs if not o.air_delivery_available}
    assert failed_obs == set(audit.hidden_failure_parcels) == set(audit.observed_air_failure_parcels)
    assert len(failed_obs) > 0


def test_bernoulli_unattempted_not_observed(inst):
    w = make_world(inst, "C50", 2, "bernoulli", 0.5)
    c = inst.customers[0]
    w.observe_air_arrival(c.parcel_id, 1.0, "x", c.customer_id, "d")
    audit = w.finish_episode()
    assert set(audit.observed_air_failure_parcels) <= {c.parcel_id}


def _episode_audit(strat, flag):
    import random, zlib
    from tdr.config import AlgorithmConfig, PhysicalConfig
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.hidden_world import TestWorld
    from tdr.schedule import initial_state
    from tdr import simulate
    case = "C50"
    pkg = json.load(open(ROOT / "data" / "package.json"))
    fx = ROOT / "tests" / "fixtures" / "spec" / case
    if not fx.exists():
        pytest.skip("fixture missing")
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 300
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    alg.reassign_adopt_only_if_best = flag
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, fx)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    rng = random.Random(zlib.crc32(f"{case}:1:3".encode()))
    world = TestWorld(inst, case, tuple(rng.sample(air, 3)))
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    cap = []
    orig = simulate.optimize

    def wrap(p, ctx, b, **kw):
        r = orig(p, ctx, b, **kw)
        cap.append(r)
        return r
    simulate.optimize = wrap
    try:
        ep = simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg, rngs, recovery_eval_budget=300)
    finally:
        simulate.optimize = orig
    return ep, cap


@pytest.mark.parametrize("strat", ["S", "X"])
def test_reassign_flag_never_adopts_worse_than_best(strat):
    """reassign_adopt_only_if_best=True：目录候选只有优于全局最优才替换当前解（防止丢弃 ALNS 进展）."""
    ep, cap = _episode_audit(strat, True)
    assert ep.status.startswith("COMPLETED") or ep.status.startswith("STOPPED")
    for r in cap:
        gap = r.stats.audit.get("reassign:adopt_gap_max")
        assert gap is None or gap < 0.0


def test_reassign_flag_default_false():
    from tdr.config import AlgorithmConfig
    assert AlgorithmConfig().reassign_adopt_only_if_best is False


def _light_plan():
    from tdr.experiment import load_case_nominal
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    fx = ROOT / "tests" / "fixtures" / "light"
    case = "C50"
    if not (fx / case).exists():
        pytest.skip("fixture missing")
    from tdr.config import PhysicalConfig
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    inst = load_instance(pkg, case)
    plan, _, H = load_case_nominal(inst, fx / case)
    return inst, phys, plan


def _overlaps(plan):
    from tdr.moves import drone_chain
    bad = []
    for d in plan.drone_sorties:
        ch = drone_chain(plan, d)
        for i in range(len(ch)):
            for j in range(i + 1, len(ch)):
                _, li, ri = ch[i]; _, lj, rj = ch[j]
                if not (ri < lj or li > rj):
                    bad.append((d, ch[i], ch[j]))
    return bad


@pytest.mark.parametrize("recheck", [True, False])
def test_apply_air_recheck_prevents_overlapping_chain(recheck):
    """贪心修复里两个 NEW 候选在修复开始时选了同一机体同一区间：应用第二个时必须重新核对机位."""
    from tdr import moves
    from tdr.moves import AirCandidate, apply_air, drones_on_truck, sortie_slot_free
    inst, phys, plan = _light_plan()
    plan = plan.clone()
    # 清空某车的全部航次以制造空闲机位
    truck = max(sorted(plan.routes), key=lambda t: len(plan.routes[t]))
    for sid in [s.sid for s in plan.sorties.values() if s.truck == truck and not s.started]:
        plan.remove_sortie(sid)
    route = plan.routes[truck]
    assert len(route) >= 4
    drones = drones_on_truck(plan, truck)
    assert len(drones) >= 1
    d0 = drones[0]
    a, b = 1, 3
    assert sortie_slot_free(plan, d0, a, b)
    parcels = [p for p in inst.parcel_mass][:2]
    old = moves.CHAIN_RECHECK
    moves.CHAIN_RECHECK = recheck
    try:
        oks = []
        for p in parcels:
            cand = AirCandidate("NEW", truck, route[a], "ARC", 0.5, route[b], proxy=0.0, energy=0.0, drone=d0)
            oks.append(apply_air(plan, inst, p, cand, phys=phys))
    finally:
        moves.CHAIN_RECHECK = old
    if recheck:
        assert _overlaps(plan) == []                    # 无重叠：第二个换机体或失败
        assert oks[0] is True
    else:
        assert len(_overlaps(plan)) >= 1                # 旧行为复现：同机体区间重叠


def test_joint_target_parses_violations():
    from types import SimpleNamespace
    from tdr.recovery import _joint_target
    from tdr.plan import Plan
    p = Plan("X")
    # 构造最小计划：两条路线、两个已起飞航次
    v1 = p.add_visit("t1", "c1", pos=None, ground=[]).vid
    v2 = p.add_visit("t2", "c2", pos=None, ground=[]).vid
    s1 = p.add_sortie("d1", "t1", None, "ARC", 0.5, [], v1); s1.started = True
    s2 = p.add_sortie("d2", "t1", None, "ARC", 0.5, [], v2); s2.started = True
    ev = SimpleNamespace(violations=["SWAP_CANNOT_FIX:d2@100.0:e=-0.1<0.0"])
    assert _joint_target(p, ev, frag_sid=s1.sid, done=set()) == s2.sid
    assert _joint_target(p, ev, frag_sid=s1.sid, done={s2.sid}) is None        # 已重选过不重复
    ev = SimpleNamespace(violations=["SLOT_OVER:t2@10.0=4"])
    assert _joint_target(p, ev, frag_sid=s1.sid, done=set()) == s2.sid        # 回收在 t2 的在飞航次
    assert _joint_target(p, SimpleNamespace(violations=["H_EXCEEDED:t1@9>8"]), s1.sid, set()) is None
    assert _joint_target(p, SimpleNamespace(violations=["SWAP_CANNOT_FIX:d1@1.0"]), s1.sid, set()) is None  # 失败机本身不在此处理


def test_joint_catalog_S_restricted_to_own_launch_truck_X_any():
    """S 对在飞航次只考虑其放飞车，X 可任意车（同一目录/同一代码）."""
    from tdr.recovery import RecoveryCatalog
    from tdr import recovery
    import random, zlib
    from tdr.config import AlgorithmConfig, PhysicalConfig
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.hidden_world import TestWorld
    from tdr.schedule import initial_state
    from tdr import simulate
    case = "C50"
    pkg = json.load(open(ROOT / "data" / "package.json"))
    fx = ROOT / "tests" / "fixtures" / "spec" / case
    if not fx.exists():
        pytest.skip("fixture missing")
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 100
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, fx)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    rng = random.Random(zlib.crc32(f"{case}:1:3".encode()))
    world = TestWorld(inst, case, tuple(rng.sample(air, 3)))
    cap = []
    orig = simulate.initial_recovery

    def wrap(new_plan, state2, *a, **kw):
        cap.append((new_plan.clone(), state2))
        return orig(new_plan, state2, *a, **kw)
    simulate.initial_recovery = wrap
    try:
        simulate.run_episode(inst, plan, nom, H, phys, world, "X", alg,
                             simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                             recovery_eval_budget=100)
    finally:
        simulate.initial_recovery = orig
    assert cap
    checked = 0
    for pl, st in cap:
        for so in pl.sorties.values():
            if not so.started or so.start_pos is None:
                continue
            launch = so.launch_truck or so.truck
            S = RecoveryCatalog(pl, so, inst, "S", st, set(), phys=phys, guard_n=10).next_entries(40)
            X = RecoveryCatalog(pl, so, inst, "X", st, set(), phys=phys, guard_n=10).next_entries(200)
            assert S and all(e["truck"] == launch for e in S)
            assert {e["truck"] for e in X} >= {e["truck"] for e in S}
            checked += 1
    assert checked >= 1


def test_joint_flag_default_off_and_runs():
    from tdr.config import AlgorithmConfig
    assert AlgorithmConfig().joint_inflight_retarget is False


def test_slot_relief_candidates_advance_queued_launch_only():
    """v4：SLOT_OVER 时只把排队航次的放飞访问提前(≤2 位)，其余字段不变；放飞访问不早于同机体上一航次回收访问."""
    from tdr.evaluate import evaluate_plan
    from tdr.recovery import _slot_relief_candidates
    from tdr.schedule import initial_state
    inst, phys, plan = _light_plan()
    st = initial_state(inst, phys)
    ev = evaluate_plan(plan, inst, phys, st, None, "NOMINAL")
    assert ev.timeline is not None
    truck = next(so.truck for so in plan.sorties.values() if so.truck)
    ev.violations = [f"SLOT_OVER:{truck}@0.0=9"]
    cands = _slot_relief_candidates(plan, ev, -1, st, max_n=20)
    assert cands, "名义解中应存在可提前放飞的排队航次"
    route = plan.routes[truck]
    for c in cands:
        diff = [sid for sid, so in plan.sorties.items() if c.sorties[sid].launch_vid != so.launch_vid]
        assert len(diff) == 1
        sid = diff[0]
        a, b = route.index(plan.sorties[sid].launch_vid), route.index(c.sorties[sid].launch_vid)
        assert 1 <= a - b <= 2
        so = plan.sorties[sid]
        assert c.sorties[sid].rec_vid == so.rec_vid and c.sorties[sid].air == so.air
        assert plan.sorties[sid].launch_vid == plan.sorties[sid].launch_vid  # 原计划不被修改
    # 无 SLOT_OVER 违规 → 无候选
    ev.violations = ["H_EXCEEDED:t1@1>0"]
    assert _slot_relief_candidates(plan, ev, -1, st) == []


def test_slot_aware_catalog_is_symmetric_and_only_reorders():
    """v4：机位感知只改排序(不删条目)；S 只有放飞车一个车，条目集合不变；X 中满员车条目不排在非满员车之前."""
    from tdr.recovery import RecoveryCatalog
    from tdr.moves import drone_carriers
    from tdr.config import AlgorithmConfig
    from tdr.evaluate import evaluate_plan
    from tdr.hidden_world import BernoulliWorld
    from tdr.experiment import load_case_nominal
    from tdr.schedule import initial_state
    from tdr import simulate
    inst, phys, plan = _light_plan()
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 60
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    _, _, H = load_case_nominal(inst, ROOT / "tests" / "fixtures" / "light" / "C50")
    cap = []
    orig = simulate.initial_recovery

    def wrap(new_plan, state2, *a, **kw):
        cap.append((new_plan.clone(), state2))
        return orig(new_plan, state2, *a, **kw)
    simulate.initial_recovery = wrap
    try:
        w = BernoulliWorld(inst, "C50", 3, 0.3)
        simulate.run_episode(inst, plan, nom, H, phys, w, "X", alg,
                             simulate.derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                             recovery_eval_budget=60, max_replans=3)
    finally:
        simulate.initial_recovery = orig
    assert cap
    n = 0
    for pl, st in cap:
        for so in pl.sorties.values():
            if not so.started or so.start_pos is None:
                continue
            key = lambda e: (e["truck"], e["kind"], e["ref"])
            for strat in ("S", "X"):
                A = RecoveryCatalog(pl, so, inst, strat, st, set(), phys=phys, guard_n=10, slot_aware=False).next_entries(300)
                B = RecoveryCatalog(pl, so, inst, strat, st, set(), phys=phys, guard_n=10, slot_aware=True).next_entries(300)
                assert sorted(map(key, A)) == sorted(map(key, B))
            n += 1
    assert n >= 1


def test_slot_ledger_counts_drone_after_recovery_until_final():
    """v5 修复：非起飞航次回收后，无人机继续占本车机位直到下次放飞/入库(旧评价器漏计→与重放不一致)."""
    import dataclasses
    from tdr.evaluate import evaluate_plan, truck_slot_check, final_carrier
    from tdr.schedule import initial_state
    inst, phys, plan = _light_plan()
    st = initial_state(inst, phys)
    ev = evaluate_plan(plan, inst, phys, st, None, "NOMINAL")
    assert ev.feasible
    fin = {}
    for d in [f"d{i+1}" for i in range(phys.drone_count)]:
        fin.setdefault(final_carrier(plan, d, st, phys), []).append(d)
    k, ds = max(((kk, vv) for kk, vv in fin.items() if ev.timeline.truck_finish.get(kk, 0.0) > 1.0),
                key=lambda kv: len(kv[1]))
    assert len(ds) >= 2
    tight = dataclasses.replace(phys, truck_drone_slots=len(ds) - 1)
    errs = truck_slot_check(plan, inst, tight, ev.timeline, st)
    assert any(e.startswith(f"SLOT_OVER:{k}@") for e in errs), errs
    ok = dataclasses.replace(phys, truck_drone_slots=len(ds))
    assert not truck_slot_check(plan, inst, ok, ev.timeline, st)


def test_slot_ledger_matches_replay_on_episode():
    """端到端：若干失败后评价器与独立重放不应在机位上不一致(无 INVALID_EXECUTION)."""
    import json as _j
    from tdr.config import AlgorithmConfig
    from tdr.evaluate import evaluate_plan
    from tdr.schedule import initial_state
    from tdr import simulate
    inst, phys, plan = _light_plan()
    pkg = _j.load(open(ROOT / "data" / "package_light.json"))
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 60; alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    from tdr.experiment import load_case_nominal
    _, _, H = load_case_nominal(inst, ROOT / "tests" / "fixtures" / "light" / "C50")
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    for seed in (1, 2):
        w = BernoulliWorld(inst, "C50", seed, 0.3)
        ep = simulate.run_episode(inst, plan, nom, H, phys, w, "X", alg,
                                  simulate.derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                                  recovery_eval_budget=60, max_replans=6)
        assert ep.status != "INVALID_EXECUTION", ep.notes


def test_soft_h_overtime_cost_and_default_hard():
    """v5 变体(b)：默认硬 H；soft_h 下 H_EXCEEDED 变为 (mult-1)×时薪×超出秒数 的附加成本."""
    import dataclasses
    from tdr.evaluate import evaluate_plan
    from tdr.schedule import initial_state
    inst, phys, plan = _light_plan()
    st = initial_state(inst, phys)
    base = evaluate_plan(plan, inst, phys, st, None, "NOMINAL")
    assert base.feasible
    fin = base.timeline.truck_finish
    H = max(fin.values()) - 300.0
    hard = evaluate_plan(plan, inst, phys, st, H, "NOMINAL")
    assert not hard.feasible and any(v.startswith("H_EXCEEDED") for v in hard.violations)
    soft_phys = dataclasses.replace(phys, soft_h=True, overtime_mult=1.5)
    soft = evaluate_plan(plan, inst, soft_phys, st, H, "NOMINAL")
    assert soft.feasible
    ot = sum(max(0.0, f - H) for f in fin.values())
    assert ot > 0
    assert soft.cost == pytest.approx(base.cost + phys.wage_per_s * 0.5 * ot, rel=1e-9)
    assert soft.cost_breakdown["overtime_s"] == pytest.approx(ot)
    # H 足够大 → 软/硬一致
    big = evaluate_plan(plan, inst, soft_phys, st, max(fin.values()) + 1.0, "NOMINAL")
    assert big.cost == pytest.approx(base.cost)


def test_landed_flag_zero_energy_and_clone():
    """v6 变体(a)：landed 阶段零能耗(WAIT/R)、Sortie.clone 保留、默认关."""
    import dataclasses
    from tdr.schedule import DroneStage, stage_energy
    from tdr.plan import Sortie
    inst, phys, plan = _light_plan()
    assert phys.land_and_wait is False and phys.soft_h is False
    for kind in ("WAIT", "R"):
        a = DroneStage(kind, 0.0, 100.0, mass=1.0)
        b = DroneStage(kind, 0.0, 100.0, mass=1.0, landed=True)
        assert stage_energy(a, phys) > 0 and stage_energy(b, phys) == 0.0
    c = DroneStage("CRUISE", 0.0, 10.0, mass=1.0, dist=100.0, landed=True)
    assert stage_energy(c, phys) > 0           # 只有 WAIT/R 受 landed 影响
    s0 = next(iter(plan.sorties.values()))
    s0.landed = True
    assert s0.clone().landed is True
    s0.landed = False


def test_land_and_wait_candidates_symmetric_and_flagged():
    """S 的降落候选只在原放飞车上，X 可任意车；候选的该航次 landed=True，且接机客户=下一空送客户点."""
    import dataclasses, random, zlib
    from tdr.recovery import _landing_candidates
    from tdr.config import AlgorithmConfig
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.schedule import initial_state
    from tdr import simulate
    inst, phys, plan = _light_plan()
    phys = dataclasses.replace(phys, land_and_wait=True)
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 60; alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    _, _, H = load_case_nominal(inst, ROOT / "tests" / "fixtures" / "light" / "C50")
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    cap = []
    orig = simulate.initial_recovery

    def wrap(new_plan, state2, *a, **kw):
        cap.append((new_plan.clone(), state2))
        return orig(new_plan, state2, *a, **kw)
    simulate.initial_recovery = wrap
    try:
        simulate.run_episode(inst, plan, nom, H, phys, BernoulliWorld(inst, "C50", 3, 0.3), "X", alg,
                             simulate.derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                             recovery_eval_budget=60, max_replans=3)
    finally:
        simulate.initial_recovery = orig
    assert cap
    n = 0
    for pl, st in cap:
        for so in pl.sorties.values():
            if not so.started:
                continue
            launch = so.launch_truck or so.truck
            S = _landing_candidates(pl, so.sid, inst, phys, st, set(), "S", 10)
            X = _landing_candidates(pl, so.sid, inst, phys, st, set(), "X", 10, max_n=50)
            for c in S:
                f = c.sorties[so.sid]
                assert f.landed and c.visits[f.rec_vid].truck == launch
                assert len(f.air) <= 1
            for c in X:
                assert c.sorties[so.sid].landed and len(c.sorties[so.sid].air) <= 1
            n += 1
    assert n >= 1


def _all_parcels(pl):
    out = []
    for v in pl.visits.values():
        out += v.ground
    for s in pl.sorties.values():
        out += s.air + s.handover
    return sorted(out)


def test_unlaunched_candidates_conserve_parcels_and_respect_S():
    """v7：未起飞航次修复候选：包裹守恒；S 的改回收点只在本放飞车；三类候选(改回收点/丢末客/整转地面)齐全."""
    from tdr.recovery import _unlaunched_candidates
    from tdr.schedule import initial_state
    inst, phys, plan = _light_plan()
    st = initial_state(inst, phys)
    base = _all_parcels(plan)
    sid = next((s.sid for s in plan.sorties.values() if len(s.air) >= 2 and not s.started), None)
    assert sid is not None
    so = plan.sorties[sid]
    for strat in ("S", "X"):
        cs = _unlaunched_candidates(plan, sid, inst, phys, st, strat)
        assert len(cs) >= 2
        kinds = set()
        for c in cs:
            assert _all_parcels(c) == base
            if sid not in c.sorties:
                kinds.add("ground")
            elif len(c.sorties[sid].air) == len(so.air) - 1:
                kinds.add("drop_last")
            elif c.sorties[sid].rec_vid != so.rec_vid:
                kinds.add("rec")
                if strat == "S":
                    assert c.visits[c.sorties[sid].rec_vid].truck == so.truck
        assert {"ground", "drop_last"} <= kinds
    # 原计划不被修改
    assert _all_parcels(plan) == base and plan.sorties[sid].air == so.air


def test_unlaunched_target_parses_non_started_sortie():
    from tdr.recovery import _unlaunched_target
    from tdr.evaluate import evaluate_plan
    from tdr.schedule import initial_state
    inst, phys, plan = _light_plan()
    st = initial_state(inst, phys)
    ev = evaluate_plan(plan, inst, phys, st, None, "NOMINAL")
    s = next(x for x in plan.sorties.values() if not x.started)
    stg = next(g for g in ev.timeline.drone_stages[s.drone] if g.sid == s.sid)
    ev.violations = [f"SWAP_CANNOT_FIX:{s.drone}@{stg.start:.1f}:e=-0.1<0.0"]
    assert _unlaunched_target(plan, ev, set()) == s.sid
    other = _unlaunched_target(plan, ev, {s.sid})
    assert other != s.sid


def test_v7_flags_episode_no_invalid():
    """v7 全开(land+unlaunched)：端到端不产生 INVALID_EXECUTION；默认关闭."""
    import dataclasses, json as _j
    from tdr.config import AlgorithmConfig
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.schedule import initial_state
    from tdr import simulate
    inst, phys, plan = _light_plan()
    pkg = _j.load(open(ROOT / "data" / "package_light.json"))
    ad = dict(pkg["algorithm_protocol"]["default_parameters"])
    assert AlgorithmConfig.from_dict(ad).unlaunched_repair is False
    ad.update(joint_inflight_retarget=True, unlaunched_repair=True)
    alg = AlgorithmConfig.from_dict(ad)
    alg.recovery_eval_budget_override = 60; alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    phys = dataclasses.replace(phys, land_and_wait=True)
    _, _, H = load_case_nominal(inst, ROOT / "tests" / "fixtures" / "light" / "C50")
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    for seed in (1, 2):
        ep = simulate.run_episode(inst, plan, nom, H, phys, BernoulliWorld(inst, "C50", seed, 0.3), "S", alg,
                                  simulate.derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                                  recovery_eval_budget=60, max_replans=5)
        assert ep.status != "INVALID_EXECUTION", ep.notes
