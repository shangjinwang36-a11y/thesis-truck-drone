"""不可变执行日志的独立全程重放核验.

只读取：班次初态 + 逐段动作/阶段记录。不调用 schedule_plan / allocate_charging。
逐事件按真实区间核对：车辆位移只在 DRIVE 结束时更新；人工动作不得与驾驶重叠；
接机/交付必须在真实到场之后；通道与机位按全区间统计；能量与成本由几何/载荷/充电重算。
"""
from __future__ import annotations

import math
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

    def to_dict(self) -> dict:
        return {"ok": self.ok, "violations": self.violations[:50], "cost": self.cost,
                "distance_km": self.distance_km, "driver_s": self.driver_s,
                "charge_ac_kwh": self.charge_ac_kwh, "e_return": self.e_return,
                "delivered": self.delivered, "n_segments": self.n_segments,
                "terminal": self.terminal}


def _d(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - 1e-9 and b0 < a1 - 1e-9


def verify_replay(inst: Instance, phys: PhysicalConfig, segments: list[dict]) -> ReplayReport:
    rep = ReplayReport(n_segments=len(segments))
    if not segments:
        rep.violations.append("NO_SEGMENTS")
        return rep
    v = rep.violations
    first = segments[0]["start"]
    holder = {p: h for p, h in first["holder"].items()}
    carrier = {d: c for d, c in first["drone_carrier"].items()}
    energy = {d: float(e) for d, e in first["energy"].items()}
    delivered = set(first.get("delivered", []))
    ac_left = {k: float(a) for k, a in first.get("truck_ac", {}).items()}
    start_pos = {k: tuple(p) for k, p in first["truck_pos"].items()}
    truck_finish: dict[str, float] = {}
    total_dist = 0.0
    charge_ac = 0.0
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

    def pos_at(truck: str, t: float):
        last = start_pos.get(truck, (0.0, 0.0))
        for (te, p) in pos_tl.get(truck, []):
            if te <= t + 1e-9:
                last = p
        return last

    def driving_at(truck: str, t: float) -> bool:
        return any(a0 < t < a1 - 1e-9 for a0, a1 in drive_iv.get(truck, []))

    for si, seg in enumerate(segments):
        if si > 0:
            st = seg["start"]
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
        for a in seg["actions"]:
            events.append((a["start"], 0, "A", a))
        for s in seg["stages"]:
            events.append((s["start"], 1, "S", s))
        events.sort(key=lambda x: (x[0], x[1]))
        drone_pos: dict[str, tuple[float, float]] = {}
        for t, _, kind, rec in events:
            if kind == "A":
                a = rec
                ak = a["kind"]
                if ak == "DRIVE":
                    frm, to = tuple(a["from"]), tuple(a["to"])
                    dist, dur = a["dist"], a["end"] - a["start"]
                    if abs(dist - phys.truck_speed_m_s * dur) > max(1e-4, 1e-6 * dist):
                        v.append(f"DRIVE_MISMATCH:{a['actor']}@{a['start']:.1f} dist={dist:.1f} dur={dur:.1f}")
                    if _d(frm, pos_at(a["actor"], a["start"])) > 1.0:
                        v.append(f"DRIVE_ORIGIN:{a['actor']}@{a['start']:.1f}")
                    drive_iv[a["actor"]].append((a["start"], a["end"]))
                    pos_tl[a["actor"]].append((a["end"], to))
                    total_dist += dist
                    if a.get("ref") == "DEPOT" and not a.get("partial", False):
                        truck_finish[a["actor"]] = a["end"]
                elif ak in ("G", "P", "R", "U"):
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
                if ak == "G":
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
                    for p in a.get("payload", []):
                        if holder.get(p) not in (f"TRUCK:{a['actor']}", "DEPOT"):
                            v.append(f"P_CUSTODY:{p} holder={holder.get(p)} truck={a['actor']}")
                        holder[p] = f"DRONE:{a.get('drone')}"
                elif ak == "R":
                    d = a.get("drone")
                    cust = a.get("customer")
                    c = inst.customer(cust) if cust in inst._by_id else None
                    if c is not None and _d((c.x, c.y), pos_at(a["actor"], a["start"])) > 1.0:
                        v.append(f"R_TRUCK_NOT_THERE:{d}@{cust}")
                    if c is not None and d in drone_pos and _d((c.x, c.y), drone_pos[d]) > 50.0:
                        v.append(f"R_DRONE_NOT_THERE:{d}@{cust}")
                    if energy.get(d, 0.0) < phys.e_min - 1e-6:
                        v.append(f"R_RESERVE:{d}@{t:.1f} E={energy.get(d,0):.4f}")
                    reserved[a["actor"]] = reserved.get(a["actor"], 0) + 1
                    occupied = len(onboard.get(a["actor"], set())) + reserved[a["actor"]]
                    if occupied > phys.truck_drone_slots:
                        v.append(f"SLOT_OVER:{a['actor']}@{t:.1f}={occupied}")
                    channel_iv[a["actor"]].append((a["start"], a["end"], "R"))
                    reserved[a["actor"]] -= 1
                    onboard.setdefault(a["actor"], set()).add(d)
                    carrier[d] = a["actor"]
                elif ak == "U":
                    for p in a.get("parcels", []):
                        holder[p] = f"TRUCK:{a['actor']}"
                elif ak == "L":
                    d = a.get("drone")
                    lk = a.get("truck")
                    if carrier.get(d) != lk:
                        v.append(f"L_WRONG_TRUCK:{d} carrier={carrier.get(d)} launch={lk}")
                    if lk is not None:
                        channel_iv[lk].append((a["start"], a["end"], "L"))
                        onboard.get(lk, set()).discard(d)
                    carrier[d] = None
                    drone_pos[d] = tuple(a.get("pos", (0.0, 0.0)))
            else:
                s = rec
                sk = s["kind"]
                d = s.get("drone")
                dur = s["end"] - s["start"]
                if sk == "CRUISE":
                    dist = s["dist"]
                    if dur > 0 and abs(dist - phys.drone_speed_m_s * dur) > max(1e-4, 1e-6 * dist):
                        v.append(f"CRUISE_MISMATCH:{d}@{s['start']:.1f} dist={dist:.1f} dur={dur:.1f}")
                    energy[d] = energy.get(d, phys.e_cap) - phys.fly_energy_kwh(dist, s.get("mass", 0.0))
                    drone_pos[d] = (s["x1"], s["y1"])
                elif sk in ("SERVICE", "WAIT"):
                    energy[d] = energy.get(d, phys.e_cap) - phys.hover_energy_kwh(dur, s.get("mass", 0.0))
                    if sk == "SERVICE" and s.get("parcel"):
                        p = s["parcel"]
                        if holder.get(p) != f"DRONE:{d}":
                            v.append(f"SERVICE_CUSTODY:{p} holder={holder.get(p)} drone={d}")
                        if s.get("customer") != inst.parcel_to_customer.get(p):
                            v.append(f"SERVICE_WRONG_CUSTOMER:{p}")
                        holder[p] = "DELIVERED"
                        delivered.add(p)
                elif sk == "R":
                    energy[d] = energy.get(d, phys.e_cap) - phys.hover_energy_kwh(dur, s.get("mass", 0.0))
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
                    if energy.get(d, 0.0) > phys.e_cap + 1e-6:
                        v.append(f"OVERCHARGE:{d}@{s['start']:.1f}")
            if len(v) > 300:
                break
        # 段内通道全区间检查：同一车 L/R 不得重叠
        for k, ivs in channel_iv.items():
            for (a0, a1, ka), (b0, b1, kb) in zip(ivs, ivs[1:]):
                if _overlap(a0, a1, b0, b1):
                    v.append(f"CHANNEL_OVERLAP:{k}:{ka}@{a0:.1f}/{kb}@{b0:.1f}")
        if len(v) > 300:
            break
    missing = [c.parcel_id for c in inst.customers if c.parcel_id not in delivered]
    if missing:
        v.append(f"UNDELIVERED_FINAL:{len(missing)}:{missing[:5]}")
    rep.delivered = len(delivered)
    rep.distance_km = total_dist / 1000.0
    rep.driver_s = sum(truck_finish.values())
    rep.charge_ac_kwh = charge_ac
    rep.e_return = {d: float(e) for d, e in energy.items()}
    Qnet = phys.slot_efficiency * charge_ac
    refill = sum(phys.e_cap - energy.get(d, phys.e_cap) for d in energy)
    rep.cost = (phys.c_km * total_dist / 1000.0 + phys.wage_per_s * rep.driver_s
                + phys.cost_vehicle_kwh * Qnet + phys.cost_depot_kwh * refill)
    for d in sorted(energy):
        rep.terminal[d] = {"carrier": carrier.get(d), "energy": energy.get(d)}
    rep.ok = not v
    return rep
