"""T08a-5a：情景分缓存的指纹要区分放飞点/接机点。S 与 X 共用同一函数。"""
import json
from pathlib import Path

from tdr import hybrid
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import plan_from_dict
from tdr.schedule import initial_state

ROOT = Path(__file__).resolve().parents[1]


def test_moving_a_launch_or_recovery_visit_changes_the_fingerprint():
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C50")
    plan = plan_from_dict(json.loads((ROOT / "r6/results/round11_tune/R11/nominal/S/C50/nominal_plan.json").read_text())["plan"])
    base = hybrid._fingerprint(plan)
    n = 0
    for s in plan.sorties.values():
        for field in ("launch_vid", "rec_vid"):
            cur = getattr(s, field)
            if cur is None or cur not in plan.visits:
                continue
            for vid in plan.routes[plan.visits[cur].truck]:
                if vid == cur:
                    continue
                q = plan.clone()
                setattr(q.sorties[s.sid], field, vid)
                assert hybrid._fingerprint(q) != base
                n += 1
    assert n > 0
    assert hybrid._fingerprint(plan.clone()) == base          # 同一结构仍命中缓存
