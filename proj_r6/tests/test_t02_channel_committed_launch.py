"""T02-B：截断时正在进行、跨过截断点的放飞仍占着放飞车的通道。

复现 RC100 种子 2001 S 的结构：d8 的放飞 970.2–980.2 跨过 t_cut=972.9，残段 start_time=980.2；
后缀里同车 d7 的回收 978.4–1008.4 与它重叠。旧 channel_check 看不到前者（评价可行、回放报 CHANNEL_OVERLAP）。
函数不接收策略参数，S/R/X 同一路径。
"""
from tdr.config import PhysicalConfig
from tdr.evaluate import channel_check
from tdr.plan import Plan, Sortie
from tdr.schedule import StartState, Timeline


def _case():
    phys = PhysicalConfig()
    plan = Plan("T")
    v = plan.add_visit("t1", "c1")
    plan.sorties[1] = Sortie(1, "d8", "t1", None, "AIR", 0.0, ["p1"], v.vid, started=True,
                             start_time=980.19, start_pos=(0.0, 0.0), launch_truck="t1")
    plan.sorties[2] = Sortie(2, "d7", "t1", None, "AIR", 0.0, ["p2"], v.vid, started=True,
                             start_time=900.0, start_pos=(1.0, 1.0), launch_truck="t1")
    plan.drone_sorties = {"d8": [1], "d7": [2]}
    tl = Timeline(t0=972.9, rec_times={1: (1100.0, 1130.0), 2: (978.38, 1008.38)})
    return plan, phys, tl, StartState(t0=972.9)


def test_committed_launch_blocks_overlapping_recovery():
    plan, phys, tl, st = _case()
    assert channel_check(plan, phys, tl) == []            # 旧口径：看不到
    errs = channel_check(plan, phys, tl, st)
    assert errs and errs[0].startswith("CHANNEL_OVERLAP:t1")


def test_finished_launch_does_not_block():
    plan, phys, tl, st = _case()
    plan.sorties[1].start_time = 970.0                    # 放飞在截断前已完成
    assert channel_check(plan, phys, tl, st) == []
