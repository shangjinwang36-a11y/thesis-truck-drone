#!/usr/bin/env python3
"""DIAGNOSTIC ONLY. Not a main-result run.

On tune seeds 101-110, two ceilings under the fixed physics and the 0.08333 kWh margin:
  * X's nominal search with 10x the evaluation budget (10000), then the usual episodes.
  * Exhaustive single-cross insertion, and pair-cross insertion, on S's published plan.
The best g_SX of those plans is an upper look at what the fixed settings can pay.
"""
from __future__ import annotations

import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "r6"))

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
TUNE = list(range(101, 111))


def _singles(plan, inst, phys, H, slack):
    from tdr.cross_nominal import _apply_rec, _clears, _floor_kwh, scheduler_feasible
    from tdr.moves import air_energy, air_time, route_times, sortie_start, _pos
    floor = _floor_kwh(phys, slack)
    rt_cache = {}

    def rt(truck):
        if truck not in rt_cache:
            rt_cache[truck] = route_times(plan, inst, phys, truck)
        return rt_cache[truck]

    out = []
    for sids in plan.drone_sorties.values():
        if not sids:
            continue
        s = plan.sorties[sids[-1]]
        if s.started or not s.air or s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
            continue
        if plan.visits[s.launch_vid].truck != plan.visits[s.rec_vid].truck:
            continue
        ta = plan.visits[s.launch_vid].truck
        if s.launch_vid not in plan.routes.get(ta, []):
            continue
        sp = sortie_start(inst, plan, s)
        _, dep_a = rt(ta)
        la = plan.routes[ta].index(s.launch_vid)
        mass = sum(inst.parcel_mass[p] for p in s.air)
        rv = plan.visits[s.rec_vid]
        removable = (not rv.ground and not any(
            o.sid != s.sid and (o.launch_vid == rv.vid or o.rec_vid == rv.vid)
            for o in plan.sorties.values()))
        for tb, route in plan.routes.items():
            if tb == ta:
                continue
            arr_b, _ = rt(tb)
            for bi, vid in enumerate(route):
                rp = _pos(inst, plan, vid)
                try:
                    e = air_energy(inst, phys, sp, s.air, rp)
                except KeyError:
                    continue
                tt = arr_b[bi] - dep_a[la]
                hover = phys.hover_energy_kwh(max(0.0, tt - air_time(inst, phys, sp, s.air, rp)), mass)
                necessary = (e + hover
                             + phys.hover_energy_kwh(phys.launch_s, mass)
                             + phys.hover_energy_kwh(phys.air_service_s, mass)
                             + phys.hover_energy_kwh(phys.recovery_s, mass))
                if not _clears(phys, necessary, floor):
                    continue
                cand = plan.clone()
                if not _apply_rec(cand, s.sid, vid, removable):
                    continue
                if not scheduler_feasible(cand, inst, phys, H, slack):
                    continue
                out.append((s.sid, vid, removable, cand))
    return out


