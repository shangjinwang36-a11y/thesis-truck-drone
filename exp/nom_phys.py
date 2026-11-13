import sys, json, os
sys.path.insert(0, '/workspace/thesis/proj/src'); os.chdir('/workspace/thesis/proj')
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import build_case_nominal
case, out, budget, pj = sys.argv[1], sys.argv[2], int(sys.argv[3]), json.loads(sys.argv[4])
pkg = json.load(open('data/package.json'))
cfg = dict(pkg['config']); cfg.update(pj)
phys = PhysicalConfig.from_dict(cfg)
alg = AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
inst = load_instance(pkg, case)
m = build_case_nominal(inst, phys, alg, Path(out) / case, eval_budget=budget)
print(json.dumps(m, ensure_ascii=False))
