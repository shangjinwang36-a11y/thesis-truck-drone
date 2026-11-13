#!/usr/bin/env python3
"""Round 2 配对实验：名义生成 + 失败回合（Bernoulli p=0.2，S/X 同种子 CRN）。"""
from __future__ import annotations
import argparse, json, os, sys, time, math, statistics
from pathlib import Path
from multiprocessing import Pool

ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, ROOT + "/src")
os.chdir(ROOT)

CASES_DEFAULT = "C50,R50,RC50,C100,R100,RC100"

# 共享调参（A4）；A0–A3 用协议默认值
TUNED_SHARED = {
    "destroy_fraction_min": 0.10,   # 保持默认（试探后不改，避免无对照的乱调）
    "destroy_fraction_max": 0.30,
    "cross_period": 4,              # 默认 5 → 4：两阶段后段更频繁尝试跨车/改派
    "cross_n": 3,                   # 默认 2 → 3
    "nominal_two_phase_b": 200,     # 预算 1000 时阶段2 = 200（与既有 v2_b200 切分一致）
}

PRESETS = {
    "A0": {"label": "round1 修复 only",
           "v7": False, "x_nom": False, "x_rec": False, "tuned": False},
    "A1": {"label": "A0 + v7 对称恢复算子",
           "v7": True, "x_nom": False, "x_rec": False, "tuned": False},
    "A2": {"label": "A0 + X 名义（从 S 出发、改进才接受、必要时采用 S）",
           "v7": False, "x_nom": True, "x_rec": False, "tuned": False},
    "A3": {"label": "A2 + v7 + X 恢复算子（保跨车链 / S 恢复兜底）",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": False},
    "A4": {"label": "A3 + 共享调参",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True},
    "R3": {"label": "A4 + X 工时上限/电量裕度/不新开空送 + 跨车地面算子",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True},
    # 第四轮：名义与 R3 相同（复用 R3 名义解）。恢复把“一票否决”换成按已知 p 计价的新开空送，
    # 并加上地面绕路 vs 跨车再飞的算子。不在评价种子上调任何常数。
    "R4": {"label": "R3 名义 + X 风险价新开空送 + 绕路再飞",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True},
    # 第五轮诊断预设，不是最终设计。名义文件仍是 R3。发布时若 X 名义含跨车航次，改用 S 的名义。
    # 这会删掉名义跨车。论文要保留失败前的跨车，所以这个预设只用来记录“整份退回同车”的代价。
    # 开关依据来自调参种子 101–110。恢复仍可跨车。
    "R5": {"label": "诊断：含跨车的名义整份退回 S（不作为最终设计）",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True, "r5": True},
    # 第六轮：诊断回退保持关闭。名义跨车按航次做稳健性检查，并允许两机互换回收车。
    "R6": {"label": "名义跨车按航次稳健 + 互换回收车",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True, "r6": True},
    # 第七轮：在第 6 轮的检查之上，X 从阶段1 就开始跨车。S 的阶段1 仍是同车。
    "R7": {"label": "第6轮 + X 阶段1 也允许跨车",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True, "r6": True, "r7": True},
    # 第八轮：S 与 X 都做情景估价和列池集合划分。X 仍然可以跨车，S 的列里没有跨车航次。
    "R8": {"label": "情景估价 ALNS + 列池集合划分",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True, "r6": True, "r7": True, "r8": True},
    "R9": {"label": "会合访问 + 近邻成对破坏",
           "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True, "r6": True, "r7": True, "r8": True, "r9": True},
    # 只在调参种子上和 R9 比较。上限是评价班次 H，不是 Cmax(S)。正式评价用比较之后选定的那一个。
    "R9H": {"label": "R9 + 搜索/发布上限改为评价班次 H",
            "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True, "r6": True, "r7": True, "r8": True, "r9": True, "r9h": True},
    # 第 10 轮：在第 9 轮选定的班次上限上，只改 X 的会合几何和同车发布门。不重选上限，不扫参数。
    "R10": {"label": "R9 + 短回程会合 + 同车期望门",
            "v7": True, "x_nom": True, "x_rec": True, "tuned": True, "r3": True, "r4": True, "r6": True, "r7": True, "r8": True, "r9": True, "r10": True},
}


def configs(pkg, preset: str):
    from tdr.config import PhysicalConfig, AlgorithmConfig
    import dataclasses
    phys = PhysicalConfig.from_dict(pkg["config"])
    ad = dict(pkg["algorithm_protocol"]["default_parameters"])
    ps = PRESETS[preset]
    if ps["v7"]:
        ad.update(joint_inflight_retarget=True, slot_aware_recovery=True, unlaunched_repair=True)
        phys = dataclasses.replace(phys, land_and_wait=True)
    if ps["x_nom"]:
        ad.update(x_improve_only_cross=True, x_adopt_s_nominal=True, nominal_two_phase_b=200)
    if ps["x_rec"]:
        ad.update(x_preserve_cross_repair=True, x_keep_s_recovery=True)
    if ps["tuned"]:
        ad.update(TUNED_SHARED)
    elif not ps["x_nom"]:
        ad.update(nominal_two_phase_b=200)
    if ps.get("r3"):
        # X 专属。cross_ops 对 S 恒不触发（接机车=放飞车），不占用 S 的评价。
        # x_new_air_penalty=0：第三轮正式实验是硬禁止新开空送，不是 12 元/票。
        ad.update(x_cross_hs_cap=True, x_cross_energy_margin_frac=0.05,
                  x_limit_new_air=True, x_new_air_penalty=0.0, cross_ops=True)
    if ps.get("r4"):
        # 已知伯努利概率，不是在种子上拟合的。x_new_air_penalty 仍为 0，因此
        # simulate 里的 x_limit_new_air 继续硬禁止通用修复新开空送；
        # 风险价只约束再飞算子提出的那一票。硬禁止没有关掉。
        ad.update(x_risk_price_air=True, failure_prob=0.2, x_new_air_penalty=0.0)
    if ps.get("r5"):
        ad.update(x_adopt_s_if_cross=True)
    if ps.get("r6"):
        # 整份退回同车保持关闭。slack 的秒数可以在调参种子上改这一处，不在评价种子上改。
        ad.update(x_adopt_s_if_cross=False, x_cross_robust=True,
                  x_rendezvous_slack_s=90.0, x_cross_exchange=True,
                  x_exchange_cost_tau=2.0)
    if ps.get("r7"):
        # 阶段1 也跨车。稳健检查和 τ 仍是第 6 轮那一组，不在评价种子上改。
        ad.update(x_cross_from_start=True)
    if ps.get("r8"):
        # S/X 同一套情景样本和同一套集合划分。S 不生成跨车列。
        # 名义上比 S 贵不再整份退回：情景均值已经把失败后的代价算进接受准则。
        # 完工时刻仍不得超过 S，评价用的 H 还是 H_S。
        ad.update(scenario_aware=True, set_partition=True,
                  scenario_count=2, scenario_p=0.2, scenario_stream=0,
                  scenario_infeasible_penalty=400.0, set_partition_period=5,
                  x_adopt_s_nominal=False)
    if ps.get("r9"):
        # 会合访问和近邻破坏对 S、X 都开，S 只能在放飞车上插访问。
        # S 不再发布比阶段 1 真实成本更贵的情景方案。
        ad.update(support_rendezvous=True, joint_near_destroy=True,
                  pair_handoff=True, s_keep_true_cost=True,
                  convert_polish_n=20, x_s_second_start=True,
                  scenario_eval_cap=200, scenario_screen_yuan=20.0,
                  scenario_elite_refill=True,
                  expected_accept=True, expected_reeval_every=80,
                  x_exchange_cost_tau=0.0, x_improve_only_cross=False,
                  # 种子 101–110 上两种上限比过。评价班次 H 的 60 对 Δ/C_S 更低，所以正式用它。
                  x_cap_is_shift=True)
    if ps.get("r9h"):
        ad.update(x_cap_is_shift=True)
    if ps.get("r10"):
        # 几何和发布门都只在 X 的跨车路径上读。S 的搜索不进入这两支。
        ad.update(x_short_return=True, x_same_truck_j_gate=True)
    alg = AlgorithmConfig.from_dict(ad)
    alg.recovery_eval_budget_override = None
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    alg.reassign_adopt_only_if_best = True
    return phys, alg, ad, ps


def build_one(args):
    pkg_path, preset, case, budget, out_root = args
    from tdr.config import PhysicalConfig
    from tdr.data import load_instance
    from tdr.experiment import build_case_nominal
    pkg = json.load(open(pkg_path))
    phys, alg, ad, ps = configs(pkg, preset)
    inst = load_instance(pkg, case)
    phys = phys.for_case(pkg.get("case_fleet"), case)
    base = Path(out_root) / preset / "nominal"
    t0 = time.perf_counter()
    ms = build_case_nominal(inst, phys, alg, base / "S" / case, eval_budget=budget,
                            cross_launch=False, two_phase_b=ad.get("nominal_two_phase_b") or 200)
    mx = build_case_nominal(inst, phys, alg, base / "X" / case, eval_budget=budget,
                            cross_launch=True, two_phase_b=ad.get("nominal_two_phase_b") or 200,
                            adopt_from=(base / "S" / case) if ps["x_nom"] else None)
    return {"preset": preset, "case": case, "S": ms, "X": mx, "wall": time.perf_counter() - t0}


def _max_replans_value(spec, n_cust: int) -> int:
    if spec is None or str(spec) in ("n_cust", "n_customers", "auto"):
        return int(n_cust)
    if str(spec) in ("unlimited", "none", "inf"):
        return 10**9
    return int(spec)


def ep_one(args):
    pkg_path, preset, case, seed, budget, nom_root, failure_mode, p = args[:8]
    max_replans_spec = args[8] if len(args) > 8 else "n_cust"
    from tdr.data import load_instance
    from tdr.experiment import load_case_nominal, episode_metrics, nominal_and_recovery
    from tdr.evaluate import evaluate_plan, is_cross_sortie
    from tdr.hidden_world import make_world, bernoulli_failure_flags, HiddenWorld
    from tdr.schedule import initial_state
    from tdr import simulate
    pkg = json.load(open(pkg_path))
    phys, alg, ad, ps = configs(pkg, preset)
    inst = load_instance(pkg, case)
    phys = phys.for_case(pkg.get("case_fleet"), case)
    # 风险价用的就是这一次世界的失败概率，不另设一个在种子上调出来的数。
    if alg.x_risk_price_air:
        alg.failure_prob = float(p)
    alg.recovery_eval_budget_override = budget
    noms = {}
    for st_ in ("S", "X"):
        pl, nc, Hs = load_case_nominal(inst, Path(nom_root) / st_ / case)
        noms[st_] = (pl, nc, Hs)
    H = noms["S"][2]
    out = dict(preset=preset, case=case, seed=seed, n_cust=len(inst.customers),
               H_S=noms["S"][2], H_X=noms["X"][2], failure_mode=failure_mode, p=p)
    # 隐失败集合由 (case, seed, p) 决定，与计划无关；每个策略用新的 world 实例（同种子），避免 finish_episode 关闭后无法给另一策略用
    if failure_mode == "bernoulli":
        hidden = sorted(bernoulli_failure_flags(case, seed, [c.parcel_id for c in inst.customers], p))
    else:
        hidden = sorted(HiddenWorld(inst, case, seed).finish_episode().hidden_failure_parcels)
    out["hidden_failure_parcels"] = hidden
    plan_s, plan_x = noms["S"][0], noms["X"][0]
    # R 的克隆要在 S 的回合改写计划对象之前做好。三个策略共用同一个恢复评价上限。
    # 本轮正式回合只跑调用方点名的策略。X0 与 R 在当前名义构造下相同，不默认加进 60 对。
    named = args[9] if len(args) > 9 and args[9] else "S,R,X"
    strategies = tuple(part for part in str(named).split(",") if part)
    prepared = {
        strat: nominal_and_recovery(strat, plan_s, plan_x, bool(alg.x_adopt_s_if_cross))
        for strat in strategies
    }
    for strat, (plan, recovery_strategy) in prepared.items():
        nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
        air = sorted({p for s in plan.sorties.values() for p in s.air})
        out[strat + "_nominal"] = dict(
            cost=nom_ev.cost, feasible=nom_ev.feasible, air=len(air), H=H,
            n_cross=sum(1 for s in plan.sorties.values() if is_cross_sortie(plan, s)),
            n_sorties=len(plan.sorties))
        if not nom_ev.feasible:
            out[strat] = dict(status="NOMINAL_INFEASIBLE_UNDER_H", cost=None, notes=nom_ev.violations[:2])
            continue
        served_hidden = sorted(set(air) & set(hidden or []))
        out[strat + "_nominal"]["air_hidden"] = served_hidden
        max_replans = _max_replans_value(max_replans_spec, len(inst.customers))
        out["max_replans"] = max_replans
        t0 = time.perf_counter()
        world = make_world(inst, case, seed, failure_mode, p)
        rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
        try:
            ep = simulate.run_episode(inst, plan, nom_ev, H, phys, world, recovery_strategy, alg, rngs,
                                      recovery_eval_budget=budget, cut_mode="snapshot",
                                      max_replans=max_replans, ground_finish=True)
        except Exception as e:
            out[strat] = dict(status="ERROR", cost=None, error=repr(e)[:400], wall=time.perf_counter() - t0)
            continue
        ok = ep.status == "COMPLETED_VERIFIED"
        m = episode_metrics(ep)
        inc = None
        if ok and ep.evaluation and nom_ev.cost is not None:
            inc = ep.evaluation.cost - nom_ev.cost
        n_replans = max(0, len(ep.replans) - 1)
        n_evals = 0
        init_sources = []
        for rec in ep.replans[1:]:
            stt = rec.stats or {}
            n_evals += int(stt.get("n_eval_requests") or 0)
            if stt.get("init_source"):
                init_sources.append(stt["init_source"])
        n_cross_final = None
        if ep.plan is not None:
            # 已起飞残段的 truck 会被改写成接机车，is_cross_sortie 故意不计。
            # 回合结束时的跨车次数用放飞车 launch_truck 对照回收车。
            from tdr.evaluate import recovery_is_cross
            n_cross_final = sum(1 for s in ep.plan.sorties.values() if recovery_is_cross(ep.plan, s))
        notes = list(ep.notes or [])
        rec_reasons = []
        for nt in notes:
            if nt.startswith("INITIAL_RECOVERY_FAILED:"):
                rec_reasons.extend([x for x in nt.split(":", 1)[1].split(",") if x])
        n_obs_fail = sum(1 for o in ep.observations if not getattr(o, "air_delivery_available", True))
        out[strat] = dict(status=ep.status,
                          cost=ep.evaluation.cost if (ok and ep.evaluation) else None,
                          inc=inc, verified=ok, notes=notes[:8],
                          wall=time.perf_counter() - t0,
                          n_replans=n_replans, n_evals=n_evals,
                          n_fail_events=m.get("n_fail_events"), n_fail_cross=m.get("n_fail_cross"),
                          n_fail_rec=m.get("n_fail_rec"),
                          n_cross_final=n_cross_final,
                          rec_reasons=rec_reasons[:8],
                          init_sources=init_sources,
                          hit_cap=(ep.status == "STOPPED_MAX_REPLANS"),
                          n_obs_fail=n_obs_fail,
                          max_replans=max_replans,
                          ground_finish_cost=ep.ground_finish_cost,
                          ground_finish_status=ep.ground_finish_status,
                          cost_fair=(ep.evaluation.cost if (ok and ep.evaluation) else ep.ground_finish_cost))
    return out


def replay_one(args):
    """只重放一个已经停止的策略，用来在同一停点上做地面收尾。完成的回合不走这里。"""
    pkg_path, preset, case, seed, budget, nom_root, failure_mode, p, max_replans_spec, strat = args
    from tdr.data import load_instance
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal, nominal_and_recovery
    from tdr.hidden_world import make_world
    from tdr.schedule import initial_state
    from tdr import simulate
    pkg = json.load(open(pkg_path))
    phys, alg, ad, ps = configs(pkg, preset)
    inst = load_instance(pkg, case)
    phys = phys.for_case(pkg.get("case_fleet"), case)
    if alg.x_risk_price_air:
        alg.failure_prob = float(p)
    alg.recovery_eval_budget_override = budget
    plan_s, _, Hs = load_case_nominal(inst, Path(nom_root) / "S" / case)
    plan_x, _, _ = load_case_nominal(inst, Path(nom_root) / "X" / case)
    plan, recovery_strategy = nominal_and_recovery(strat, plan_s, plan_x, bool(alg.x_adopt_s_if_cross))
    nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), Hs, "NOMINAL")
    max_replans = _max_replans_value(max_replans_spec, len(inst.customers))
    world = make_world(inst, case, seed, failure_mode, p)
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    ep = simulate.run_episode(inst, plan, nom_ev, Hs, phys, world, recovery_strategy, alg, rngs,
                              recovery_eval_budget=budget, cut_mode="snapshot",
                              max_replans=max_replans, ground_finish=True)
    return {
        "case": case, "seed": seed, "strategy": strat,
        "status": ep.status,
        "notes": list(ep.notes or [])[:4],
        "ground_finish_cost": ep.ground_finish_cost,
        "ground_finish_status": ep.ground_finish_status,
    }


def mean_ci(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n == 0:
        return None, None, None, 0
    m = sum(xs) / n
    if n < 2:
        return m, None, None, n
    sd = statistics.stdev(xs)
    # 正态近似 95% CI
    h = 1.96 * sd / math.sqrt(n)
    return m, m - h, m + h, n


def _sign_p(n_x, n_s):
    n = n_x + n_s
    if n == 0:
        return None
    try:
        from scipy.stats import binomtest
        return float(binomtest(n_x, n, 0.5).pvalue)
    except Exception:
        return None


def _paired(rs, left, right):
    """Δ = C_right − C_left。负数表示 right 更便宜。分母仍是 S 的名义成本。"""
    deltas, rels = [], []
    for r in rs:
        a = (r.get(left) or {}).get("cost")
        b = (r.get(right) or {}).get("cost")
        if a is None or b is None:
            continue
        deltas.append(b - a)
        ns = (r.get("S_nominal") or {}).get("cost")
        if ns:
            rels.append((b - a) / ns)
    md, lo, hi, n = mean_ci(deltas)
    mr, rlo, rhi, _ = mean_ci(rels)
    n_neg = sum(1 for d in deltas if d < -1e-9)
    n_pos = sum(1 for d in deltas if d > 1e-9)
    return {
        "n": n, "delta_mean": md, "delta_ci95": [lo, hi],
        "delta_over_CS_mean": mr, "delta_over_CS_ci95": [rlo, rhi],
        "sign_right_better": n_neg, "sign_left_better": n_pos,
        "sign_tie": len(deltas) - n_neg - n_pos,
        "sign_p_two_sided": _sign_p(n_neg, n_pos),
    }


def _same_truck_nominal(rs):
    """X 的增益里，有多少来自更便宜的同车名义，而不是名义跨车。

    只统计 S、R、X 都完成的回合。同车更便宜：已发布的 X 名义没有跨车，且名义成本低于 S。
    这一组的 R→X 用的是同一套 X 恢复规则，差别只在名义计划，所以它是同车名义的失败后贡献。
    """
    buckets = {"same_truck_cheaper": [], "nominal_cross": [], "same_nominal": []}
    for r in rs:
        s, rg, x = (r.get("S") or {}), (r.get("R") or {}), (r.get("X") or {})
        if s.get("cost") is None or rg.get("cost") is None or x.get("cost") is None:
            continue
        nc = (r.get("X_nominal") or {}).get("n_cross") or 0
        xs = (r.get("X_nominal") or {}).get("cost")
        ss = (r.get("S_nominal") or {}).get("cost")
        row = {
            "sx": x["cost"] - s["cost"],
            "sr": rg["cost"] - s["cost"],
            "rx": x["cost"] - rg["cost"],
            "nom_gap": (None if xs is None or ss is None else xs - ss),
        }
        if nc > 0:
            buckets["nominal_cross"].append(row)
        elif xs is not None and ss is not None and xs < ss - 1e-6:
            buckets["same_truck_cheaper"].append(row)
        else:
            buckets["same_nominal"].append(row)

    def pack(rows_):
        def avg(key):
            xs_ = [z[key] for z in rows_ if z[key] is not None]
            return (sum(xs_) / len(xs_)) if xs_ else None
        return {
            "n": len(rows_),
            "delta_S_to_X_mean": avg("sx"),
            "delta_S_to_R_mean": avg("sr"),
            "delta_R_to_X_mean": avg("rx"),
            "nominal_gap_X_minus_S_mean": avg("nom_gap"),
        }
    return {name: pack(rows_) for name, rows_ in buckets.items()}


def _fairness_report(rows):
    from tdr.fairness import fairness_report
    return fairness_report(rows)


def summarize(rows):
    from collections import Counter, defaultdict
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)

    def agg(rs, tag=""):
        dcost, drel, incS, incX, nomS, nomX, nxs = [], [], [], [], [], [], []
        stopS = stopR = stopX = 0
        stS, stR, stX = Counter(), Counter(), Counter()
        for r in rs:
            s, rg, x = r.get("S") or {}, r.get("R") or {}, r.get("X") or {}
            stS[s.get("status") or "MISSING"] += 1
            stR[rg.get("status") or "MISSING"] += 1
            stX[x.get("status") or "MISSING"] += 1
            if (s.get("status") or "").startswith("STOP"):
                stopS += 1
            if (rg.get("status") or "").startswith("STOP"):
                stopR += 1
            if (x.get("status") or "").startswith("STOP"):
                stopX += 1
            if s.get("cost") is None or x.get("cost") is None:
                continue
            dcost.append(x["cost"] - s["cost"])
            ns = (r.get("S_nominal") or {}).get("cost")
            if ns:
                drel.append((x["cost"] - s["cost"]) / ns)
            if s.get("inc") is not None:
                incS.append(s["inc"])
            if x.get("inc") is not None:
                incX.append(x["inc"])
            if (r.get("S_nominal") or {}).get("cost") is not None:
                nomS.append(r["S_nominal"]["cost"])
            if (r.get("X_nominal") or {}).get("cost") is not None:
                nomX.append(r["X_nominal"]["cost"])
            nxs.append((r.get("X_nominal") or {}).get("n_cross") or 0)
        md, lo, hi, n = mean_ci(dcost)
        mr, rlo, rhi, _ = mean_ci(drel)
        n_neg = sum(1 for d in dcost if d < -1e-9)
        n_pos = sum(1 for d in dcost if d > 1e-9)
        n_tie = len(dcost) - n_neg - n_pos
        return {
            "n_rows": len(rs), "n_paired_cost": n, "STOPPED_S": stopS, "STOPPED_R": stopR,
            "STOPPED_X": stopX,
            "status_S": dict(stS), "status_R": dict(stR), "status_X": dict(stX),
            "delta_mean": md, "delta_ci95": [lo, hi],
            "delta_over_CS_mean": mr, "delta_over_CS_ci95": [rlo, rhi],
            "sign_X_better": n_neg, "sign_S_better": n_pos, "sign_tie": n_tie,
            "sign_p_two_sided": _sign_p(n_neg, n_pos),
            "inc_S_mean": (sum(incS)/len(incS) if incS else None),
            "inc_X_mean": (sum(incX)/len(incX) if incX else None),
            "nom_S_mean": (sum(nomS)/len(nomS) if nomS else None),
            "nom_X_mean": (sum(nomX)/len(nomX) if nomX else None),
            "n_cross_X_mean": (sum(nxs)/len(nxs) if nxs else None),
            # Δ(S→R) = C_R − C_S，恢复共享；Δ(R→X) = C_X − C_R，名义计划。
            "S_to_R": _paired(rs, "S", "R"),
            "R_to_X": _paired(rs, "R", "X"),
            "same_truck_nominal": _same_truck_nominal(rs),
            "fairness": _fairness_report(rs),
        }
    out = {"overall": agg(rows), "by_case": {c: agg(rs) for c, rs in sorted(by_case.items())}}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["nominal", "episodes", "all"], default="all")
    ap.add_argument("--preset", default="A4")
    ap.add_argument("--presets", default=None, help="comma list for batch")
    ap.add_argument("--package", default="data/package_light.json")
    ap.add_argument("--cases", default=CASES_DEFAULT)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--seed0", type=int, default=1)
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--world", default="bernoulli")
    ap.add_argument("--p", type=float, default=0.2)
    ap.add_argument("--out", default="r6/results/round2")
    ap.add_argument("--max-replans", default="n_cust",
                    help="replan cap: n_cust (default, never binding for unique parcel failures), unlimited, or an int")
    ap.add_argument("--nom-from", default=None,
                    help="reuse prebuilt nominals from this directory (e.g. r6/results/round2) instead of out/")
    ap.add_argument("--strategies", default="S,R,X",
                    help="episode strategies, comma-separated. X0 is optional and currently equals R.")
    args = ap.parse_args()
    pkg = args.package
    presets = (args.presets or args.preset).split(",")
    cases = args.cases.split(",")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 名义共享：A0 与 A1 共用 A0 名义；A2 与 A3 共用 A2 名义；A4 独立
    nom_src = {"A0": "A0", "A1": "A0", "A2": "A2", "A3": "A2", "A4": "A4",
               "R3": "R3", "R4": "R3", "R5": "R3", "R6": "R6", "R7": "R7", "R8": "R8",
               "R9": "R9", "R9H": "R9H", "R10": "R10"}

    if args.phase in ("nominal", "all"):
        need = sorted({nom_src[p] for p in presets if p in nom_src})
        jobs = [(pkg, pr, c, args.budget, str(out)) for pr in need for c in cases]
        t0 = time.perf_counter()
        print(f"NOMINAL jobs={len(jobs)} workers={args.workers}", flush=True)
        if args.workers <= 1:
            res = [build_one(j) for j in jobs]
        else:
            with Pool(args.workers) as pool:
                res = pool.map(build_one, jobs)
        (out / "nominal_build.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(f"NOMINAL done in {time.perf_counter()-t0:.1f}s", flush=True)
        for r in res:
            print(f"  {r['preset']} {r['case']} S={r['S'].get('cost')} X={r['X'].get('cost')} "
                  f"Xcross={r['X'].get('n_cross_sorties')} "
                  f"before_repair={r['X'].get('n_cross_before_repair')} "
                  f"repair={r['X'].get('cross_repair')} adopted={r['X'].get('adopted_s_nominal')} "
                  f"reason={r['X'].get('adopt_reason')} wall={r['wall']:.1f}",
                  flush=True)

    if args.phase in ("episodes", "all"):
        jobs = []
        for pr in presets:
            src = nom_src[pr]
            nom_base = Path(args.nom_from) if args.nom_from else out
            nom_root = nom_base / src / "nominal"
            for c in cases:
                for s in range(args.seed0, args.seed0 + args.seeds):
                    jobs.append((pkg, pr, c, s, args.budget, str(nom_root), args.world, args.p,
                                 args.max_replans, args.strategies))
        t0 = time.perf_counter()
        print(f"EPISODES jobs={len(jobs)} workers={args.workers} max_replans={args.max_replans} budget={args.budget}", flush=True)
        jsonl = out / "episodes.jsonl"
        # append-safe incremental log (overwrite at start of this run)
        jsonl.write_text("")
        rows = []
        def _consume(it, n):
            for i, r in enumerate(it, 1):
                rows.append(r)
                with jsonl.open("a") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                s, rgt, x = r.get("S") or {}, r.get("R") or {}, r.get("X") or {}
                sc, rc, xc = s.get("cost"), rgt.get("cost"), x.get("cost")
                dlt = (xc - sc) if (sc is not None and xc is not None) else None
                print(f"  [{i}/{n}] {r.get('preset')} {r.get('case')} seed={r.get('seed')} "
                      f"S={s.get('status')}/{sc} R={rgt.get('status')}/{rc} X={x.get('status')}/{xc} "
                      f"Δ={dlt} failS/R/X={s.get('n_fail_events')}/{rgt.get('n_fail_events')}/{x.get('n_fail_events')} "
                      f"wallS={s.get('wall')} wallR={rgt.get('wall')} wallX={x.get('wall')}", flush=True)
        if args.workers <= 1:
            _consume((ep_one(j) for j in jobs), len(jobs))
        else:
            with Pool(args.workers) as pool:
                _consume(pool.imap_unordered(ep_one, jobs), len(jobs))
        (out / "episodes.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        # per preset summary
        from collections import defaultdict
        by_p = defaultdict(list)
        for r in rows:
            by_p[r["preset"]].append(r)
        summ = {p: summarize(rs) for p, rs in by_p.items()}
        (out / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=2))
        print(f"EPISODES done in {time.perf_counter()-t0:.1f}s", flush=True)
        for p, s in summ.items():
            o = s["overall"]
        print(f"  {p}: n={o['n_paired_cost']} Δ={o['delta_mean']} Δ/CS={o['delta_over_CS_mean']} "
              f"CI={o['delta_ci95']} sign {o['sign_X_better']}/{o['sign_S_better']}/{o['sign_tie']} "
              f"STOP S/R/X={o['STOPPED_S']}/{o.get('STOPPED_R')}/{o['STOPPED_X']} "
              f"S→R={o.get('S_to_R', {}).get('delta_mean')} R→X={o.get('R_to_X', {}).get('delta_mean')}",
              flush=True)


if __name__ == "__main__":
    main()
