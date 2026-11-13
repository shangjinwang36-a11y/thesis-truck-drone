"""第四轮修复的回归测试."""
import json
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld, TestWorld
from tdr.schedule import initial_state
from tdr import simulate

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


def _gh(case, budget=1000):
    pkg = json.load(open(ROOT / "data" / "package_gh200_light1.json"))
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = budget
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, FIX / "gh200L1" / case)
    return pkg, phys, alg, inst, plan, H


def _gh_episode(case, seed, strat, budget=1000):
    pkg, phys, alg, inst, plan, H = _gh(case, budget)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    world = HiddenWorld(inst, case, seed)
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    return simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg, rngs, recovery_eval_budget=budget)


@pytest.mark.parametrize("seed", [2, 8])
def test_h2_ghost_sortie_no_fragment(seed):
    """失败机旧计划里之后的航次(幽灵)不能覆盖失败航次(修复前 INITIAL_RECOVERY_FAILED:NO_FRAGMENT)."""
    ep = _gh_episode("C200", seed, "S")
    assert not any("NO_FRAGMENT" in n for n in ep.notes), ep.notes
    assert ep.status == "COMPLETED_VERIFIED", (ep.status, ep.notes)


# ------------------------------------------------------------------ 失败事件快照截获（供候选级回归测试复用）
class _Stop(Exception):
    pass


def _spec(case):
    pkg = json.load(open(ROOT / "data" / "package.json"))
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 1000
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, FIX / "spec" / case)
    return pkg, phys, alg, inst, plan, H


def capture_first_event(pkgfn, case, failed, strat="S"):
    """运行到第一次恢复调用即停，返回 (inst, phys, H, new_plan, state, ground_required, kw)."""
    pkg, phys, alg, inst, plan, H = pkgfn(case)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "N")
    world = TestWorld(inst, case, tuple(failed))
    got = []
    orig = simulate.initial_recovery

    def hook(np_, st, i_, p_, strategy, gr, **kw):
        got.append((np_.clone(), st, set(gr), kw))
        raise _Stop()
    simulate.initial_recovery = hook
    try:
        simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg,
                             simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                             recovery_eval_budget=1000)
    except _Stop:
        pass
    finally:
        simulate.initial_recovery = orig
    if not got:
        return None
    np_, st, gr, kw = got[0]
    return inst, phys, H, np_, st, gr, kw


def test_m4_same_truck_custody_no_false_reject():
    """同车接机：残段里已预置在接机点之前的旧地送必须清除(修复前 spec C50 约 43/190 个同车候选被误判 G_CUSTODY)."""
    from tdr import recovery as R
    import random
    case = "C50"
    pkg, phys, alg, inst, plan, H = _spec(case)
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    n_custody = n_ok = 0
    for seed in range(8):
        f = random.Random(seed).sample(air, 2)
        cap = capture_first_event(_spec, case, f)
        if cap is None:
            continue
        inst, phys, H, np_, st, gr, kw = cap
        frag = next(s for s in np_.sorties.values() if s.sid == kw["frag_sid"])
        res = R.prepare_residual(np_, inst)
        launch = frag.launch_truck or frag.truck
        rem = [p for p in frag.air if p not in gr]
        for vid in res.routes.get(launch, []):
            for sv in ([], rem[:1], rem):
                ent = dict(truck=launch, kind="visit", ref=vid, support=False, served=list(sv))
                for cp in R.build_residual_candidate(res, frag.sid, ent, inst, phys, st, gr, "S"):
                    e = evaluate_plan(cp, inst, phys, st, H, "T")
                    n_ok += e.feasible
                    n_custody += e.status == "INVALID_CUSTODY"
    assert n_ok > 50
    assert n_custody == 0


def test_m3_sa_scale_excludes_prefix():
    from tdr.alns import prefix_fixed_cost
    from tdr.schedule import StartState
    pkg, phys, alg, inst, plan, H = _spec("C50")
    assert prefix_fixed_cost(StartState(t0=0.0), phys) == 0.0
    st = StartState(t0=1000.0, prefix_distance_m=5000.0, prefix_ac_kwh=1.0,
                    truck_start_pos={"t1": (0, 0), "t2": (0, 0)}, truck_done={"t2": 800.0})
    exp = (phys.c_km * 5.0 + phys.wage_per_s * (1000.0 + 800.0)
           + phys.cost_vehicle_kwh * phys.slot_efficiency * 1.0)
    assert prefix_fixed_cost(st, phys) == pytest.approx(exp)
    assert prefix_fixed_cost(st, phys) > 0


def test_l1_validate_structure_chain_order():
    """同机同车相邻航次：后一航次放飞访问早于前一航次回收访问 → 结构校验报错."""
    pkg, phys, alg, inst, plan, H = _spec("C50")
    assert not [e for e in plan.validate_structure(inst, phys) if "链次序" in e]
    found = False
    for d, sids in plan.drone_sorties.items():
        for a, b in zip(sids, sids[1:]):
            s1, s2 = plan.sorties[a], plan.sorties[b]
            if s1.launch_vid is None or s2.launch_vid is None:
                continue
            r1, l2 = s1.rec_vid, s2.launch_vid
            if r1 == l2 or plan.visits[r1].truck != plan.visits[l2].truck:
                continue
            rt = plan.routes[plan.visits[r1].truck]
            i, j = rt.index(r1), rt.index(l2)
            rt[i], rt[j] = rt[j], rt[i]
            errs = plan.validate_structure(inst, phys)
            assert any("链次序" in e for e in errs), errs
            found = True
            break
        if found:
            break
    assert found


