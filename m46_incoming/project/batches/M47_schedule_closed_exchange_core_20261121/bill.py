def bill(seg,phys,H,start=0):
    # Absolute real truck completion clocks, independently reconstructed from
    # executed truck work/channel use, NOT copied from evaluator future finish.
    # A depot-only mother truck may do P/L without a return DRIVE. Passive drone
    # ON_TRUCK/READY stages do not keep its driver on duty.
    finishes=dict(seg[0].get("start",{}).get("truck_done",{})) if seg else {}
    drive=energy=0.
    for g in seg:
        for a in g["actions"]:
            kind=a["kind"]
            truck=a.get("truck") if kind=="L" else a.get("actor")
            if kind in ("DRIVE","G","P","L","R","U","W") and truck is not None:
                finishes[truck]=max(finishes.get(truck,0.),float(a["end"]))
            if kind!="DRIVE": continue
            duration=a["end"]-a["start"]
            if duration>0: drive+=a["dist"]*max(0,a["end"]-max(a["start"],start))/duration
        for d in g["stages"]:
            remaining=max(0,d["end"]-max(start,d["start"]))
            if not remaining: continue
            if d["kind"]=="CRUISE":
                energy+=phys.fly_energy_kwh(d["dist"]*remaining/(d["end"]-d["start"]),d["mass"])
            elif d["kind"] in ("L","SERVICE") or d["kind"] in ("R","WAIT") and not d["landed"]:
                energy+=phys.hover_energy_kwh(remaining,d["mass"])
    return dict(driver=sum(max(0,f-start) for f in finishes.values())*phys.wage_per_s,
                overtime=sum(max(0,f-max(start,H)) for f in finishes.values())*phys.wage_per_s*(phys.overtime_mult-1),
                distance=drive/1000*phys.c_km,electricity=energy*phys.cost_depot_kwh)