def _insert_case(args):
    cfg, case, s_dir, out_dir = args
    from tdr.config import load_package
    from tdr.data import load_instance
    from tdr.evaluate import evaluate_plan, is_cross_sortie
    from tdr.expected_cost import expected_j
    from tdr.experiment import load_case_nominal, plan_to_dict
    from tdr.schedule import initial_state
    from run_v13 import _alg
    pkg = load_package(ROOT / "data" / "package_light.json")
    phys, _alg_s = _alg(cfg, case, "full")
    inst = load_instance(pkg, case)
    H = float(cfg["cases"][case]["H_case_s"])
    plan, _, _ = load_case_nominal(inst, s_dir)
    base = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    j_base = expected_j(base.cost, plan, inst, phys, 0.0, v13=True)
    singles = _singles(plan, inst, phys, H, 90.0)
    scored = []
    for sid, vid, removable, cand in singles:
        ev = evaluate_plan(cand, inst, phys, initial_state(inst, phys), H, "DIAG_SINGLE")
        if not ev.feasible:
            continue
        j = expected_j(ev.cost, cand, inst, phys, 0.0, v13=True)
        ncross = sum(1 for s in cand.sorties.values() if is_cross_sortie(cand, s))
        scored.append((j, ev.cost, ncross, sid, vid, removable, cand))
    scored.sort(key=lambda row: (row[0] if row[0] is not None else 1e18, row[1]))
    best_single = scored[0] if scored else None
    # Pairs: every non-conflicting combination of the best 12 schedule-feasible singles.
    pair_pool = scored[:12]
    best_pair = None
    n_pairs = 0
    for i, a in enumerate(pair_pool):
        for b in pair_pool[i + 1:]:
            if a[3] == b[3] or a[4] == b[4]:
                continue
            cand = plan.clone()
            from tdr.cross_nominal import _apply_rec, scheduler_feasible
            if not _apply_rec(cand, a[3], a[4], a[5]):
                continue
            if not _apply_rec(cand, b[3], b[4], b[5]):
                continue
            n_pairs += 1
            if not scheduler_feasible(cand, inst, phys, H, 90.0):
                continue
            ev = evaluate_plan(cand, inst, phys, initial_state(inst, phys), H, "DIAG_PAIR")
            if not ev.feasible:
                continue
            j = expected_j(ev.cost, cand, inst, phys, 0.0, v13=True)
            ncross = sum(1 for s in cand.sorties.values() if is_cross_sortie(cand, s))
            if best_pair is None or (j is not None and j < best_pair[0]):
                best_pair = (j, ev.cost, ncross, cand)
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)

    def dump(name, row):
        if row is None:
            return
        blob = {"plan": plan_to_dict(row[-1], inst), "cost": row[1], "j": row[0], "n_cross": row[2]}
        (dest / f"{name}.json").write_text(json.dumps(blob), encoding="utf-8")

    dump("single", best_single)
    dump("pair", best_pair)
    return {
        "case": case,
        "s_cost": base.cost,
        "s_j": j_base,
        "n_schedule_singles": len(singles),
        "n_feasible_singles": len(scored),
        "n_pairs_tried": n_pairs,
        "single_cost": None if best_single is None else best_single[1],
        "single_j": None if best_single is None else best_single[0],
        "single_cross": None if best_single is None else best_single[2],
        "pair_cost": None if best_pair is None else best_pair[1],
        "pair_j": None if best_pair is None else best_pair[0],
        "pair_cross": None if best_pair is None else best_pair[2],
    }


def _nominal_10x(args):
    cfg, case, out_dir = args
    from tdr.config import load_package
    from tdr.data import load_instance
    from tdr.experiment import build_case_nominal
    from run_v13 import _alg
    pkg = load_package(ROOT / "data" / "package_light.json")
    phys, alg = _alg(cfg, case, "full")
    inst = load_instance(pkg, case)
    dest = Path(out_dir) / case
    t0 = time.perf_counter()
    meta = build_case_nominal(inst, phys, alg, dest, eval_budget=10000, cross_launch=True)
    return {"case": case, "cost": meta.get("cost"), "n_cross": meta.get("n_cross_sorties"),
            "evals": meta.get("eval_requests"), "wall_s": time.perf_counter() - t0}


