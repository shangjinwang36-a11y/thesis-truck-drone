"""命令行入口：python -m tdr <command> [options]."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import SCHEMA_VERSION, __version__
from .config import AlgorithmConfig, PhysicalConfig
from .data import extract_from_spec, load_instance, validate_package
from .experiment import build_case_nominal, paired_statistics, run_batch, run_episode_dir

CASE_IDS = ["C50", "R50", "RC50", "C100", "R100", "RC100"]


def _load(pkg_path: str):
    with open(pkg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_extract(args) -> int:
    meta = extract_from_spec(args.spec, args.out)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0 if meta.get("package_sha256_match") and meta.get("source_sha256_match") else 1


def cmd_validate(args) -> int:
    pkg = _load(args.package)
    meta = validate_package(pkg)
    out = Path(args.out) if args.out else Path(args.package).parent / "validation.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": meta["ok"], "errors": meta["errors"][:10],
                      "n_customers": meta["n_customers"]}, ensure_ascii=False))
    return 0 if meta["ok"] else 1


def _phys_alg(pkg, args):
    phys = PhysicalConfig.from_dict(pkg["config"])
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    if getattr(args, "recovery_eval_budget", None) is not None:
        alg.recovery_eval_budget_override = args.recovery_eval_budget
        alg.recovery_time_limit_override_s = None
    return phys, alg


def cmd_nominal(args) -> int:
    pkg = _load(args.package)
    phys, alg = _phys_alg(pkg, args)
    cases = CASE_IDS if args.case == "all" else [args.case]
    metas = []
    for case in cases:
        inst = load_instance(pkg, case)
        m = build_case_nominal(inst, phys, alg, Path(args.out) / case,
                               eval_budget=args.eval_budget)
        print(json.dumps(m, ensure_ascii=False))
        metas.append(m)
    return 0 if all(m.get("status") == "FEASIBLE" for m in metas) else 1


def cmd_simulate(args) -> int:
    pkg = _load(args.package)
    phys, alg = _phys_alg(pkg, args)
    inst = load_instance(pkg, args.case)
    from .experiment import load_case_nominal
    plan, cost, H = load_case_nominal(inst, Path(args.nominal) / args.case
                                      if (Path(args.nominal) / args.case).exists() else Path(args.nominal))
    strategies = ["S", "X"] if args.strategy == "both" else [args.strategy]
    for strategy in strategies:
        out = Path(args.out) / f"{args.case}_seed{args.environment_seed:02d}_{strategy}"
        r = run_episode_dir(inst, plan, cost, H, phys, alg, args.environment_seed, strategy, out,
                            recovery_eval_budget=args.recovery_eval_budget,
                            recovery_wall_s=args.recovery_wall_s)
        print(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_experiment(args) -> int:
    pkg = _load(args.package)
    phys, alg = _phys_alg(pkg, args)
    cases = CASE_IDS if args.cases == "all" else args.cases.split(",")
    seeds = list(range(1, args.seeds + 1))
    strategies = ["S", "X"] if args.strategy == "both" else [args.strategy]
    if args.recovery_wall_s is not None:
        summ = run_batch(pkg, cases, seeds, strategies, args.nominal_dir, args.out, phys, alg,
                         args.recovery_eval_budget, args.recovery_wall_s)
    else:
        summ = run_batch(pkg, cases, seeds, strategies, args.nominal_dir, args.out, phys, alg,
                         args.recovery_eval_budget, None)
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    return 0


def cmd_smoke(args) -> int:
    """8 客户开发夹具：验证多票空送、失效揭示、恢复、跨车、返库."""
    pkg = _load(args.package)
    phys, alg = _phys_alg(pkg, args)
    inst_full = load_instance(pkg, "C50")
    from .data import Customer, Instance
    custs = tuple(inst_full.customers[:8])
    inst = Instance("SMOKE8", "C50", inst_full.depot_x, inst_full.depot_y, custs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    m = build_case_nominal(inst, phys, alg, out / "nominal", eval_budget=args.eval_budget or 300)
    print(json.dumps(m, ensure_ascii=False))
    if m.get("status") != "FEASIBLE":
        return 1
    from .experiment import load_case_nominal
    plan, cost, H = load_case_nominal(inst, out / "nominal")
    air = [p for s in plan.sorties.values() for p in s.air]
    results = []
    for strategy in ("S", "X"):
        for target in (air[:1] or [None]):
            if target is None:
                continue
            from .hidden_world import TestWorld
            from .simulate import run_episode
            from .evaluate import evaluate_plan
            from .schedule import initial_state
            world = TestWorld(inst, "SMOKE8", (target,))
            from .simulate import derive_rngs
            ep = run_episode(inst, plan, evaluate_plan(plan, inst, phys, initial_state(inst, phys), H),
                             H, phys, world, strategy, alg,
                             derive_rngs(alg.base_algorithm_seed, "SMOKE8", "recovery", 0),
                             recovery_eval_budget=args.recovery_eval_budget or 200)
            results.append({"strategy": strategy, "status": ep.status,
                            "cost": ep.evaluation.cost if ep.evaluation else None,
                            "observed_failure": [o.parcel_id for o in ep.observations
                                                 if not o.air_delivery_available]})
    (out / "smoke_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(r["status"] == "COMPLETED_VERIFIED" for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tdr", description="tdr_alns_v61 (V6.1 implementation)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract")
    p.add_argument("--spec", required=True)
    p.add_argument("--out", default="data")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("validate")
    p.add_argument("--package", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("nominal")
    p.add_argument("--package", required=True)
    p.add_argument("--case", default="all")
    p.add_argument("--out", default="outputs/nominal")
    p.add_argument("--eval-budget", type=int, default=None)
    p.set_defaults(func=cmd_nominal)

    p = sub.add_parser("simulate")
    p.add_argument("--package", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--environment-seed", type=int, required=True)
    p.add_argument("--strategy", default="both", choices=["S", "X", "both"])
    p.add_argument("--nominal", default="outputs/nominal")
    p.add_argument("--out", default="outputs/single")
    p.add_argument("--recovery-eval-budget", type=int, default=None)
    p.add_argument("--recovery-wall-s", type=float, default=None)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("experiment")
    p.add_argument("--package", required=True)
    p.add_argument("--nominal-dir", required=True)
    p.add_argument("--out", default="outputs/formal")
    p.add_argument("--cases", default="all")
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--strategy", default="both", choices=["S", "X", "both"])
    p.add_argument("--recovery-eval-budget", type=int, default=None)
    p.add_argument("--recovery-wall-s", type=float, default=None)
    p.add_argument("--formal", action="store_true")
    p.set_defaults(func=cmd_experiment)

    p = sub.add_parser("smoke")
    p.add_argument("--package", required=True)
    p.add_argument("--out", default="outputs/smoke")
    p.add_argument("--eval-budget", type=int, default=None)
    p.add_argument("--recovery-eval-budget", type=int, default=None)
    p.set_defaults(func=cmd_smoke)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