def test_wait_cap_follows_spec_null():
    """规范 fixed_wait_cap_s=null：默认不设能量修复等待上限；旧 3600 s 上限仅为显式敏感性选项."""
    pkg, phys, alg, inst, plan, H = _spec("C50")
    assert phys.energy_wait_cap_s is None
    import dataclasses
    assert dataclasses.replace(phys, energy_wait_cap_s=3600.0).energy_wait_cap_s == 3600.0


def test_stopped_max_replans_label():
    import inspect
    src = inspect.getsource(simulate.run_episode)
    assert "STOPPED_MAX_REPLANS" in src


def test_h4_cross_truck_candidates_include_release_credit():
    """规范 C50 / HiddenWorld seed 3：穷举(oracle)最优 X=196.3；修复前代码初始 X=208.7，修复后应≈197.9(<200)，S=226.0 不变."""
    from tdr import recovery as R
    from tdr.alns import Budget, SearchStats
    pkg = json.load(open(ROOT / "data" / "package.json"))
    case = "C50"
    phys = PhysicalConfig.from_dict(dict(pkg["config"]))
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 1000
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, nc, H = load_case_nominal(inst, FIX / "spec_m03" / case)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "N")
    out = {}
    for strat in "SX":
        got = []
        orig = simulate.initial_recovery

        def hook(np_, st, i_, p_, s, gr, **kw):
            got.append((np_.clone(), st, set(gr), kw))
            raise _Stop()
        simulate.initial_recovery = hook
        try:
            simulate.run_episode(inst, plan, nom, H, phys, HiddenWorld(inst, case, 3), strat, alg,
                                 simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                                 recovery_eval_budget=1000, cut_mode="cascade")
        except _Stop:
            pass
        finally:
            simulate.initial_recovery = orig
        np_, st, gr, kw = got[0]
        opt, _, _ = R.initial_recovery(np_, st, inst, phys, strat, gr, H=H, frag_sid=kw["frag_sid"],
                                       stats=SearchStats(), budget=Budget(alg.recovery_init_eval_budget, None),
                                       rescue_evals=1000, info={}, use_milp=True, extra_pool=kw.get("extra_pool"))
        out[strat] = opt.ev.cost
    assert out["S"] == pytest.approx(226.01, abs=0.05)
    assert out["X"] < 200.0, out


def test_h4_continue_subsets_prefixes():
    from tdr.recovery import _continue_subsets
    rem = ["a", "b", "c", "d", "e", "f"]
    subs = _continue_subsets(rem)
    assert [] in subs and ["a"] in subs and rem in subs
    for k in range(2, 6):
        assert rem[:k] in subs
    assert len({tuple(s) for s in subs}) == len(subs)


def test_h1_snapshot_at_failure_time_no_cascade():
    """H1：快照取失败时刻；回放核验通过(以前级联顺延 243.9 s)；在途动作按各自剩余时长承诺."""
    ep = _gh_episode("C200", 2, "S")
    assert ep.status == "COMPLETED_VERIFIED", (ep.status, ep.notes)
    assert ep.replans[1:], "应发生重规划"
    for rp in ep.replans[1:]:
        assert rp.t_cut == pytest.approx(rp.time_s)
    old = _gh_episode_cut("C200", 2, "S", "cascade")
    assert old.replans[1].t_cut - old.replans[1].time_s > 100.0     # 旧口径的级联顺延确实很大(243.9 s)


def _gh_episode_cut(case, seed, strat, cut_mode, budget=1000):
    pkg, phys, alg, inst, plan, H = _gh(case, budget)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    world = HiddenWorld(inst, case, seed)
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    return simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg, rngs,
                                recovery_eval_budget=budget, cut_mode=cut_mode)


def test_h1_commit_times_only_straddling_entities():
    from tdr.simulate import compute_commit_times
    pkg, phys, alg, inst, plan, H = _gh("C200")
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "N")
    tl = ev.timeline
    # 选一个正落在某卡车 G/P/R/U 内部的时刻
    acts = [a for a in tl.actions if a.kind in ("G", "P", "R", "U") and a.end - a.start > 5]
    a = acts[len(acts) // 2]
    t = 0.5 * (a.start + a.end)
    t_cut, Tt, Td = compute_commit_times(tl, t, "d_none")
    assert t_cut == t
    assert Tt.get(a.actor, 0) >= a.end - 1e-9
    # 非级联：任何实体的顺延都 ≤ 该实体自己某个动作的结束，且卡车顺延不会被别的卡车拖长
    for k, v in Tt.items():
        own = [x.end for x in tl.actions if x.actor == k and x.kind in ("G", "P", "R", "U", "W") and x.start < t < x.end]
        assert own and v <= max(own) + 60.0     # 只允许 R→U 并入
    assert all(v >= t for v in list(Tt.values()) + list(Td.values()))


def test_h1_second_failure_during_committed_action():
    """H1：第一次失败时卡车 t3 的 G 被承诺到 553.2 s；第二次失败(545.5 s)发生在承诺期内——
    t3 必须仍停在原地(此前误取仓库位置 → DRIVE_ORIGIN)，回放核验通过(轻型 RC50 / forced5 / seed1)."""
    import random as _r
    import zlib
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    case = "RC50"
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 1000
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, nc, H = load_case_nominal(inst, FIX / "light_rc50" / case)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "N")
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    failed = tuple(_r.Random(zlib.crc32(f"{case}:1:5".encode())).sample(air, 5))
    ep = simulate.run_episode(inst, plan, nom, H, phys, TestWorld(inst, case, failed), "S", alg,
                              simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                              recovery_eval_budget=1000)
    assert ep.status == "COMPLETED_VERIFIED", (ep.status, ep.notes[:2])
    assert any(abs(r.time_s - 545.5) < 1.0 for r in ep.replans)   # 确实发生了承诺期内的第二次失败