def _episode(args):
    cfg, case, seed, plan_path, label = args
    from tdr.config import load_package
    from tdr.data import load_instance
    from tdr.evaluate import evaluate_plan, is_cross_sortie
    from tdr.experiment import plan_from_dict
    from tdr.hidden_world import HiddenWorld
    from tdr.schedule import initial_state
    from tdr import simulate
    from run_v13 import _alg
    pkg = load_package(ROOT / "data" / "package_light.json")
    phys, alg = _alg(cfg, case, "full")
    inst = load_instance(pkg, case)
    H = float(cfg["cases"][case]["H_case_s"])
    raw = json.loads(Path(plan_path).read_text())
    plan = plan_from_dict(raw["plan"] if "plan" in raw and "routes" not in raw else raw.get("plan", raw))
    # nominal_plan.json wraps the plan; insertion dumps do too under "plan".
    if "routes" in raw:
        plan = plan_from_dict(raw)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    if not nom.feasible:
        return {"case": case, "seed": seed, "label": label, "cost": None, "status": nom.status}
    world = HiddenWorld(inst, case, seed)
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0, public_history=())
    ep = simulate.run_episode(inst, plan, nom, H, phys, world, "X", alg, rngs,
                              recovery_eval_budget=1000, recovery_wall_s=60.0,
                              max_replans=len(inst.customers), ground_finish=True)
    return {"case": case, "seed": seed, "label": label,
            "cost": getattr(ep, "v13_cost", None),
            "status": getattr(ep, "v13_status", ep.status),
            "n_cross": sum(1 for s in plan.sorties.values() if is_cross_sortie(plan, s))}


def main():
    from tdr.v13 import load_run_config
    cfg, _, _ = load_run_config(formal=False, m1=10, m2=10)
    main_root = ROOT / "r6" / "results" / "v13_round8"
    out = ROOT / "r6" / "results" / "v13_round8_ceiling"
    out.mkdir(parents=True, exist_ok=True)
    insert_jobs = [(cfg, c, main_root / "nominal" / "S" / c, out / "insert" / c) for c in CASES]
    with Pool(4) as pool:
        insert_rows = pool.map(_insert_case, insert_jobs)
        ten_rows = pool.map(_nominal_10x, [(cfg, c, out / "nominal10x") for c in CASES])
    (out / "insert_summary.json").write_text(json.dumps(insert_rows, indent=2), encoding="utf-8")
    (out / "nominal10x_summary.json").write_text(json.dumps(ten_rows, indent=2), encoding="utf-8")
    jobs = []
    for c in CASES:
        for seed in TUNE:
            jobs.append((cfg, c, seed, main_root / "nominal" / "X" / c / "nominal_plan.json", "main"))
            p10 = out / "nominal10x" / c / "nominal_plan.json"
            if p10.exists():
                jobs.append((cfg, c, seed, p10, "budget10x"))
            for label in ("single", "pair"):
                p = out / "insert" / c / f"{label}.json"
                if p.exists():
                    jobs.append((cfg, c, seed, p, label))
    with Pool(4) as pool:
        episodes = pool.map(_episode, jobs)
    (out / "episodes.json").write_text(json.dumps(episodes), encoding="utf-8")
    main_eps = json.loads((main_root / "episodes.json").read_text())
    s_cost = {}
    for ep in main_eps:
        if ep["seed"] not in TUNE:
            continue
        s_cost[(ep["case"], ep["seed"])] = (ep.get("S") or {}).get("cost")
    by = {c: {lab: [] for lab in ("main", "budget10x", "single", "pair")} for c in CASES}
    for row in episodes:
        cs = s_cost.get((row["case"], row["seed"]))
        cx = row.get("cost")
        if cs and cx:
            by[row["case"]][row["label"]].append((cs - cx) / cs)
    table = []
    for c in CASES:
        rec = {"case": c}
        best = None
        for lab in ("main", "budget10x", "single", "pair"):
            vals = by[c][lab]
            g = None if not vals else sum(vals) / len(vals)
            rec[lab] = g
            rec[f"n_{lab}"] = len(vals)
            if g is not None and (best is None or g > best):
                best = g
        rec["best_g_sx"] = best
        table.append(rec)
    (out / "ceiling.json").write_text(json.dumps({
        "label": "DIAGNOSTIC ONLY",
        "tune_seeds": TUNE,
        "insert": insert_rows,
        "nominal10x": ten_rows,
        "g_sx": table,
    }, indent=2), encoding="utf-8")
    print(json.dumps(table, indent=2))


if __name__ == "__main__":
    main()
