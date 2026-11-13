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
    from tdr.experiment import load_case_nominal, episode_metrics, nominal_plan_for_run
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
    for strat in ("S", "X"):
        plan = nominal_plan_for_run(noms["S"][0], noms[strat][0], strat, bool(alg.x_adopt_s_if_cross))
        nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
        air = sorted({p for s in plan.sorties.values() for p in s.air})
        out[strat + "_nominal"] = dict(
            cost=nom_ev.cost, feasible=nom_ev.feasible, air=len(air), H=H,
            n_cross=sum(1 for s in plan.sorties.values() if is_cross_sortie(plan, s)),
            n_sorties=len(plan.sorties))
        if not nom_ev.feasible:
            out[strat] = dict(status="NOMINAL_INFEASIBLE_UNDER_H", cost=None, notes=nom_ev.violations[:2])
            continue
        # 该计划空送且属于隐失败集合的票（CRN：同一隐集合，观测取决于空送集合）
        served_hidden = sorted(set(air) & set(hidden or []))
        out[strat + "_nominal"]["air_hidden"] = served_hidden
        max_replans = _max_replans_value(max_replans_spec, len(inst.customers))
        out["max_replans"] = max_replans
        t0 = time.perf_counter()
        world = make_world(inst, case, seed, failure_mode, p)
        rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
        try:
            ep = simulate.run_episode(inst, plan, nom_ev, H, phys, world, strat, alg, rngs,
                                      recovery_eval_budget=budget, cut_mode="snapshot",
                                      max_replans=max_replans)
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
                          max_replans=max_replans)
    return out


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


def summarize(rows):
    from collections import Counter, defaultdict
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    def agg(rs, tag=""):
        dcost, drel, incS, incX, nomS, nomX, nxs = [], [], [], [], [], [], []
        stopS = stopX = done = 0
        stS, stX = Counter(), Counter()
        for r in rs:
            s, x = r.get("S") or {}, r.get("X") or {}
            stS[s.get("status") or "MISSING"] += 1
            stX[x.get("status") or "MISSING"] += 1
            if (s.get("status") or "").startswith("STOP"):
                stopS += 1
            if (x.get("status") or "").startswith("STOP"):
                stopX += 1
            if s.get("cost") is None or x.get("cost") is None:
                continue
            done += 1
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
        # 符号检验：X 更好的次数（Δ<0）
        n_neg = sum(1 for d in dcost if d < -1e-9)
        n_pos = sum(1 for d in dcost if d > 1e-9)
        n_tie = len(dcost) - n_neg - n_pos
        return {
            "n_rows": len(rs), "n_paired_cost": n, "STOPPED_S": stopS, "STOPPED_X": stopX,
            "status_S": dict(stS), "status_X": dict(stX),
            "delta_mean": md, "delta_ci95": [lo, hi],
            "delta_over_CS_mean": mr, "delta_over_CS_ci95": [rlo, rhi],
            "sign_X_better": n_neg, "sign_S_better": n_pos, "sign_tie": n_tie,
            "sign_p_two_sided": _sign_p(n_neg, n_pos),
            "inc_S_mean": (sum(incS)/len(incS) if incS else None),
            "inc_X_mean": (sum(incX)/len(incX) if incX else None),
            "nom_S_mean": (sum(nomS)/len(nomS) if nomS else None),
            "nom_X_mean": (sum(nomX)/len(nomX) if nomX else None),
            "n_cross_X_mean": (sum(nxs)/len(nxs) if nxs else None),
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
    args = ap.parse_args()
    pkg = args.package
    presets = (args.presets or args.preset).split(",")
    cases = args.cases.split(",")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 名义共享：A0 与 A1 共用 A0 名义；A2 与 A3 共用 A2 名义；A4 独立
    nom_src = {"A0": "A0", "A1": "A0", "A2": "A2", "A3": "A2", "A4": "A4",
               "R3": "R3", "R4": "R3", "R5": "R3", "R6": "R6", "R7": "R7"}

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
                    jobs.append((pkg, pr, c, s, args.budget, str(nom_root), args.world, args.p, args.max_replans))
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
                s, x = r.get("S") or {}, r.get("X") or {}
                sc, xc = s.get("cost"), x.get("cost")
                dlt = (xc - sc) if (sc is not None and xc is not None) else None
                print(f"  [{i}/{n}] {r.get('preset')} {r.get('case')} seed={r.get('seed')} "
                      f"S={s.get('status')}/{sc} X={x.get('status')}/{xc} "
                      f"Δ={dlt} failS/X={s.get('n_fail_events')}/{x.get('n_fail_events')} "
                      f"replS/X={s.get('n_replans')}/{x.get('n_replans')} "
                      f"hit_cap={s.get('hit_cap')}/{x.get('hit_cap')} "
                      f"wallS={s.get('wall')} wallX={x.get('wall')}", flush=True)
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
                  f"STOP S/X={o['STOPPED_S']}/{o['STOPPED_X']} incS={o['inc_S_mean']} incX={o['inc_X_mean']}",
                  flush=True)


if __name__ == "__main__":
    main()
