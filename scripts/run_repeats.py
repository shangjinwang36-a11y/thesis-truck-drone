"""算法基种子重复实验：同一批环境，换算法基种子重跑（对应规范 12.5(6) 的稳定性补充实验）.

用法：python scripts/run_repeats.py --budget 1000 --seed 20261112 --out outputs/fix1000_s20261112
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tdr.config import AlgorithmConfig, PhysicalConfig          # noqa: E402
from tdr.experiment import run_batch                             # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--package", default="data/package.json")
ap.add_argument("--nominal-dir", default="outputs_summary/nominal2")
ap.add_argument("--budget", type=int, required=True)
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--recovery-decision", default=None)
ap.add_argument("--selector", default=None)
ap.add_argument("--qtable", default=None)
a = ap.parse_args()
pkg = json.load(open(a.package, encoding="utf-8"))
phys = PhysicalConfig.from_dict(pkg["config"])
alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
alg.base_algorithm_seed = a.seed
if a.recovery_decision:
    alg.recovery_decision = a.recovery_decision
if a.selector:
    alg.operator_selector = a.selector
if a.qtable:
    alg.qtable_path = a.qtable
cases = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
run_batch(pkg, cases, list(range(1, 11)), ["S", "X"], a.nominal_dir, a.out, phys, alg,
          a.budget, None, make_figures=False)
