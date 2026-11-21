"""计划结构：车辆访问链、无人机航次、包裹指派与结构校验."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .config import PhysicalConfig, home_truck
from .data import Instance


@dataclass
class Visit:
    """一次客户访问（重复访问使用不同vid）."""

    vid: int
    truck: str
    customer: str
    ground: list[str] = field(default_factory=list)  # 本访问 G 的包裹

    def clone(self) -> "Visit":
        return Visit(self.vid, self.truck, self.customer, list(self.ground))


@dataclass
class Sortie:
    """一个无人机航次（或恢复阶段的空中残段）."""

    sid: int
    drone: str
    truck: str | None          # 放飞车；恢复残段为当前实际承运车
    launch_vid: int | None     # P 所在访问；None 表示仓库出发
    mode: str                  # "ARC" | "STOP" | "AIR"（已在空中）
    lam: float
    air: list[str]             # 按顺序空送的包裹
    rec_vid: int               # 回收访问 vid
    handover: list[str] = field(default_factory=list)  # 回收时交接（异常票）
    started: bool = False      # True: 已在空中，start_time/start_pos 有效
    start_time: float = 0.0
    start_pos: tuple[float, float] | None = None
    rec_priority: int = 0      # 同一访问的回收顺序（局部事件重排）
    launch_priority: int = 0   # 同一访问的放飞顺序
    launch_truck: str | None = None  # 原放飞车（跨车回收统计用，不随承运车改写）
    landed: bool = False       # 降落等待：回收访问处落地等待(零能耗、免 E_min 备用电量)，v6 变体 a

    def clone(self) -> "Sortie":
        return Sortie(self.sid, self.drone, self.truck, self.launch_vid, self.mode, self.lam,
                      list(self.air), self.rec_vid, list(self.handover), self.started,
                      self.start_time, self.start_pos, self.rec_priority, self.launch_priority,
                      self.launch_truck, self.landed)

    @property
    def payload_ids(self) -> list[str]:
        return list(self.air) + list(self.handover)

    @property
    def abnormal(self) -> bool:
        return bool(self.handover)


class Plan:
    """一份完整后缀计划（含所有未完成任务、回收与随车返库）."""

    def __init__(self, case_id: str):
        self.case_id = case_id
        self.routes: dict[str, list[int]] = {}
        self.visits: dict[int, Visit] = {}
        self.sorties: dict[int, Sortie] = {}
        self.drone_sorties: dict[str, list[int]] = {}
        self.next_vid = 1
        self.next_sid = 1

    # ---------- 构造 ----------
    def add_visit(self, truck: str, customer: str, pos: int | None = None,
                  ground: list[str] | None = None) -> Visit:
        vid = self.next_vid
        self.next_vid += 1
        v = Visit(vid, truck, customer, list(ground or []))
        self.visits[vid] = v
        route = self.routes.setdefault(truck, [])
        if pos is None:
            route.append(vid)
        else:
            route.insert(pos, vid)
        return v

    def add_sortie(self, drone: str, truck: str | None, launch_vid: int | None, mode: str,
                   lam: float, air: list[str], rec_vid: int, handover: list[str] | None = None,
                   order: int | None = None) -> Sortie:
        sid = self.next_sid
        self.next_sid += 1
        s = Sortie(sid, drone, truck, launch_vid, mode, lam, list(air), rec_vid, list(handover or []))
        self.sorties[sid] = s
        lst = self.drone_sorties.setdefault(drone, [])
        if order is None:
            # 第三轮修复：新航次必须按"时间/路线次序"插入机体航次链，而不是一律追加到链尾。
            # 此前追加到链尾会让"路线上更早的新航次"排在更晚航次之后，造成机体链与卡车路线次序相反，
            # 定点迭代的时刻表每轮漂移约 1300 s 而不收敛(14 轮后 H 超限)，被误判为不可行。
            lst.insert(self._chain_pos(lst, truck, launch_vid, rec_vid), sid)
        else:
            lst.insert(order, sid)
        return s

    def _route_idx(self, vid: int | None) -> int | None:
        if vid is None:
            return -1
        v = self.visits.get(vid)
        if v is None or v.truck not in self.routes or vid not in self.routes[v.truck]:
            return None
        return self.routes[v.truck].index(vid)

    def _chain_pos(self, chain: list[int], truck: str | None, launch_vid: int | None, rec_vid: int) -> int:
        """同车航次按路线次序排链：插在第一个"放飞位置晚于本航次回收位置"的同车航次之前；否则链尾."""
        ri = self._route_idx(rec_vid)
        if ri is None or truck is None:
            return len(chain)
        for i, sid in enumerate(chain):
            o = self.sorties.get(sid)
            if o is None or o.truck != truck or o.rec_vid not in self.visits:
                continue
            if self.visits[o.rec_vid].truck != truck:
                continue
            li_o = self._route_idx(o.launch_vid)
            if li_o is not None and li_o > ri:
                return i
        return len(chain)

    # ---------- 查询 ----------
    def visit(self, vid: int) -> Visit:
        return self.visits[vid]

    def route_customers(self, truck: str) -> list[str]:
        return [self.visits[v].customer for v in self.routes.get(truck, [])]

    def visit_index(self, vid: int) -> int:
        v = self.visits[vid]
        return self.routes[v.truck].index(vid)

    def launch_sorties(self, vid: int) -> list[Sortie]:
        return [s for s in self.sorties.values() if s.launch_vid == vid]

    def recoveries(self, vid: int) -> list[Sortie]:
        return [s for s in self.sorties.values() if s.rec_vid == vid]

    def parcel_delivery(self) -> dict[str, tuple[str, int]]:
        """parcel -> ("G", vid) 或 ("AIR", sid)"""
        out: dict[str, tuple[str, int]] = {}
        for v in self.visits.values():
            for p in v.ground:
                out[p] = ("G", v.vid)
        for s in self.sorties.values():
            for p in s.air:
                out[p] = ("AIR", s.sid)
        return out

    def assigned_parcels(self) -> set[str]:
        return set(self.parcel_delivery().keys())

    def all_sorties(self) -> list[Sortie]:
        return list(self.sorties.values())

    # ---------- 校验 ----------
    def validate_structure(self, inst: Instance, phys: PhysicalConfig,
                           initial_carrier: dict[str, str] | None = None,
                           holders: dict[str, str] | None = None) -> list[str]:
        """结构校验：目的地、唯一交付、载荷、机体链、货物保管与冻结边界.

        initial_carrier: 计划起点时每架无人机的实际承运车（名义=d_i→t_i；恢复=快照）。
        holders: 计划起点时每票的真实保管者（"DEPOT"/"TRUCK:t1"/"DRONE:d1"/"DELIVERED"）；
                 为 None 时按名义出库处理（未交付票均在仓库，可自由装车）。
        """
        errs: list[str] = []
        # 航次引用
        for s in self.sorties.values():
            if s.rec_vid not in self.visits:
                errs.append(f"sortie {s.sid}: 回收访问 {s.rec_vid} 不存在")
                continue
            if self.visits[s.rec_vid].customer is None:
                errs.append(f"sortie {s.sid}: 回收访问无客户")
            if s.launch_vid is not None:
                if s.launch_vid not in self.visits:
                    errs.append(f"sortie {s.sid}: 放飞访问 {s.launch_vid} 不存在")
                elif s.truck is not None and self.visits[s.launch_vid].truck != s.truck:
                    errs.append(f"sortie {s.sid}: 放飞访问不属于放飞车")
            elif not s.started and s.mode != "ARC":
                errs.append(f"sortie {s.sid}: 仓库放飞必须为 ARC")
            if s.mode == "ARC" and not s.started:
                if not (0.0 <= s.lam <= 1.0):
                    errs.append(f"sortie {s.sid}: lambda 越界 {s.lam}")
            if s.mode == "STOP" and s.launch_vid is not None and not s.started:
                pass
            if s.started and s.start_pos is None:
                errs.append(f"sortie {s.sid}: 空中残段缺少起始坐标")
            if (not s.started and s.launch_vid is not None and s.launch_vid in self.visits
                    and s.rec_vid in self.visits
                    and self.visits[s.launch_vid].truck == self.visits[s.rec_vid].truck):
                route = self.routes.get(self.visits[s.launch_vid].truck, [])
                if (s.launch_vid in route and s.rec_vid in route
                        and route.index(s.launch_vid) >= route.index(s.rec_vid)):
                    errs.append(f"sortie {s.sid}: 同车放飞访问不早于回收访问(时刻成环)")
            if len(s.payload_ids) == 0 and not s.started:
                errs.append(f"sortie {s.sid}: 空载航次")
            m = sum(inst.parcel_mass[p] for p in s.payload_ids if p in inst.parcel_mass)
            if m > phys.drone_payload_limit_kg + 1e-9:
                errs.append(f"sortie {s.sid}: 载荷 {m:.2f}kg 超限")
        # 包裹唯一交付 + 目的地一致性（G 只能在该票收件客户执行）
        seen: dict[str, str] = {}
        for v in self.visits.values():
            for p in v.ground:
                if p in seen:
                    errs.append(f"包裹 {p} 重复交付（{seen[p]} / G@{v.vid}）")
                if p in inst.parcel_to_customer and inst.parcel_to_customer[p] != v.customer:
                    errs.append(f"错址交付: 包裹 {p} 应收件于 {inst.parcel_to_customer[p]}，"
                                f"却在 {v.customer}(visit {v.vid}) 执行 G")
                seen[p] = f"G@{v.vid}"
        for s in self.sorties.values():
            for p in s.air:
                if p in seen:
                    errs.append(f"包裹 {p} 重复交付（{seen[p]} / AIR@{s.sid}）")
                seen[p] = f"AIR@{s.sid}"
            for p in s.handover:
                if p not in seen:
                    errs.append(f"交接包裹 {p} 未安排地面交付")
        # 机体链：首航次承运车 = 起始承运车；后续 = 上一航次回收车
        for d, sids in self.drone_sorties.items():
            carrier = None
            if initial_carrier is not None:
                carrier = initial_carrier.get(d)
            elif not any(self.sorties[x].started for x in sids if x in self.sorties):
                carrier = home_truck(d)
            prev_rec = None
            for sid in sids:
                s = self.sorties.get(sid)
                if s is None:
                    errs.append(f"drone {d}: 航次 {sid} 不存在")
                    continue
                if s.started:
                    # 空中残段的承运关系由残段自身的 rec 访问确定（跨车回收后即新承运车）
                    carrier = self.visits[s.rec_vid].truck if s.rec_vid in self.visits else carrier
                    prev_rec = s.rec_vid if s.rec_vid in self.visits else None
                    continue
                if carrier is not None and s.truck != carrier:
                    errs.append(f"drone {d}: 航次 {sid} 放飞车 {s.truck} 与上一回收/起始承运车 {carrier} 不符")
                # 第四轮 L1：同车相邻航次，后一航次的放飞访问不得早于前一航次的回收访问（路线次序）；
                # 否则调度链成环(定点迭代不收敛，被误判 H_EXCEEDED)
                if (prev_rec is not None and s.launch_vid is not None and s.launch_vid in self.visits
                        and self.visits[prev_rec].truck == self.visits[s.launch_vid].truck):
                    rt_ = self.routes.get(self.visits[prev_rec].truck, [])
                    if prev_rec in rt_ and s.launch_vid in rt_ and rt_.index(s.launch_vid) < rt_.index(prev_rec):
                        errs.append(f"drone {d}: 航次 {sid} 放飞访问早于上一航次回收访问(链次序)")
                carrier = self.visits[s.rec_vid].truck if s.rec_vid in self.visits else None
                prev_rec = s.rec_vid if s.rec_vid in self.visits else None
        # 货物保管由调度器的时点检查（P/G/R/U 顺序）与全程重放核验负责，
        # 这里只保留目的地与交接闭环等静态结构检查。
        return errs

    # ---------- 货物保管（静态结构层） ----------
    def _validate_custody(self, inst: Instance, holders: dict[str, str]) -> list[str]:
        """静态检查：G 只能由持有该票的车执行；P 只能装载该车持有的票；
        无人机交接（handover）只能把机上票转给回收车。"""
        errs: list[str] = []
        holder = {p: holders.get(p, "DEPOT") for p in inst.parcel_mass}
        # 先按票的交付方式确定"谁必须持有"
        for v in self.visits.values():
            for p in v.ground:
                h = holder.get(p)
                if h not in (f"TRUCK:{v.truck}", "DEPOT"):
                    errs.append(f"保管断裂: {p} 由 {h} 持有，却由 {v.truck} 在 {v.customer} 执行 G")
                holder[p] = "DELIVERED"
        for s in self.sorties.values():
            for p in s.air:
                h = holder.get(p)
                if h not in (f"TRUCK:{s.truck}", "DEPOT") and not s.started:
                    errs.append(f"保管断裂: {p} 由 {h} 持有，却在 {s.truck} 的航次 {s.sid} 装载")
                holder[p] = "DELIVERED"
        for s in self.sorties.values():
            for p in s.handover:
                if holder.get(p) == "DELIVERED":
                    errs.append(f"交接票 {p} 已交付却又进入交接清单")
                holder[p] = f"TRUCK:{self.visits[s.rec_vid].truck}" if s.rec_vid in self.visits else "UNKNOWN"
        return errs

    # ---------- 复制 ----------
    def clone(self) -> "Plan":
        p = Plan(self.case_id)
        p.next_vid = self.next_vid
        p.next_sid = self.next_sid
        p.routes = {k: list(v) for k, v in self.routes.items()}
        p.visits = {k: v.clone() for k, v in self.visits.items()}
        p.sorties = {k: s.clone() for k, s in self.sorties.items()}
        p.drone_sorties = {k: list(v) for k, v in self.drone_sorties.items()}
        return p

    # ---------- 删除辅助 ----------
    def remove_visit(self, vid: int) -> None:
        v = self.visits.pop(vid, None)
        if v is None:
            return
        route = self.routes.get(v.truck, [])
        if vid in route:
            route.remove(vid)

    def remove_sortie(self, sid: int) -> None:
        s = self.sorties.pop(sid, None)
        if s is None:
            return
        lst = self.drone_sorties.get(s.drone, [])
        if sid in lst:
            lst.remove(sid)
        if not lst:
            self.drone_sorties.pop(s.drone, None)

    def remove_sortie_tree(self, sid: int) -> None:
        """删除航次及其后续同机航次."""
        s = self.sorties.get(sid)
        if s is None:
            return
        lst = list(self.drone_sorties.get(s.drone, []))
        idx = lst.index(sid)
        for x in lst[idx:]:
            self.remove_sortie(x)


def ground_only_plan(inst: Instance, n_trucks: int = 5, n_total: int | None = None) -> Plan:
    """五车全地送初解：角度扇区 + 最近邻（第7.3节第一步）."""
    import math

    depot = (inst.depot_x, inst.depot_y)
    customers = list(inst.customers)
    customers.sort(key=lambda c: (math.atan2(c.y - depot[1], c.x - depot[0]),
                                  math.hypot(c.x - depot[0], c.y - depot[1]),
                                  c.customer_id))
    n = len(customers)
    k = n_trucks            # 第三轮：车队规模随配置(轻型配置 100 客户 8 车/7 车)；规范配置默认 5
    base = n // k
    extra = n % k
    sizes = [base + (1 if i < extra else 0) for i in range(k)]
    plan = Plan(inst.case_id)
    for t in range(max(k, n_total or 0)):          # 未启用的车保留空路线（终端核验需要其存在）
        plan.routes[f"t{t+1}"] = []
    idx = 0
    for t in range(k):
        seg = customers[idx:idx + sizes[t]]
        idx += sizes[t]
        truck = f"t{t+1}"
        if not seg:
            continue
        remaining = list(seg)
        cur = depot
        order = []
        while remaining:
            nxt = min(remaining, key=lambda c: (math.hypot(c.x - cur[0], c.y - cur[1]), c.customer_id))
            order.append(nxt)
            remaining.remove(nxt)
            cur = (nxt.x, nxt.y)
        for c in order:
            plan.add_visit(truck, c.customer_id, ground=[c.parcel_id])
    return plan
