"""Read-only accounting of every full-evaluation request; does not alter old budgets."""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE = ContextVar("round10_evaluation_audit", default=None)

class EvaluationAudit:
    def __init__(self):
        self.accepted = Counter()
        self.denied = Counter()
        self.unbudgeted = Counter()
        self.budgets = {}

    def record(self, reason, budget, accepted):
        (self.accepted if accepted else self.denied)[reason] += 1
        if budget is None:
            self.unbudgeted[reason] += 1
        else:
            entry = self.budgets.setdefault(id(budget), {"object": budget, "calls": 0,
                                                         "reasons": Counter()})
            if accepted:
                entry["calls"] += 1
                entry["reasons"][reason] += 1

    def summary(self):
        budgets = []
        for e in self.budgets.values():
            b = e["object"]
            budgets.append({"accepted_calls": e["calls"], "used": b.used,
                            "final_limit": b.eval_limit, "wall_limit": b.wall_limit,
                            "scenario_ledger": bool(getattr(b, "scenario_ledger", False)),
                            "reasons": dict(e["reasons"])})
        return {"accepted_calls": sum(self.accepted.values()),
                "denied_calls": sum(self.denied.values()),
                "by_reason": dict(self.accepted), "denied_by_reason": dict(self.denied),
                "unbudgeted_by_reason": dict(self.unbudgeted), "budgets": budgets}

@contextmanager
def audit_evaluations():
    audit = EvaluationAudit()
    token = _ACTIVE.set(audit)
    try:
        yield audit
    finally:
        _ACTIVE.reset(token)
