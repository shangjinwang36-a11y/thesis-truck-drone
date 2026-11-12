"""第三轮：机体航次链次序修复（早于链内已有航次的新航次必须插在其前面）."""
import json
from pathlib import Path

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.plan import ground_only_plan
from tdr.schedule import initial_state, schedule_plan
from tdr.evaluate import evaluate_plan

ROOT = Path(__file__).resolve().parents[1]


def _setup():
    pkg = json.load(open(ROOT / "data" / "package.json"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    inst = load_instance(pkg, "C50")
    return inst, phys, ground_only_plan(inst)


def test_chain_insert_follows_route_order():
    inst, phys, plan = _setup()
    truck = max(plan.routes, key=lambda k: len(plan.routes[k]))
    r = plan.routes[truck]
    assert len(r) >= 8
    drone = phys.home_drone if hasattr(phys, "home_drone") else f"d{int(truck[1:])}"
    late = plan.add_sortie(drone, truck, r[5], "STOP", 0.0, [], r[7])
    early = plan.add_sortie(drone, truck, r[1], "STOP", 0.0, [], r[3])
    assert plan.drone_sorties[drone] == [early.sid, late.sid]
    # 时刻表固定点必须收敛(此前顺序颠倒会每轮漂移约 1300 s，14 轮不收敛)
    tl = schedule_plan(plan, inst, phys, initial_state(inst, phys))
    assert tl.iterations < 14
