"""Observation-only counter around the inherited finite emergency candidate builder."""
from contextlib import contextmanager
from collections import Counter
from tdr import ground_finish

@contextmanager
def finish_candidate_calls():
    original=ground_finish._candidate
    counts=Counter()
    def recorded(plan,state,inst,phys,H,mode,land,audit):
        counts['constructed_attempts']+=1
        before=audit['eval_requests']
        result=original(plan,state,inst,phys,H,mode,land,audit)
        counts['physical_requests']+=audit['eval_requests']-before
        counts['feasible_candidates']+=int(result.cost is not None)
        counts['unplaced_before_evaluation']+=int(result.status.startswith('UNPLACED:'))
        return result
    ground_finish._candidate=recorded
    try:yield counts
    finally:ground_finish._candidate=original
