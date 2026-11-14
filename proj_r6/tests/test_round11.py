"""第 11 轮：失败按包裹键抽取；T08a 修正恢复目录为 S/R/X 统一能量预筛。"""
import json
from pathlib import Path

from tdr.config import PhysicalConfig
from tdr.data import Customer, Instance, load_instance
from tdr.hidden_world import BernoulliWorld, bernoulli_failure_flags
from tdr.plan import Plan
from tdr.recovery import RecoveryCatalog
from tdr.schedule import DroneStart, initial_state

ROOT = Path(__file__).resolve().parents[1]


def test_bernoulli_draw_is_keyed_by_parcel_not_by_order():
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    ids = [c.parcel_id for c in inst.customers]
    forward = bernoulli_failure_flags("C50", 11, ids, 0.2)
    backward = bernoulli_failure_flags("C50", 11, list(reversed(ids)), 0.2)
    duplicated = bernoulli_failure_flags("C50", 11, ids + ids, 0.2)
    assert forward == backward == duplicated
    first = BernoulliWorld(inst, "C50", 11, 0.2)
    second = BernoulliWorld(inst, "C50", 11, 0.2)
    for parcel in ids:
        early = first.observe_air_arrival(parcel, 1.0, f"early|{parcel}", "c", "d1")
        late = second.observe_air_arrival(parcel, 50.0, f"late|{parcel}|2", "c", "d9")
        assert early.air_delivery_available == late.air_delivery_available
        assert (not early.air_delivery_available) == (parcel in forward)
    reverse = BernoulliWorld(inst, "C50", 11, 0.2)
    for parcel in reversed(ids):
        obs = reverse.observe_air_arrival(parcel, 3.0, f"rev|{parcel}", "c", "d1")
        assert (not obs.air_delivery_available) == (parcel in forward)


def _airborne(energy: float):
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    phys.set_active()
    inst = Instance("TAIL", "T", 0.0, 0.0, (
        Customer("c1", "p1", 400.0, 0.0, 1.0),
        Customer("c2", "p2", 20000.0, 0.0, 1.0),
        Customer("c3", "p3", 800.0, 400.0, 1.0),
    ))
    plan = Plan("TAIL")
    launch = plan.add_visit("t1", "c1", ground=["p1"])
    rec = plan.add_visit("t1", "c2", ground=[])
    plan.add_visit("t2", "c3", ground=["p3"])
    frag = plan.add_sortie("d1", "t1", launch.vid, "ARC", 0.0, ["p2"], rec.vid)
    frag.started = True
    frag.start_pos = (0.0, 0.0)
    frag.launch_truck = "t1"
    state = initial_state(inst, phys)
    state.drone_energy["d1"] = energy
    state.drone_start["d1"] = DroneStart("AIRBORNE", None, 0.0, (0.0, 0.0), energy, aboard=["p2"])
    return plan, frag, inst, phys, state


def _take(cat, n=80):
    out = []
    for entry in cat._gen:
        out.append(entry)
        if len(out) >= n:
            break
    return out


def test_energy_screen_applies_to_all_strategies():
    plan, frag, inst, phys, state = _airborne(0.001)
    guard = 4
    plain = RecoveryCatalog(plan, frag, inst, "X", state, set(), phys=phys, guard_n=guard)
    screened = RecoveryCatalog(plan, frag, inst, "X", state, set(), phys=phys, guard_n=guard,
                               drop_energy_tail=True)
    same = RecoveryCatalog(plan, frag, inst, "S", state, set(), phys=phys, guard_n=guard,
                           drop_energy_tail=True)
    reactive = RecoveryCatalog(plan, frag, inst, "R", state, set(), phys=phys, guard_n=guard,
                               drop_energy_tail=True)
    a = _take(plain)
    b = _take(screened)
    c = _take(same)

    def key(entry):
        return (entry["truck"], entry["ref"], tuple(entry["served"]))

    assert len(a) > guard
    assert any(entry["est"] >= 1e4 for entry in a[guard:])
    assert b and c
    assert all(entry["est"] < 1e4 for entry in b + c)
    assert [key(entry) for entry in b if entry["truck"] == "t1"] == [key(entry) for entry in c]
    assert _take(reactive) == b
