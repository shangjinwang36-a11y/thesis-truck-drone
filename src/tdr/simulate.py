"""事件仿真：真实轨迹推进、到点观察、状态截断、恢复调用与回合执行."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .alns import Budget, SearchStats, SolveContext, SolveResult, optimize
from .config import AlgorithmConfig, PhysicalConfig, home_truck
from .data import Instance
from .evaluate import Evaluation, evaluate_plan
from .hidden_world import HiddenWorld, Observation, TestWorld
from .plan import Plan, Sortie
from .recovery import initial_recovery
from .schedule import (DroneStart, StartState, Timeline, allocate_charging, initial_state,
                       schedule_plan, stage_energy)

INF = float("inf")


@dataclass(frozen=True)
class AirArrival:
    time: float
    parcel: str
    customer: str
    drone: str
    sid: int


def air_arrivals(plan: Plan, tl: Timeline, inst: Instance) -> list[AirArrival]:
    out = []
    for d, stages in tl.drone_stages.items():
        for st in stages:
            if st.kind == "SERVICE" and st.parcel and not st.resumed:
                out.append(AirArrival(st.start, st.parcel, inst.parcel_to_customer[st.parcel],
                                      d, st.sid or -1))
    out.sort(key=lambda a: (a.time, a.parcel))
    return out


def _lerp(p, q, t):
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def truck_state_at(truck: str, t: float, plan: Plan, tl: Timeline, inst: Instance):
    depot = (inst.depot_x, inst.depot_y)
    route = plan.routes.get(truck, [])
    for a in tl.actions:
        if a.actor != truck or a.kind != "DRIVE":
            continue
        if a.start - 1e-9 <= t <= a.end + 1e-9:
            frac = 0.0 if a.end - a.start < 1e-12 else (t - a.start) / (a.end - a.start)
            frac = min(1.0, max(0.0, frac))
            pos = _lerp(a.info.get("from", depot), a.info.get("to", depot), frac)
            if a.ref == "DEPOT":
                return pos, max(0.0, a.end - t), len(route), False
            idx = next((i for i, vid in enumerate(route)
                        if plan.visits[vid].customer == a.ref), len(route))
            return pos, max(0.0, a.end - t), idx, False
    for i, vid in enumerate(route):
        arr = tl.visit_arr.get(vid, 0.0)
        dep = tl.visit_dep.get(vid, 0.0)
        if arr - 1e-9 <= t <= dep + 1e-9:
            c = inst.customer(plan.visits[vid].customer)
            return (c.x, c.y), 0.0, i, False
    fin = tl.truck_finish.get(truck, 0.0)
    if t >= fin - 1e-9:
        return depot, 0.0, len(route), True
    return depot, 0.0, len(route), False


def _charge_index(stages, i):
    c = -1
    for j in range(i + 1):
        st = stages[j]
        if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
            c += 1
    return c


def _energy_at(tl: Timeline, phys: PhysicalConfig, d: str, t: float):
    stages = tl.drone_stages[d]
    energies = tl.drone_energy.get(d, [])
    if not stages:
        return phys.e_cap, -1
    e_prev = energies[0]
    if t < stages[0].start - 1e-9:
        return e_prev, -1
    for i, st in enumerate(stages):
        if st.start - 1e-9 <= t <= st.end + 1e-9:
            frac = 0.0 if st.end - st.start < 1e-12 else (t - st.start) / (st.end - st.start)
            frac = min(1.0, max(0.0, frac))
            if st.kind == "SWAP":
                # 换电：完成即满电（W 动作在截断中被视为不可分割，故 t<end 时仍是旧电池）
                return (energies[i + 1] if t >= st.end - 1e-9 else e_prev), i
            if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
                q = tl.q_by_stage.get(f"{d}#{_charge_index(stages, i)}", 0.0)
                return e_prev + phys.slot_efficiency * q * frac, i
            if st.kind == "CRUISE":
                return e_prev - phys.fly_energy_kwh(st.dist * frac, st.mass), i
            return e_prev - stage_energy(st, phys) * frac, i
        e_prev = energies[i + 1]
    return energies[-1], len(stages) - 1


def _drone_pos_at(stages, idx: int, t: float, inst: Instance):
    """按已执行阶段回放得到 t 时刻无人机坐标（服务/等待阶段沿用客户点）."""
    pos = None
    for j in range(0, min(idx, len(stages) - 1) + 1):
        st = stages[j]
        if st.kind == "L":
            pos = (st.x0, st.y0)
        elif st.kind == "CRUISE":
            if j == idx:
                frac = 0.0 if st.end - st.start < 1e-12 else (t - st.start) / (st.end - st.start)
                frac = min(1.0, max(0.0, frac))
                pos = _lerp((st.x0, st.y0), (st.x1, st.y1), frac)
            else:
                pos = (st.x1, st.y1)
        elif st.kind == "SERVICE" and st.parcel:
            c = inst.customer(inst.parcel_to_customer[st.parcel])
            pos = (c.x, c.y)
    return pos


def _ghost_action(a, failed_drone: str | None, t_fail: float | None) -> bool:
    """失败揭示后，失败机在旧计划里的后续 P/L/R/U 不会发生（它在原地悬停等待截断），
    不应计入执行日志，也不应顺延截断点（第二轮修复）。"""
    if failed_drone is None or t_fail is None:
        return False
    if a.kind not in ("P", "L", "R", "U"):
        return False
    drone = a.actor if a.kind == "L" else a.info.get("drone")
    return drone == failed_drone and a.start >= t_fail - 1e-6


def compute_cut(tl: Timeline, t_fail: float, failed_drone: str) -> float:
    t_cut = t_fail
    for a in tl.actions:
        if _ghost_action(a, failed_drone, t_fail):
            continue
        if a.kind in ("G", "P", "R", "U", "W") and a.start < t_fail < a.end:
            t_cut = max(t_cut, a.end)
    for d, stages in tl.drone_stages.items():
        for st in stages:
            if st.kind == "L" and st.start < t_fail < st.end:
                t_cut = max(t_cut, st.end)
            if st.kind == "SERVICE" and d != failed_drone and st.start < t_fail < st.end:
                t_cut = max(t_cut, st.end)
    # 第二轮修复：若截断点恰为回收结束(R 末)而交接卸货 U 紧随其后，则 U 必须随本段完成，
    # 否则回放认为机上票仍在无人机、而计划已把它记在回收车名下(SEGk_HOLDER / G_CUSTODY)。
    # 同理：延长后的截断点若又落入别的固定时长人工动作(G/P/R/U)或放飞 L 的内部，继续顺延到其结束
    # （未完成的固定动作在段内不产生事件，会造成日志与回放的保管者不一致），直到不动点。
    for _ in range(64):
        moved = False
        for a in tl.actions:
            if _ghost_action(a, failed_drone, t_fail):
                continue
            if a.kind in ("G", "P", "R", "U", "W") and a.start < t_cut < a.end - 1e-9:
                t_cut = a.end
                moved = True
            elif a.kind == "U" and abs(a.start - t_cut) < 1e-6 and a.end > t_cut:
                t_cut = a.end
                moved = True
        for d, stages in tl.drone_stages.items():
            for st in stages:
                if d == failed_drone and st.start >= t_fail - 1e-6:
                    continue
                if st.kind == "L" and st.start < t_cut < st.end - 1e-9:
                    t_cut = st.end
                    moved = True
        if not moved:
            break
    return t_cut


def _truck_is_driving(truck: str, t: float, tl: Timeline) -> bool:
    for a in tl.actions:
        if a.actor == truck and a.kind == "DRIVE" and a.ref != "DEPOT":
            if a.start < t < a.end - 1e-9:
                return True
    return False


def _compute_holders(new: Plan, plan: Plan, inst: Instance, delivered: set[str],
                     prev_state: StartState | None,
                     inflight: set[int] | None = None) -> dict[str, str]:
    holders: dict[str, str] = {}
    drone_of: dict[str, str] = {}
    handed: dict[str, str] = {}      # 已回收并交接给回收车、尚未地送的票 → 回收车
    for s in new.sorties.values():
        if s.started:
            for p in s.air + s.handover:
                drone_of[p] = s.drone
    # 原计划中在飞（started）的航次：其机上票在快照时确实在机上
    # 修复（第一轮顺带）：只有"此刻仍在飞"的残段，机上票才算无人机保管；
    # 已经回收并交接（R、U 完成）的残段，其交接票已转给回收车，保管者是该车（等待地送）。
    for s in plan.sorties.values():
        if s.started and s.start_time <= (prev_state.t0 if prev_state else 0.0) + 1e9:
            if inflight is not None and s.sid not in inflight and s.rec_vid in plan.visits:
                rec_truck = plan.visits[s.rec_vid].truck
                for p in s.air + s.handover:
                    if p not in delivered:
                        handed.setdefault(p, rec_truck)
                continue
            for p in s.air + s.handover:
                if p not in delivered:
                    drone_of.setdefault(p, s.drone)
    for v in new.visits.values():
        for p in v.ground:
            holders.setdefault(p, f"TRUCK:{v.truck}")
    for s in new.sorties.values():
        if not s.started:
            for p in s.air + s.handover:
                holders.setdefault(p, f"TRUCK:{s.truck}")
    for p in inst.parcel_mass:
        if p in delivered:
            holders[p] = "DELIVERED"
        elif p in drone_of:
            holders[p] = f"DRONE:{drone_of[p]}"
        elif p in handed:
            holders[p] = f"TRUCK:{handed[p]}"
        elif p in holders:
            continue
        else:
            for v in plan.visits.values():
                if p in v.ground:
                    holders[p] = f"TRUCK:{v.truck}"
                    break
            else:
                for s in plan.sorties.values():
                    if p in s.air or p in s.handover:
                        holders[p] = f"TRUCK:{s.truck}"
                        break
                else:
                    holders[p] = prev_state.parcel_holder.get(p) if prev_state else "DEPOT"
    return holders


def _in_flight(plan: Plan, tl: Timeline, t_cut: float) -> set[int]:
    out: set[int] = set()
    for s in plan.sorties.values():
        rt = tl.rec_times.get(s.sid)
        if s.started:
            end = rt[1] if rt else INF
            if s.start_time <= t_cut < end - 1e-9:
                out.add(s.sid)
        else:
            lt = tl.launch_times.get(s.sid)
            if lt and rt and lt[1] <= t_cut < rt[1] - 1e-9:
                out.add(s.sid)
    return out


def truncate(plan: Plan, tl: Timeline, inst: Instance, phys: PhysicalConfig,
             t_cut: float, t_fail: float, failed_sid: int, failed_parcel: str,
             failed_drone: str, prev_state: StartState | None = None
             ) -> tuple[Plan, StartState, dict[str, Any]]:
    delivered: set[str] = set()
    for a in tl.actions:
        if a.kind == "G" and a.end <= t_cut + 1e-9:
            delivered.add(a.ref)
    for d, stages in tl.drone_stages.items():
        for st in stages:
            if st.kind == "SERVICE" and st.parcel and st.end <= t_cut + 1e-9:
                if d == failed_drone and st.start >= t_fail - 1e-6:
                    continue        # 第二轮修复：失败揭示后该机原地悬停，旧计划里它之后的服务不会发生
                delivered.add(st.parcel)
    delivered.discard(failed_parcel)
    prev_delivered = set(prev_state.delivered) if prev_state is not None else set()
    all_delivered = prev_delivered | delivered
    prefix_dist = 0.0
    for a in tl.actions:
        if a.kind != "DRIVE":
            continue
        leg = a.info.get("dist", 0.0)
        if a.end <= t_cut + 1e-9:
            prefix_dist += leg
        elif a.start < t_cut:
            prefix_dist += leg * (t_cut - a.start) / max(1e-9, a.end - a.start)
    q_prefix: dict[str, float] = {k: 0.0 for k in plan.routes}
    for d, stages in tl.drone_stages.items():
        cidx = -1
        for st in stages:
            if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
                cidx += 1
                q = tl.q_by_stage.get(f"{d}#{cidx}", 0.0)
                if st.end <= t_cut + 1e-9:
                    q_prefix[st.truck] = q_prefix.get(st.truck, 0.0) + q
                elif st.start < t_cut:
                    q_prefix[st.truck] = q_prefix.get(st.truck, 0.0) + q * (t_cut - st.start) / (st.end - st.start)
    swap_refill_prefix = 0.0
    if phys.swap_mode:
        # 换电：q_prefix[卡车] 改记"已用备用电池块数"；换下电池的待补电量计入 prefix_refill_kwh
        for d, stages in tl.drone_stages.items():
            energies = tl.drone_energy.get(d, [])
            for i, st_ in enumerate(stages):
                if st_.kind != "SWAP" or st_.end > t_cut + 1e-9:
                    continue
                if d == failed_drone and st_.start >= t_fail - 1e-6:
                    continue
                q_prefix[st_.truck] = q_prefix.get(st_.truck, 0.0) + 1.0
                swap_refill_prefix += phys.e_cap - energies[i]
    base_dist = prev_state.prefix_distance_m if prev_state is not None else 0.0
    base_ac = prev_state.prefix_ac_kwh if prev_state is not None else 0.0
    st = StartState(t0=t_cut, delivered=set(all_delivered),
                    prefix_distance_m=base_dist + prefix_dist,
                    prefix_ac_kwh=base_ac + (0.0 if phys.swap_mode else sum(q_prefix.values())),
                    prefix_refill_kwh=(prev_state.prefix_refill_kwh if prev_state is not None else 0.0)
                    + swap_refill_prefix)
    inflight = _in_flight(plan, tl, t_cut) | {failed_sid}
    new = plan.clone()
    for truck in plan.routes:
        pos, first_travel, start_idx, finished = truck_state_at(truck, t_cut, plan, tl, inst)
        st.truck_start_pos[truck] = pos
        st.truck_start_time[truck] = t_cut
        st.truck_first_travel_s[truck] = first_travel
        st.truck_ready_time[truck] = t_cut
        _ac0 = float(phys.spare_batteries) if phys.swap_mode else phys.truck_initial_ac_kwh
        prev_ac = prev_state.truck_ac.get(truck, _ac0) if prev_state else _ac0
        st.truck_ac[truck] = max(0.0, prev_ac - q_prefix.get(truck, 0.0))
        new.routes[truck] = [] if finished else list(plan.routes[truck][start_idx:])
        st.truck_fixed_first[truck] = (not finished) and _truck_is_driving(truck, t_cut, tl)
        st.truck_min_insert[truck] = 1 if st.truck_fixed_first[truck] else 0
        if finished and truck in tl.truck_finish:
            st.truck_done[truck] = tl.truck_finish[truck]
    keep_vids = {vid for r in new.routes.values() for vid in r}
    for vid in list(new.visits):
        if vid not in keep_vids:
            del new.visits[vid]
    for v in new.visits.values():
        v.ground = [p for p in v.ground if p not in all_delivered]
    freed: list[str] = []
    unloaded: list[dict] = []
    p_done_sids = {int(a.ref[1:]) for a in tl.actions
                   if a.kind == "P" and a.ref.startswith("S") and a.end <= t_cut + 1e-9}
    def _drop(s) -> None:
        ps = [p for p in s.air + s.handover if p not in all_delivered]
        if s.sid in p_done_sids and ps:
            unloaded.append({"truck": s.truck, "drone": s.drone, "parcels": ps})
        freed.extend(ps)
    # 清理已执行/非法航次（在飞与失败航次另行处理）
    for s in list(new.sorties.values()):
        if s.sid == failed_sid or s.sid in inflight:
            continue
        rt = tl.rec_times.get(s.sid)
        if rt is not None and rt[1] <= t_cut + 1e-9:
            _drop(s)
            new.remove_sortie(s.sid)
            continue
        if s.rec_vid not in new.visits or (s.launch_vid is not None and s.launch_vid not in new.visits):
            _drop(s)
            new.remove_sortie(s.sid)
            continue
        s.air = [p for p in s.air if p not in all_delivered]
        s.handover = [p for p in s.handover if p not in all_delivered]
    # 无人机状态与空中残段
    st.dispatched = set(prev_state.dispatched) if prev_state is not None else set()
    for d in [f"d{i+1}" for i in range(phys.drone_count)]:
        stages = tl.drone_stages.get(d, [])
        energy, idx = _energy_at(tl, phys, d, t_cut)
        cur = None
        for sid in plan.drone_sorties.get(d, []):
            if sid in inflight:
                cur = sid
        if d == failed_drone:
            # 第四轮 H2：失败机原地悬停，它在旧计划里之后的航次(幽灵航次)不是“在飞”；
            # 当前航次必为失败航次，否则失败航次被当成已完成弹出机体链(NO_FRAGMENT)。
            cur = failed_sid
        launched = [sid for sid in plan.drone_sorties.get(d, [])
                    if ((tl.launch_times.get(sid) or (0, 0, None))[1] <= t_cut + 1e-9)
                    or (plan.sorties[sid].started and plan.sorties[sid].start_time <= t_cut + 1e-9)]
        if launched:
            st.dispatched.add(d)
        carrier = None
        frag = None
        if cur is not None:
            o = plan.sorties[cur]
            stage = stages[idx] if 0 <= idx < len(stages) else None
            if stage is not None:
                if stage.kind == "L":
                    pos = (stage.x1, stage.y1)
                elif stage.kind in ("CRUISE", "SERVICE", "WAIT"):
                    pos = _drone_pos_at(stages, idx, t_cut, inst)
                    if pos is None:
                        # 残段首阶段即 WAIT/SERVICE(无停靠点)：沿用残段起点坐标（第二轮修复：连续失败同一时刻截断）
                        pos = o.start_pos or st.truck_start_pos.get(home_truck(d), (inst.depot_x, inst.depot_y))
                else:
                    pos = o.start_pos or st.truck_start_pos.get(home_truck(d), (inst.depot_x, inst.depot_y))
            else:
                pos = o.start_pos or (inst.depot_x, inst.depot_y)
            if cur == failed_sid:
                mass_onboard = sum(inst.parcel_mass[p] for p in o.air + o.handover if p not in all_delivered)
                energy_f, _ = _energy_at(tl, phys, d, t_fail)
                energy = energy_f - phys.hover_energy_kwh(max(0.0, t_cut - t_fail), mass_onboard)
                c = inst.customer(inst.parcel_to_customer[failed_parcel])
                pos = (c.x, c.y)
                remain_air = [p for p in o.air if p not in all_delivered and p != failed_parcel]
                hand = [p for p in o.handover if p not in all_delivered]
                if failed_parcel not in hand:
                    hand.append(failed_parcel)
                rec_keep = o.rec_vid if o.rec_vid in new.visits else -1
                frag = Sortie(failed_sid, d, o.truck, None, "AIR", 0.0, remain_air, rec_keep,
                              hand, True, t_cut, pos, 0, 0, o.launch_truck or o.truck)
            else:
                remain_air = [p for p in o.air if p not in all_delivered]
                hand = [p for p in o.handover if p not in all_delivered]
                rec_keep = o.rec_vid if o.rec_vid in new.visits else -1
                frag = Sortie(cur, d, o.truck, None, "AIR", 0.0, remain_air, rec_keep,
                              hand, True, t_cut, pos, 0, 0, o.launch_truck or o.truck)
            new.sorties[frag.sid] = frag
            st.drone_start[d] = DroneStart("AIRBORNE", None, t_cut, pos, energy)
            if (cur != failed_sid and stage is not None and stage.kind == "SERVICE" and stage.parcel
                    and stage.start < t_cut < stage.end - 1e-9 and remain_air and remain_air[0] == stage.parcel):
                # 第三轮：截断落在别机正在进行的空中服务内部，记下已完成时长，残段只补完剩余部分
                st.drone_start[d].service_parcel = stage.parcel
                st.drone_start[d].service_done_s = stage.svc_done0 + (t_cut - stage.start)
            st.drone_carrier[d] = o.truck or home_truck(d)
        else:
            stage = stages[idx] if 0 <= idx < len(stages) else None
            if stage is not None and stage.truck:
                carrier = stage.truck
            if carrier is None:
                for sd in reversed(stages):
                    if sd.truck:
                        carrier = sd.truck
                        break
            carrier = carrier or home_truck(d)
            st.drone_start[d] = DroneStart("ON_TRUCK", carrier, t_cut,
                                           st.truck_start_pos.get(carrier), energy)
            st.drone_carrier[d] = carrier
        st.drone_energy[d] = energy
        # 无人机未来航次
        keep: list[int] = []
        for sid in new.drone_sorties.get(d, []):
            if sid not in new.sorties:
                continue
            s = new.sorties[sid]
            if sid == cur:
                keep.append(sid)
                continue
            lt = tl.launch_times.get(sid)
            if s.started:
                keep.append(sid)
                continue
            if lt is None:
                keep.append(sid)
                continue
            if lt[1] <= t_cut + 1e-9:
                freed.extend([p for p in s.air + s.handover if p not in all_delivered])
                new.sorties.pop(sid, None)
                continue
            p_done = any(a.kind == "P" and a.ref == f"S{sid}" and a.end <= t_cut + 1e-9
                         for a in tl.actions)
            if p_done:
                ps_ = [p for p in s.air + s.handover if p not in all_delivered]
                if ps_:
                    # 第二轮修复：装机(P)已完成、放飞(L)未开始即遇截断——机上票须经零时长 U 卸回原车，
                    # 否则回放仍认为票在无人机上(SEGk_HOLDER)而计划已把它记在车上。
                    unloaded.append({"truck": s.truck, "drone": s.drone, "parcels": ps_})
                freed.extend(ps_)
                new.sorties.pop(sid, None)
                continue
            keep.append(sid)
        new.drone_sorties[d] = keep
        if not keep:
            new.drone_sorties.pop(d, None)
    for d in list(new.drone_sorties):
        new.drone_sorties[d] = [x for x in new.drone_sorties[d] if x in new.sorties]
        if not new.drone_sorties[d]:
            new.drone_sorties.pop(d)
    # 最终清理：引用已不存在访问的非在飞航次
    for s in list(new.sorties.values()):
        if s.sid == failed_sid or s.sid in inflight:
            continue
        if s.rec_vid not in new.visits or (s.launch_vid is not None and s.launch_vid not in new.visits):
            _drop(s)
            new.remove_sortie(s.sid)
    for d in list(new.drone_sorties):
        new.drone_sorties[d] = [x for x in new.drone_sorties[d] if x in new.sorties]
        if not new.drone_sorties[d]:
            new.drone_sorties.pop(d)
    st.parcel_holder = _compute_holders(new, plan, inst, all_delivered, prev_state, inflight)
    info = {"unloaded": unloaded, "delivered": all_delivered, "prefix_dist": prefix_dist, "q_prefix": q_prefix,
            "t_cut": t_cut, "freed": sorted(set(freed)), "inflight": sorted(inflight)}
    return new, st, info


# ---------------------------------------------------------------------------
# 执行日志：按段收集不可变动作记录
# ---------------------------------------------------------------------------
def _state_record(st: StartState, phys: PhysicalConfig) -> dict:
    return {
        "holder": dict(st.parcel_holder),
        "drone_carrier": dict(st.drone_carrier),
        "energy": {d: float(e) for d, e in st.drone_energy.items()},
        "delivered": sorted(st.delivered),
        "truck_pos": {k: list(v) for k, v in st.truck_start_pos.items()},
        "truck_ac": {k: float(v) for k, v in st.truck_ac.items()},
        "dispatched": sorted(st.dispatched),
        "drone_mode": {d: (st.drone_start[d].kind if d in st.drone_start else "ON_TRUCK")
                       for d in st.drone_carrier},
    }


def collect_segment(plan: Plan, tl: Timeline, inst: Instance, phys: PhysicalConfig,
                    t0: float, t1: float, start_state: StartState,
                    failed_parcel: str | None = None, failed_time: float | None = None,
                    failed_drone: str | None = None) -> dict:
    actions: list[dict] = []
    for a in tl.actions:
        if a.end <= t0 + 1e-9 or a.start >= t1 - 1e-9:
            continue
        if _ghost_action(a, failed_drone, failed_time):
            continue
        start = max(a.start, t0)
        end = min(a.end, t1)
        if end <= start + 1e-12 and a.kind != "DRIVE":
            continue
        partial = bool(end < a.end - 1e-9 or start > a.start + 1e-9)
        if partial and a.kind in ("G", "P", "R", "U", "L", "W"):
            # 未完成的固定时长动作不产生交付/装卸/回收事件（其剩余时间由快照承接）
            continue
        rec = {"kind": a.kind, "actor": a.actor, "start": start, "end": end, "ref": a.ref,
               "partial": partial}
        if a.kind == "DRIVE":
            span = a.end - a.start
            f0 = 0.0 if span < 1e-12 else (start - a.start) / span
            f1 = 1.0 if span < 1e-12 else (end - a.start) / span
            frm = a.info.get("from", (0.0, 0.0))
            to = a.info.get("to", (0.0, 0.0))
            p0 = (frm[0] + (to[0] - frm[0]) * f0, frm[1] + (to[1] - frm[1]) * f0)
            p1 = (frm[0] + (to[0] - frm[0]) * f1, frm[1] + (to[1] - frm[1]) * f1)
            rec["from"] = [p0[0], p0[1]]
            rec["to"] = [p1[0], p1[1]]
            rec["dist"] = a.info.get("dist", 0.0) * (f1 - f0)
        elif a.kind == "G":
            rec["customer"] = a.info.get("customer")
        elif a.kind == "W":
            rec["drone"] = a.info.get("drone")
        elif a.kind == "P":
            rec["drone"] = a.info.get("drone")
            so = plan.sorties.get(int(a.ref[1:])) if a.ref.startswith("S") else None
            rec["payload"] = list(so.payload_ids) if so else []
        elif a.kind in ("R", "U"):
            rec["drone"] = a.info.get("drone")
            rec["customer"] = a.info.get("customer")
            sid0 = int(a.ref[1:]) if a.ref.startswith("S") else None
            so0 = plan.sorties.get(sid0) if sid0 is not None else None
            if so0 is not None:
                rec["launch_truck"] = so0.launch_truck or so0.truck
                if a.kind == "R":
                    rec["onboard"] = list(so0.air) + list(so0.handover)
                    rec["handover"] = list(so0.handover)
            if a.kind == "U":
                rec["parcels"] = list(a.info.get("parcels", []))
        elif a.kind == "L":
            rec["drone"] = a.actor
            rec["truck"] = a.info.get("truck")
            sid = int(a.ref[1:]) if a.ref.startswith("S") else None
            so = plan.sorties.get(sid) if sid is not None else None
            rec["mass"] = sum(inst.parcel_mass[p] for p in so.payload_ids) if so else 0.0
            rec["pos"] = list(a.info.get("pos", (0.0, 0.0)))
        actions.append(rec)
    stages: list[dict] = []
    for d, lst in tl.drone_stages.items():
        cidx = -1
        post_fail_mass: float | None = None
        for st in lst:
            if (failed_drone == d and failed_time is not None and failed_parcel is not None
                    and st.start >= failed_time - 1e-6 and st.end > t0 + 1e-9 and st.start < t1 - 1e-9):
                # 第二轮修复：失败揭示后无人机原地悬停(带原机载质量)直到截断点；
                # 不再按旧计划的后续 CRUISE/SERVICE 阶段记账(截断点被顺延较长时与快照能量不一致)。
                if post_fail_mass is None:
                    post_fail_mass = next((x.mass for x in lst if x.kind == "SERVICE"
                                           and x.parcel == failed_parcel
                                           and abs(x.start - failed_time) < 1e-6), 0.0)
                if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
                    cidx += 1
                continue
            if st.start >= t1 - 1e-9 or st.end <= t0 + 1e-9:
                if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
                    cidx += 1
                continue
            is_charge = st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck
            if is_charge:
                cidx += 1
            end = min(st.end, t1)
            start = max(st.start, t0)
            frac = 0.0 if st.end - st.start < 1e-12 else (end - start) / (st.end - st.start)
            rec = {"kind": st.kind, "drone": d, "start": start, "end": end,
                   "truck": st.truck, "mass": st.mass}
            if end < st.end - 1e-9 and st.kind in ("R", "L"):
                # 跨段截断的回收/放飞只记悬停能耗，不改变 custody/机位状态
                rec["kind"] = "WAIT"
            if is_charge:
                rec["q_ac"] = tl.q_by_stage.get(f"{d}#{cidx}", 0.0) * frac
            if st.kind == "CRUISE":
                rec["dist"] = st.dist * frac
                rec["x1"] = st.x0 + (st.x1 - st.x0) * frac
                rec["y1"] = st.y0 + (st.y1 - st.y0) * frac
            elif st.kind == "SERVICE":
                canceled = (failed_parcel is not None and st.parcel == failed_parcel
                            and failed_time is not None and abs(st.start - failed_time) < 1e-6)
                clipped = end < st.end - 1e-9
                if canceled or clipped:
                    # 失败揭示后的服务不执行；跨段截断的服务只记等待，交付在完成段记录
                    rec["kind"] = "WAIT"
                else:
                    rec["parcel"] = st.parcel
                    rec["customer"] = inst.parcel_to_customer.get(st.parcel) if st.parcel else None
            stages.append(rec)
        if post_fail_mass is not None and t1 > max(t0, failed_time) + 1e-9:
            stages.append({"kind": "WAIT", "drone": d, "start": max(t0, failed_time), "end": t1,
                           "truck": None, "mass": post_fail_mass})
    return {"t0": t0, "t1": t1, "start": _state_record(start_state, phys),
            "actions": actions, "stages": stages}


# ---------------------------------------------------------------------------
# 回合执行
# ---------------------------------------------------------------------------
@dataclass
class ReplanRecord:
    index: int
    time_s: float
    observed_parcels: list[str]
    status: str
    cost: float | None
    z: float | None
    stats: dict[str, Any] = field(default_factory=dict)
    t_cut: float = 0.0
    recovery: str = ""


@dataclass
class EpisodeResult:
    case_id: str
    strategy: str
    environment_seed: int
    status: str
    observations: list[Observation] = field(default_factory=list)
    replans: list[ReplanRecord] = field(default_factory=list)
    plan: Plan | None = None
    evaluation: Evaluation | None = None
    H: float | None = None
    audit: Any = None
    wall_s: float = 0.0
    replan_times: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)
    replay: Any = None


def derive_rngs(base_seed: int, case_id: str, phase: str, replan_index: int) -> dict[str, random.Random]:
    import hashlib
    out = {}
    for name in ("operator", "destroy", "accept"):
        text = f"tdr_v61|{base_seed}|{case_id}|{phase}|{replan_index}|{name}"
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        out[name] = random.Random(seed)
    return out


def initial_run_state(plan: Plan, inst: Instance, phys: PhysicalConfig) -> StartState:
    """班次初态：所有包裹按名义计划装入首个承运车（地面票直接装车，空送票在首次 P 时装机）."""
    st = initial_state(inst, phys)
    holder: dict[str, str] = {}
    for v in plan.visits.values():
        for p in v.ground:
            holder[p] = f"TRUCK:{v.truck}"
    for s0 in plan.sorties.values():
        for p in s0.air + s0.handover:
            holder.setdefault(p, f"TRUCK:{s0.truck}")
    for p in inst.parcel_mass:
        holder.setdefault(p, "DEPOT")
    st.parcel_holder = holder
    st.drone_carrier = {f"d{i+1}": phys.home_truck(f"d{i+1}") for i in range(phys.drone_count)}
    st.drone_energy = {f"d{i+1}": phys.e_cap for i in range(phys.drone_count)}
    return st


def run_episode(inst: Instance, nominal_plan: Plan, nominal_ev: Evaluation, H: float,
                phys: PhysicalConfig, world, strategy: str, alg: AlgorithmConfig,
                rngs: dict[str, random.Random], recovery_eval_budget: int | None = None,
                recovery_wall_s: float | None = None, variant: str = "full",
                max_replans: int = 8) -> EpisodeResult:
    from .replay import verify_replay
    t_start = time.perf_counter()
    res = EpisodeResult(case_id=inst.case_id, strategy=strategy,
                        environment_seed=getattr(world, "_HiddenWorld__seed", -1), status="ERROR")
    res.H = H
    plan = nominal_plan.clone()
    state = initial_run_state(plan, inst, phys)
    ground_required: set[str] = set()
    processed: set[tuple[str, float]] = set()
    replan_index = 0
    segments: list[dict] = []
    seg_start = state
    res.replans.append(ReplanRecord(0, 0.0, [], "NOMINAL", nominal_ev.cost, nominal_ev.z,
                                    {"n_eval_requests": 0}, 0.0, "NOMINAL"))
    while True:
        ev_now = evaluate_plan(plan, inst, phys, state, H, "SIMULATE")
        if not ev_now.feasible:
            res.status = "INVALID_EXECUTION"
            res.notes += ["SIM_INVALID:" + x for x in ev_now.violations[:5]]
            res.plan, res.evaluation = plan, ev_now
            break
        tl = ev_now.timeline
        arrivals = air_arrivals(plan, tl, inst)
        fail = None
        for a in arrivals:
            if a.time < state.t0 - 1e-9:
                continue
            if a.parcel in state.delivered:
                continue
            key = (a.parcel, round(a.time, 3))
            if key in processed:
                continue
            obs = world.observe_air_arrival(a.parcel, a.time,
                                            f"{a.sid}|{a.parcel}|{round(a.time, 3)}",
                                            a.customer, a.drone)
            res.observations.append(obs)
            processed.add(key)
            if not obs.air_delivery_available:
                fail = (a, obs)
                break
        if fail is None:
            t_end = max(list(tl.truck_finish.values()) +
                        [st.end for lst in tl.drone_stages.values() for st in lst] + [state.t0])
            segments.append(collect_segment(plan, tl, inst, phys, state.t0, t_end, seg_start))
            ev = evaluate_plan(plan, inst, phys, state, H, "FINAL")
            rep = verify_replay(inst, phys, segments)
            res.segments = segments
            res.replay = rep
            res.plan = plan
            res.evaluation = ev
            if ev.feasible and rep.ok:
                res.status = "COMPLETED_VERIFIED"
            else:
                res.status = "INVALID_EXECUTION"
                res.notes += ev.violations[:5] + rep.violations[:8]
            break
        a, obs = fail
        ground_required.add(a.parcel)
        t_cut = compute_cut(tl, a.time, a.drone)
        segments.append(collect_segment(plan, tl, inst, phys, state.t0, t_cut, seg_start,
                                        failed_parcel=a.parcel, failed_time=a.time,
                                        failed_drone=a.drone))
        new_plan, state2, info_ = truncate(plan, tl, inst, phys, t_cut, a.time, a.sid,
                                           a.parcel, a.drone, prev_state=state)
        for u in info_.get("unloaded", []):
            if u["parcels"]:
                segments[-1]["actions"].append({
                    "kind": "U", "actor": u["truck"], "drone": u["drone"],
                    "parcels": list(u["parcels"]), "start": t_cut, "end": t_cut,
                    "ref": "", "partial": False, "customer": ""})
        if replan_index >= max_replans:
            res.status = "STOPPED_NO_FEASIBLE_SUFFIX"
            res.notes.append(f"STOP_CONTEXT:replan={replan_index + 1},t_fail={a.time:.1f},t_cut={t_cut:.1f},"
                             f"drone={a.drone},parcel={a.parcel}")
            res.notes.append("MAX_REPLANS")
            res.plan, res.evaluation = new_plan, None
            break
        main_limit = (recovery_eval_budget if recovery_eval_budget is not None
                      else alg.deterministic_recovery_eval_budget)
        # 修复2：初始化预算与 ALNS 主循环预算分开记账，S/X 使用相同的两份额度
        t_budget0 = time.perf_counter()
        init_budget = Budget(alg.recovery_init_eval_budget, recovery_wall_s, start=t_budget0)
        init_stats = SearchStats()
        init_info: dict[str, Any] = {}
        opt, reasons, catalog = initial_recovery(new_plan, state2, inst, phys, strategy,
                                                 ground_required, H=H,
                                                 extra_pool=info_.get("freed", []),
                                                 frag_sid=a.sid, stats=init_stats,
                                                 budget=init_budget, rescue_evals=main_limit,
                                                 info=init_info,
                                                 use_milp=(alg.recovery_decision == "milp"))
        if opt is None:
            res.status = "STOPPED_NO_FEASIBLE_SUFFIX"
            res.notes.append(f"STOP_CONTEXT:replan={replan_index + 1},t_fail={a.time:.1f},t_cut={t_cut:.1f},"
                             f"drone={a.drone},parcel={a.parcel},n_candidate_reasons={len(reasons)}")
            res.notes.append("INITIAL_RECOVERY_FAILED:" + ",".join(reasons[:5]))
            res.plan, res.evaluation = new_plan, None
            break
        rr = derive_rngs(alg.base_algorithm_seed, inst.case_id, "recovery", replan_index + 1)
        ctx = SolveContext(inst=inst, phys=phys, alg=alg, state=state2, H=H, mode="recovery",
                           affected_drones={a.drone}, affected_sorties={a.sid},
                           ground_required=set(ground_required), replan_index=replan_index + 1,
                           rngs=rr, catalog=catalog, frag_sid=a.sid)
        t_r = time.perf_counter()
        budget = Budget(main_limit, recovery_wall_s, start=t_budget0)   # 主循环预算
        stats = SearchStats()
        sol = optimize(opt.plan, ctx, budget, variant=variant, stats=stats, init_ev=opt.ev)
        dt = time.perf_counter() - t_r
        res.replan_times.append(dt)
        # 永不劣于残段候选：理论上 optimize 的最好解从起始解出发、只会更好；这里再做显式兜底
        res_cost = init_info.get("residual_cost")
        if (res_cost is not None and sol.evaluation is not None and sol.evaluation.feasible
                and (sol.evaluation.cost or 0.0) > res_cost + alg.cost_tolerance_yuan):
            res.notes.append("RESIDUAL_GUARD_TRIGGERED")
            rp, rev = init_info["_residual"]
            sol = SolveResult(rp, rev, "FEASIBLE_LIMIT", sol.stats)
        init_counts = {
            "n_init_evals": init_stats.eval_requests,
            "init_by_reason": dict(init_stats.eval_by_reason),
            "n_main_evals": stats.eval_requests,
            "n_main_iterations": stats.iterations,
            "main_by_reason": dict(stats.eval_by_reason),
            "n_eval_requests": init_stats.eval_requests + stats.eval_requests,
            "init_budget_limit": alg.recovery_init_eval_budget,
            "main_budget_limit": main_limit,
            "init_rescue_used": init_info.get("rescue_used", False),
            "init_source": init_info.get("best_source"),
            "init_cost": init_info.get("init_cost"),
            "residual_feasible": init_info.get("residual_feasible"),
            "residual_cost": res_cost,
            "rebuild_cost": init_info.get("rebuild_cost"),
            "n_init_catalog_entries": init_info.get("n_catalog_entries"),
            "stop_reason": stats.stop_reason,
            "recovery_decision": alg.recovery_decision,
            "milp_status": init_info.get("milp_status"),
            "milp_n_options": init_info.get("milp_n_options"),
            "milp_wall_s": init_info.get("milp_wall_s"),
            "milp_surrogate_obj": init_info.get("milp_surrogate_obj"),
            "milp_true_costs": init_info.get("milp_true_costs"),
            "final_cost": sol.evaluation.cost if sol.evaluation is not None else None,
        }
        if init_counts["init_cost"] is not None and init_counts["final_cost"] is not None:
            init_counts["patch_back"] = init_counts["init_cost"] - init_counts["final_cost"]
        sol.stats.counts.update(init_counts)
        if sol.plan is None or sol.evaluation is None or not sol.evaluation.feasible:
            res.status = "STOPPED_NO_FEASIBLE_SUFFIX"
            res.notes.append("RECOVERY_OPT_FAILED")
            res.replans.append(ReplanRecord(replan_index + 1, a.time, [a.parcel], sol.status,
                                            None, None, dict(sol.stats.counts), t_cut))
            res.plan, res.evaluation = new_plan, None
            break
        plan, state = sol.plan, state2
        seg_start = state2
        replan_index += 1
        res.replans.append(ReplanRecord(replan_index, a.time, [a.parcel], sol.status,
                                        sol.evaluation.cost, sol.evaluation.z,
                                        dict(sol.stats.counts), t_cut, opt.description))
        if replan_index > 200:
            res.status = "ERROR"
            res.notes.append("REPLAN_LOOP")
            break
    res.wall_s = time.perf_counter() - t_start
    try:
        res.audit = world.finish_episode()
    except Exception as exc:  # noqa: BLE001
        res.notes.append(f"AUDIT_ERROR:{exc}")
    return res
