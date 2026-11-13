"""变体 A 的训练脚本：在**训练环境种子**（默认 101–130，与评价用的 1–10 不重叠）上训练 Q 表.

单案例训练：  python scripts/train_selector.py --case C50 --out outputs/qtables/C50.json
合并多个案例： python scripts/train_selector.py --merge outputs/qtables/*.json --out outputs/qtables/merged.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tdr import selector                                         # noqa: E402
from tdr.config import AlgorithmConfig, PhysicalConfig          # noqa: E402
from tdr.data import load_instance                               # noqa: E402
from tdr.evaluate import evaluate_plan                           # noqa: E402
from tdr.experiment import load_case_nominal                     # noqa: E402
from tdr.hidden_world import HiddenWorld                         # noqa: E402
from tdr.schedule import initial_state                           # noqa: E402
from tdr.simulate import derive_rngs, run_episode                # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--package", default="data/package.json")
ap.add_argument("--nominal-dir", default="outputs_summary/nominal2")
ap.add_argument("--case")
ap.add_argument("--seed-from", type=int, default=101)
ap.add_argument("--seed-to", type=int, default=130)
ap.add_argument("--budget", type=int, default=1000)
ap.add_argument("--eps-start", type=float, default=0.30)
ap.add_argument("--eps-end", type=float, default=0.10)
ap.add_argument("--out", required=True)
ap.add_argument("--merge", nargs="*")
a = ap.parse_args()

if a.merge:
    tabs = [json.load(open(p, encoding="utf-8")) for p in a.merge]
    merged = selector.QSelector.merge(tabs)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(merged, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print("merged", len(tabs), "tables; states:", len(merged["q"]), "updates:", merged["n_updates"])
    sys.exit(0)

pkg = json.load(open(a.package, encoding="utf-8"))
phys = PhysicalConfig.from_dict(pkg["config"])
alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
alg.operator_selector = "qlearn"
sel = selector.QSelector(list(alg.destroy_operators), list(alg.repair_operators),
                         eps=a.eps_start, learn=True)
selector.TRAINING_SELECTOR = sel
inst = load_instance(pkg, a.case)
plan, cost, H = load_case_nominal(inst, Path(a.nominal_dir) / a.case)
nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
seeds = list(range(a.seed_from, a.seed_to + 1))
total = len(seeds) * 2
k = 0
for seed in seeds:
    for strategy in ("S", "X"):
        sel.eps = a.eps_start + (a.eps_end - a.eps_start) * k / max(1, total - 1)
        k += 1
        world = HiddenWorld(inst, inst.case_id, seed)
        rngs = derive_rngs(alg.base_algorithm_seed + seed, inst.case_id, "recovery", 0)
        ep = run_episode(inst, plan, nom_ev, H, phys, world, strategy, alg, rngs,
                         recovery_eval_budget=a.budget)
        print(a.case, seed, strategy, ep.status, "updates", sel.n_updates, flush=True)
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
json.dump(sel.to_json(), open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
print("saved", a.out, "states", len(sel.q), "updates", sel.n_updates)
