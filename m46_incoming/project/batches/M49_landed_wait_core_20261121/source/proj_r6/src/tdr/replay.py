"""不可变执行日志的独立全程重放核验.

只读取：班次初态 + 逐段动作/阶段记录。不调用 schedule_plan / allocate_charging。
逐事件按真实区间核对：车辆位移只在 DRIVE 结束时更新；人工动作不得与驾驶重叠；
接机/交付必须在真实到场之后；通道与机位按全区间统计；能量与成本由几何/载荷/充电重算。
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .config import PhysicalConfig
from .data import Instance


@dataclass
class ReplayReport:
    ok: bool = False
    violations: list[str] = field(default_factory=list)
    cost: float | None = None
    distance_km: float = 0.0
    driver_s: float = 0.0
    charge_ac_kwh: float = 0.0
    e_return: dict[str, float] = field(default_factory=dict)
    delivered: int = 0
    n_segments: int = 0
    terminal: dict[str, dict] = field(default_factory=dict)
    n_swaps: int = 0

    def to_dict(self) -> dict:
        return {"ok": self.ok, "violations": self.violations[:50], "cost": self.cost,
                "distance_km": self.distance_km, "driver_s": self.driver_s,
                "charge_ac_kwh": self.charge_ac_kwh, "e_return": self.e_return,
                "delivered": self.delivered, "n_segments": self.n_segments,
                "terminal": self.terminal, "n_swaps": self.n_swaps}


def _d(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - 1e-9 and b0 < a1 - 1e-9


def verify_replay(inst: Instance, phys: PhysicalConfig, segments: list[dict], H: float | None = None,
                  strategy: str | None = None, *, require_complete: bool = True) -> ReplayReport:
    rep = ReplayReport(n_segments=len(segments))
    if not segments:
        rep.violations.append("NO_SEGMENTS")
        return rep
    v = rep.violations
    first = segments[0]["start"]
    holder = {p: h for p, h in first["holder"].items()}
    parcel_mass = inst.parcel_mass
    carrier = {d: c for d, c in first["drone_carrier"].items()}
    for d, mode in first.get("drone_mode", {}).items():
        if mode == "AIRBORNE":
            carrier[d] = None
    prepared = {d: (carrier.get(d), segments[0]["t0"], set(parcels))
                for d, parcels in first.get("prepared_loads", {}).items()}
    awaiting_handover = {}
    energy = {d: float(e) for d, e in first["energy"].items()}
    for d, e in energy.items():
        if e < phys.e_min - phys.energy_tol:
            v.append(f"INITIAL_RESERVE:{d}:{e:.9f}")
    delivered = set(first.get("delivered", []))
    ac_left = {k: float(a) for k, a in first.get("truck_ac", {}).items()}
    start_pos = {k: tuple(p) for k, p in first["truck_pos"].items()}
    min_energy = dict(energy)
    # Recorded prefix-completed clocks are physical snapshot facts, not future
    # evaluator output. Full episodes derive clocks afresh from executed events.
    truck_finish: dict[str, float] = {k:float(t) for k,t in first.get("truck_done",{}).items()}
    total_dist = 0.0
    charge_ac = 0.0
    swap_refill = 0.0
    n_swaps = 0
    onboard: dict[str, set[str]] = {k: set() for k in start_pos}
    for d, c in carrier.items():
        if c:
            onboard.setdefault(c, set()).add(d)
    reserved: dict[str, int] = {k: 0 for k in start_pos}

    # 全局：每车的位移/驾驶区间与人工动作区间，用于跨段续接与重叠检查
    drive_iv: dict[str, list[tuple[float, float]]] = {k: [] for k in start_pos}
    manual_iv: dict[str, list[tuple[float, float, str]]] = {k: [] for k in start_pos}
    channel_iv: dict[str, list[tuple[float, float, str]]] = {k: [] for k in start_pos}
    pos_tl: dict[str, list[tuple[float, tuple[float, float]]]] = {k: [] for k in start_pos}
    stage_iv: dict[str, list[tuple[float, float, str]]] = {}
    destinations = {c.customer_id: (c.x, c.y) for c in inst.customers}
    depot = (inst.depot_x, inst.depot_y)
    destinations["DEPOT"] = depot
    pending_stops = {}

    def pos_at(truck: str, t: float):
        last = start_pos.get(truck, (0.0, 0.0))
        for (te, p) in pos_tl.get(truck, []):
            if te <= t + 1e-9:
                last = p
        return last

    def driving_at(truck: str, t: float) -> bool:
        return any(a0 < t < a1 - 1e-9 for a0, a1 in drive_iv.get(truck, []))

    drone_pos: dict[str, tuple[float, float]] = {}
    for si, seg in enumerate(segments):
        if si > 0:
            prior = segments[si - 1]
            if abs(prior["t1"] - seg["t0"]) > 1e-6:
                v.append(f"SEG{si}_START_TIME")
            failure = prior.get("failure")
            if failure and prior["t0"] - 1e-9 <= failure["time"] <= prior["t1"] + 1e-9 and abs(prior["t1"] - seg["t0"]) < 1e-6:
                pending_stops.clear()
            st = seg["start"]
            # Prefix completion metadata must agree with this independent
            # replay's already executed clock; never silently adopt a future F.
            for truck, finish in st.get("truck_done", {}).items():
                if abs(truck_finish.get(truck, 0.0) - float(finish)) > 1e-6:
                    v.append(f"SEG{si}_TRUCK_DONE:{truck}:{finish}!={truck_finish.get(truck,0.0)}")
            # Prefix records include any driving committed through the end of a launch.
            for truck in start_pos:
                if truck not in st["truck_pos"] or _d(st["truck_pos"][truck], pos_at(truck, float("inf"))) > 1e-6:
                    v.append(f"SEG{si}_TRUCK_POSITION:{truck}")
            for p, h in st["holder"].items():
                if holder.get(p) != h and p not in delivered:
                    v.append(f"SEG{si}_HOLDER:{p} replay={holder.get(p)} log={h}")
            mode = st.get("drone_mode", {})
            for d, c in st["drone_carrier"].items():
                if mode.get(d) == "AIRBORNE":
                    continue
                if carrier.get(d) != c:
                    v.append(f"SEG{si}_CARRIER:{d} replay={carrier.get(d)} log={c}")
            for d, e in st["energy"].items():
                if abs(energy.get(d, 0.0) - float(e)) > 2e-3:
                    v.append(f"SEG{si}_ENERGY:{d} replay={energy.get(d,0):.4f} log={float(e):.4f}")
        events: list[tuple[float, int, str, dict]] = []
        swap_stages = Counter((s["drone"], s["truck"], s["start"], s["end"])
                              for s in seg["stages"] if s["kind"] == "SWAP")
        for a in seg["actions"]:
            events.append((a["start"], 0, "A", a))
        for s in seg["stages"]:
            events.append((s["start"], 1, "S", s))
        events.sort(key=lambda x: (x[0], x[1]))
        for t, _, kind, rec in events:
            if kind == "A":
                a = rec
                ak = a["kind"]
                # Driver works through real driving, manual work and launch
                # channel use. L.actor is a drone; its truck is explicit.
                work_truck = a.get("truck") if ak == "L" else a.get("actor")
                if ak in ("DRIVE", "G", "P", "L", "R", "U", "W") and work_truck in start_pos:
                    truck_finish[work_truck] = max(truck_finish.get(work_truck, 0.0), float(a["end"]))
                if ak == "DRIVE":
                    frm, to = tuple(a["from"]), tuple(a["to"])
                    dist, dur = a["dist"], a["end"] - a["start"]
                    if abs(dist - phys.truck_speed_m_s * dur) > max(1e-4, 1e-6 * dist):
                        v.append(f"DRIVE_MISMATCH:{a['actor']}@{a['start']:.1f} dist={dist:.1f} dur={dur:.1f}")
                    if abs(_d(frm, to) - dist) > max(1e-4, 1e-6 * dist):
                        v.append(f"DRIVE_GEOMETRY:{a['actor']}@{t:.1f}")
                    if _d(frm, pos_at(a["actor"], a["start"])) > 1e-6:
                        v.append(f"DRIVE_ORIGIN:{a['actor']}@{a['start']:.1f}")
                    # A clipped customer leg commits its destination across recovery segments.
                    truck, ref = a["actor"], a["ref"]
                    partial = a.get("partial", False)
                    expected = pending_stops.pop(truck, None)
                    target_visit = (ref, a.get("visit"))
                    if expected is not None and expected != target_visit:
                        v.append(f"COMMITTED_FIRST_STOP:{truck}:{expected[0]}->{ref}@{t:.1f}:{expected[1]}->{target_visit[1]}")
                    if ref not in destinations:
                        v.append(f"UNKNOWN_DRIVE_DESTINATION:{truck}:{ref}")
                    else:
                        target = destinations[ref]
                        remaining = _d(to, target)
                        if remaining > 1e-6:
                            if not partial or _d(frm, to) + remaining > _d(frm, target) + 1e-6:
                                v.append(f"COMMITTED_FIRST_STOP:{truck}:{ref}:OFF_LEG@{t:.1f}")
                            if partial:
                                pending_stops[truck] = target_visit
                    if any(_overlap(t, a["end"], b0, b1) for b0, b1, _ in manual_iv[truck]):
                        v.append(f"DRIVE_OVERLAP_MANUAL:{truck}@{t:.1f}")
                    if any(_overlap(t, a["end"], b0, b1) for b0, b1 in drive_iv[truck]):
                        v.append(f"DRIVE_OVERLAP:{truck}@{t:.1f}")
                    drive_iv[a["actor"]].append((a["start"], a["end"]))
                    pos_tl[a["actor"]].append((a["end"], to))
                    total_dist += dist
                elif ak in ("G", "P", "R", "U", "W"):
                    # 人工动作：不得与驾驶或其他人工动作重叠
                    for (b0, b1) in drive_iv.get(a["actor"], []):
                        if _overlap(a["start"], a["end"], b0, b1):
                            v.append(f"MANUAL_OVERLAP_DRIVE:{a['actor']}@{a['start']:.1f}")
                            break
                    for (b0, b1, k2) in manual_iv.get(a["actor"], []):
                        if _overlap(a["start"], a["end"], b0, b1):
                            v.append(f"MANUAL_OVERLAP:{a['actor']}@{a['start']:.1f}({k2})")
                            break
                    manual_iv[a["actor"]].append((a["start"], a["end"], ak))
                if ak == "W":
                    d = a.get("drone")
                    k = a["actor"]
                    key = (d, k, t, a["end"])
                    if not swap_stages[key]:
                        v.append(f"SWAP_UNMATCHED_ACTION:{d}@{k}:{t:.1f}")
                        continue
                    swap_stages[key] -= 1
                    if not phys.swap_mode:
                        v.append(f"SWAP_IN_SPEC_MODE:{d}@{t:.1f}")
                    if abs((a["end"] - a["start"]) - phys.swap_s) > 1e-6:
                        v.append(f"SWAP_DURATION:{d}@{t:.1f}")
                    if carrier.get(d) != k:
                        v.append(f"SWAP_NOT_ON_TRUCK:{d} carrier={carrier.get(d)} truck={k}")
                    ac_left[k] = ac_left.get(k, float(phys.spare_batteries)) - 1.0
                    if ac_left[k] < -1e-9:
                        v.append(f"SWAP_SPARES:{k}@{t:.1f} left={ac_left[k]:.0f}")
                    swap_refill += phys.e_cap - energy.get(d, phys.e_cap)
                    n_swaps += 1
                    energy[d] = phys.e_cap
                elif ak == "G":
                    if abs(a["end"] - t - phys.ground_service_s) > 1e-6:
                        v.append(f"G_DURATION:{a['ref']}@{t:.1f}")
                    p = a["ref"]
                    cust = a.get("customer")
                    if p in delivered:
                        v.append(f"DOUBLE_DELIVERY:{p}@{t:.1f}")
                    if cust != inst.parcel_to_customer.get(p):
                        v.append(f"WRONG_DESTINATION:{p}@{cust}")
                    if holder.get(p) not in (f"TRUCK:{a['actor']}", "DEPOT"):
                        v.append(f"G_CUSTODY:{p} holder={holder.get(p)} truck={a['actor']}")
                    c = inst.customer(cust) if cust in inst._by_id else None
                    if c is not None:
                        if driving_at(a["actor"], a["start"]):
                            v.append(f"G_WHILE_DRIVING:{p}@{cust}")
                        if _d((c.x, c.y), pos_at(a["actor"], a["start"])) > 1.0:
                            v.append(f"G_NOT_AT_CUSTOMER:{p}@{cust}")
                    holder[p] = "DELIVERED"
                    delivered.add(p)
                elif ak == "P":
                    d = a.get("drone")
                    if carrier.get(d) != a["actor"] or d in prepared or d in awaiting_handover:
                        v.append(f"P_DRONE_NOT_READY:{d}@{t:.1f}")
                    for p in a.get("payload", []):
                        if holder.get(p) not in (f"TRUCK:{a['actor']}", "DEPOT"):
                            v.append(f"P_CUSTODY:{p} holder={holder.get(p)} truck={a['actor']}")
                        holder[p] = f"DRONE:{a.get('drone')}"
                    prepared[d] = (a["actor"], a["end"], set(a.get("payload", [])))
                elif ak == "R":
                    d = a.get("drone")
                    cust = a.get("customer")
                    c = inst.customer(cust) if cust in inst._by_id else None
                    if c is not None and _d((c.x, c.y), pos_at(a["actor"], a["start"])) > 1.0:
                        v.append(f"R_TRUCK_NOT_THERE:{d}@{cust}")
                    if c is not None and d in drone_pos and _d((c.x, c.y), drone_pos[d]) > 50.0:
                        v.append(f"R_DRONE_NOT_THERE:{d}@{cust}")
                    if d not in carrier or carrier[d] is not None:
                        v.append(f"R_DRONE_NOT_AIRBORNE:{d}@{t:.1f}")
                    # 落地零等待耗电不代表可动用保留电量。
                    emin = phys.e_min
                    if energy.get(d, 0.0) < emin - phys.energy_tol:
                        v.append(f"R_RESERVE:{d}@{t:.1f} E={energy.get(d,0):.4f}")
                    if strategy == "S":
                        launch_truck = a.get("launch_truck")
                        if launch_truck and launch_truck != a["actor"]:
                            v.append(f"S_CROSS_RECOVERY:{d}:{launch_truck}->{a['actor']}@{t:.1f}")
                    reserved[a["actor"]] = reserved.get(a["actor"], 0) + 1
                    occupied = len(onboard.get(a["actor"], set())) + reserved[a["actor"]]
                    if occupied > phys.truck_drone_slots:
                        v.append(f"SLOT_OVER:{a['actor']}@{t:.1f}={occupied}")
                    channel_iv[a["actor"]].append((a["start"], a["end"], "R"))
                    reserved[a["actor"]] -= 1
                    onboard.setdefault(a["actor"], set()).add(d)
                    carrier[d] = a["actor"]
                    if a.get("handover"):
                        awaiting_handover[d] = a
                elif ak == "U":
                    d, truck = a.get("drone"), a["actor"]
                    parcels = a.get("parcels", [])
                    customer = a.get("customer")
                    previous_errors = len(v)
                    if carrier.get(d) != truck:
                        v.append(f"U_CARRIER:{d}@{truck}:{t:.1f}")
                    if abs(a["end"] - t - phys.handover_s) > 1e-6 or a["end"] <= t:
                        v.append(f"U_DURATION:{d}@{t:.1f}")
                    if a.get("prelaunch"):
                        load = prepared.get(d)
                        if load is None or load[0] != truck or t < load[1] - 1e-6 or set(parcels) != load[2]:
                            v.append(f"U_WITHOUT_PREPARATION:{d}@{t:.1f}")
                    else:
                        recovery = awaiting_handover.get(d)
                        if (recovery is None or recovery["actor"] != truck or recovery["ref"] != a["ref"]
                                or abs(t - recovery["end"]) > 1e-6 or set(parcels) != set(recovery["handover"])):
                            v.append(f"U_WITHOUT_RECOVERY:{d}@{t:.1f}")
                        if recovery is not None:
                            if customer and customer != recovery.get("customer"):
                                v.append(f"U_WRONG_SITE:{d}@{t:.1f}")
                            customer = recovery.get("customer")
                    if customer == "DEPOT" and a.get("prelaunch"):
                        stop = (inst.depot_x, inst.depot_y)
                    elif customer in inst._by_id:
                        c = inst.customer(customer)
                        stop = (c.x, c.y)
                    else:
                        stop = None
                    if stop is None or driving_at(truck, t) or _d(stop, pos_at(truck, t)) > 1e-6:
                        v.append(f"U_NOT_PARKED_AT_STOP:{d}@{t:.1f}")
                    if not parcels or len(set(parcels)) != len(parcels) or any(holder.get(p) != f"DRONE:{d}" for p in parcels):
                        v.append(f"U_CUSTODY:{d}@{t:.1f}")
                    if len(v) == previous_errors:
                        for p in parcels:
                            holder[p] = f"TRUCK:{truck}"
                        if a.get("prelaunch"):
                            prepared.pop(d)
                        else:
                            awaiting_handover.pop(d)
                elif ak == "L":
                    d = a.get("drone")
                    lk = a.get("truck")
                    if carrier.get(d) != lk:
                        v.append(f"L_WRONG_TRUCK:{d} carrier={carrier.get(d)} launch={lk}")
                    if lk is not None:
                        channel_iv[lk].append((a["start"], a["end"], "L"))
                        onboard.get(lk, set()).discard(d)
                    prepared.pop(d, None)
                    carrier[d] = None
                    drone_pos[d] = tuple(a.get("pos", (0.0, 0.0)))
            else:
                s = rec
                sk = s["kind"]
                d = s.get("drone")
                dur = s["end"] - s["start"]
                if sk in ("L", "CRUISE", "SERVICE", "WAIT", "R"):
                    aboard = f"DRONE:{d}"
                    carried = sum(parcel_mass[p] for p, owner in holder.items() if owner == aboard)
                    if abs(carried - s.get("mass", 0.0)) > 1e-6:
                        v.append(f"STAGE_PAYLOAD:{d}@{t:.1f}:{sk}")
                if dur > 1e-9:
                    stage_iv.setdefault(d, []).append((s["start"], s["end"], sk))
                if sk == "CRUISE":
                    dist = s["dist"]
                    endpoint = (s["x1"], s["y1"])
                    if d in drone_pos and abs(_d(drone_pos[d], endpoint) - dist) > max(1e-4, 1e-6 * dist):
                        v.append(f"CRUISE_GEOMETRY:{d}@{t:.1f}")
                    if dur > 0 and abs(dist - phys.drone_speed_m_s * dur) > max(1e-4, 1e-6 * dist):
                        v.append(f"CRUISE_MISMATCH:{d}@{s['start']:.1f} dist={dist:.1f} dur={dur:.1f}")
                    energy[d] = energy.get(d, phys.e_cap) - phys.fly_energy_kwh(dist, s.get("mass", 0.0))
                    drone_pos[d] = endpoint
                elif sk == "WAIT" and s.get("landed"):
                    pass  # 降落等待：零能耗，与 schedule.stage_energy 一致
                elif sk in ("SERVICE", "WAIT"):
                    energy[d] = energy.get(d, phys.e_cap) - phys.hover_energy_kwh(dur, s.get("mass", 0.0))
                    if sk == "SERVICE" and s.get("parcel"):
                        p = s["parcel"]
                        if p in delivered:
                            v.append(f"DOUBLE_AIR:{p}@{s['start']:.1f}")
                        if holder.get(p) != f"DRONE:{d}":
                            v.append(f"SERVICE_CUSTODY:{p} holder={holder.get(p)} drone={d}")
                        if s.get("customer") != inst.parcel_to_customer.get(p):
                            v.append(f"SERVICE_WRONG_CUSTOMER:{p}")
                        holder[p] = "DELIVERED"
                        delivered.add(p)
                elif sk == "R":
                    if not s.get("landed"):
                        energy[d] = energy.get(d, phys.e_cap) - phys.hover_energy_kwh(dur, s.get("mass", 0.0))
                        if energy.get(d, 0.0) < phys.e_min - phys.energy_tol:
                            v.append(f"R_END_RESERVE:{d}@{s['start']:.1f}:{energy.get(d, 0):.4f}")
                elif sk == "L":
                    energy[d] = energy.get(d, phys.e_cap) - phys.hover_energy_kwh(dur, s.get("mass", 0.0))
                elif sk in ("ON_TRUCK", "READY"):
                    q = float(s.get("q_ac", 0.0))
                    if q > 0:
                        k = s.get("truck")
                        cap = phys.slot_ac_kw * dur / 3600.0
                        if q > cap + 1e-9:
                            v.append(f"CHARGE_POWER:{d}@{s['start']:.1f} q={q:.4f}>{cap:.4f}")
                        energy[d] = energy.get(d, phys.e_cap) + phys.slot_efficiency * q
                        ac_left[k] = ac_left.get(k, phys.truck_initial_ac_kwh) - q
                        charge_ac += q
                        if ac_left[k] < -1e-9:
                            v.append(f"AC_BUDGET:{k}@{s['start']:.1f} left={ac_left[k]:.4f}")
                    if energy.get(d, 0.0) > phys.e_cap + phys.energy_tol:
                        v.append(f"OVERCHARGE:{d}@{s['start']:.1f}")
                min_energy[d] = min(min_energy.get(d, phys.e_cap), energy.get(d, phys.e_cap))
                if energy.get(d, phys.e_cap) < phys.e_min - phys.energy_tol:
                    v.append(f"STAGE_RESERVE:{d}@{s['start']:.1f}:{sk}:{energy.get(d, 0):.9f}")

            if len(v) > 300:
                break
        for (d, k, start, _), count in swap_stages.items():
            if count:
                v.append(f"SWAP_UNMATCHED_STAGE:{d}@{k}:{start:.1f}")
        # 段内通道全区间检查：同一车 L/R 不得重叠
        for k, ivs in channel_iv.items():
            ordered = sorted(ivs, key=lambda x: (x[0], x[1], x[2]))
            for (a0, a1, ka), (b0, b1, kb) in zip(ordered, ordered[1:]):
                if _overlap(a0, a1, b0, b1):
                    v.append(f"CHANNEL_OVERLAP:{k}:{ka}@{a0:.1f}/{kb}@{b0:.1f}")
        if len(v) > 300:
            break
    for d, ivs in stage_iv.items():
        ordered = sorted(ivs, key=lambda x: (x[0], x[1], x[2]))
        for (a0, a1, ka), (b0, b1, kb) in zip(ordered, ordered[1:]):
            if b0 < a1 - 1e-6:
                v.append(f"DRONE_OVERLAP:{d}:{ka}@{a0:.1f}/{kb}@{b0:.1f}")
    # Independent replay must enforce H when the original evaluator uses hard H.
    # Deliberate original soft-H emergency pricing remains soft.
    if H is not None and not phys.soft_h:
        for truck, finish in sorted(truck_finish.items()):
            if finish > float(H) + 1e-6:
                v.append(f"REPLAY_H_EXCEEDED:{truck}@{finish:.1f}>{float(H):.1f}")
    missing = [c.parcel_id for c in inst.customers if c.parcel_id not in delivered]
    if require_complete and missing:
        v.append(f"UNDELIVERED_FINAL:{len(missing)}:{missing[:5]}")
    if require_complete:
        for truck, ref in pending_stops.items():
            v.append(f"COMMITTED_FIRST_STOP:{truck}:{ref}:NOT_REACHED")
        for truck in set(drive_iv) | set(truck_finish):
            if (drive_iv.get(truck) or truck_finish.get(truck,0.0)>0.0) and (truck not in truck_finish or _d(pos_at(truck, float("inf")), depot) > 1e-6):
                v.append(f"TRUCK_NOT_RETURNED:{truck}")
        for d in sorted(energy):
            truck = carrier.get(d)
            if truck not in start_pos or _d(pos_at(truck, float("inf")), depot) > 1e-6:
                v.append(f"DRONE_NOT_RETURNED:{d}:{truck}")
        for d in awaiting_handover:
            v.append(f"U_MISSING_AFTER_RECOVERY:{d}")
    rep.min_energy = min_energy
    rep.delivered = len(delivered)
    rep.distance_km = total_dist / 1000.0
    rep.driver_s = sum(truck_finish.values())
    rep.charge_ac_kwh = charge_ac
    rep.e_return = {d: float(e) for d, e in energy.items()}
    Qnet = phys.slot_efficiency * charge_ac
    refill = sum(phys.e_cap - energy.get(d, phys.e_cap) for d in energy) + swap_refill
    rep.n_swaps = n_swaps
    overtime = (sum(max(0.0, f - H) for f in truck_finish.values())
                if (phys.soft_h and H is not None) else 0.0)
    rep.cost = (phys.c_km * total_dist / 1000.0 + phys.wage_per_s * rep.driver_s
                + phys.wage_per_s * (phys.overtime_mult - 1.0) * overtime
                + phys.cost_vehicle_kwh * Qnet + phys.cost_depot_kwh * refill)
    for d in sorted(energy):
        rep.terminal[d] = {"carrier": carrier.get(d), "energy": energy.get(d)}
    rep.ok = not v
    return rep
