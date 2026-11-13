from dbg import *
from tdr import plan as P
o=P.Plan.validate_structure
seen=[0]
def v(self,inst,phys,*a,**k):
    errs=o(self,inst,phys,*a,**k)
    for e in errs:
        if '载荷' in e and seen[0]<3:
            seen[0]+=1
            sid=int(e.split()[1].rstrip(':'))
            s=self.sorties[sid]
            print(e,'air',s.air,'hand',s.handover,'started',s.started,'mode',s.mode,'drone',s.drone,'rec',s.rec_vid,'launch_vid',s.launch_vid)
            print('  masses',[(p,inst.parcel_mass[p]) for p in s.payload_ids])
            import traceback; traceback.print_stack(limit=8)
    return errs
P.Plan.validate_structure=v
case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
inst,plan,phys,ep,failed=run(case,seed,forced,strat)
print(ep.status)
