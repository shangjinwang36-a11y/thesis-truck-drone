exec(open('gh_nofrag.py').read().split("np_=cap['np']")[0])
tl=cap['tl']; a,k=cap['trargs']; t_cut,t_fail,failed_sid,parcel,drone=a[2:7]
t1=t_fail
for x in tl.actions:
    if simulate._ghost_action(x,drone,t_fail): continue
    if x.kind in ('G','P','R','U','W') and x.start<t_fail<x.end: t1=max(t1,x.end)
print('first-level cut delay',t1-t_fail,'final delay',t_cut-t_fail)
# list actions straddling the final cut chain
import collections
ch=[(x.actor,x.kind,round(x.start,1),round(x.end,1)) for x in tl.actions if x.kind in ('G','P','R','U','W') and not simulate._ghost_action(x,drone,t_fail) and x.end>t_fail and x.start<t_cut and x.end-x.start>0]
print(len(ch)); print(sorted(ch,key=lambda z:z[2])[:40])
