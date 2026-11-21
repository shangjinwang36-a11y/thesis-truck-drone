"""Exact, invocation-local memoization of pure geometry, never evaluation.
All bytes are unrounded. Scope includes complete visible context; per-frame plan
binding isolates altered geometry. No cross-Work, native-call or budget cache.
"""
import pickle,hashlib
class ExactGeometryScope:
 def __init__(self,p,inst,phys,state,H,launch_order,timeline,allow_cross,p_fail,diag):
  from .complete_joint import version
  from .moves import air_energy,air_time
  payload=pickle.dumps((version(p),inst,phys,vars(state),H,launch_order,timeline,allow_cross,p_fail),protocol=5)
  self.context=hashlib.sha256(payload).hexdigest();self.inst=inst;self.phys=phys;self.original_energy=air_energy;self.original_time=air_time;self.diag=diag;self.diag.update(context=self.context,full_context_bytes=len(payload),energy_hits=0,energy_misses=0,time_hits=0,time_misses=0,window_hits=0,window_misses=0,packing_hits=0,packing_misses=0,frames=0,native_evaluation_cache=False);self.plan=None
 def bind_plan(self,p):
  from .complete_joint import version
  self.plan=version(p);self.energy_values={};self.time_values={};self.window_values={};self.packing_values={};self.diag['frames']+=1
 def key(self,*args):return pickle.dumps((self.context,self.plan,args),protocol=5)
 def energy(self,inst,phys,start,cargo,rec):
  assert inst is self.inst and phys is self.phys and self.plan is not None
  key=self.key(tuple(start),tuple(cargo),tuple(rec))
  if key in self.energy_values:self.diag['energy_hits']+=1;return self.energy_values[key]
  result=self.original_energy(inst,phys,start,cargo,rec);self.energy_values[key]=result;self.diag['energy_misses']+=1;return result
 def time(self,inst,phys,start,cargo,rec):
  assert inst is self.inst and phys is self.phys and self.plan is not None
  key=self.key(tuple(start),tuple(cargo),tuple(rec))
  if key in self.time_values:self.diag['time_hits']+=1;return self.time_values[key]
  result=self.original_time(inst,phys,start,cargo,rec);self.time_values[key]=result;self.diag['time_misses']+=1;return result
 def window(self,sid,truck,cargo,compute):
  key=self.key(sid,truck,tuple(cargo))
  if key in self.window_values:self.diag['window_hits']+=1;return self.window_values[key]
  result=compute();self.window_values[key]=result;self.diag['window_misses']+=1;return result

 def packing(self,ids,pool,windows,compute):
  # Trucks affect later body assignment, not this pure parcel-packing function.
  # Full frame/context + exact ordered IDs/pool/windows determine every read.
  key=self.key('PURE_REGRET_PACKING',tuple(ids),tuple(pool),tuple(windows))
  if key in self.packing_values:self.diag['packing_hits']+=1;frozen=self.packing_values[key]
  else:
   groups,left=compute();frozen=(tuple((sid,tuple(groups[sid]))for sid in ids),frozenset(left));self.packing_values[key]=frozen;self.diag['packing_misses']+=1
  return {sid:list(cargo)for sid,cargo in frozen[0]},set(frozen[1])
