"""Scoped physical call ceiling, including historical unbudgeted S setup.
No effect outside nominal orchestration; scenario-ledger calls keep their own cap.
The envelope is a guard, not a second search allocation or a counted budget.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from .alns import Budget
_ACTIVE = ContextVar("R10_nominal_physical_ceiling", default=None)
class PhysicalEnvelope:
    def __init__(self, limit, reference_H=None):
        self.reference_H=reference_H; self.limit=limit; self.used=0; self.denied=0; self.aux=Budget(limit,None)
    def summary(self):
        return dict(limit=self.limit,used=self.used,auxiliary_used=self.aux.used,denied=self.denied,reference_H=self.reference_H)
def auxiliary_used():
    c=_ACTIVE.get(); return c.aux.used if c is not None else 0
def remaining_limit(requested):
    c=_ACTIVE.get(); return requested if c is None else min(requested,max(0,c.limit-c.used))
@contextmanager
def cap_physical(limit, reference_H=None):
    c=PhysicalEnvelope(limit,reference_H); token=_ACTIVE.set(c)
    try: yield c
    finally: _ACTIVE.reset(token)
