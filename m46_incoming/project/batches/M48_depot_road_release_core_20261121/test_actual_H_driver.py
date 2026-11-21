import json
from types import SimpleNamespace
import pytest
import execute_recorded as driver
@pytest.mark.parametrize("mode,expected",[("own",111.),("common_F2",222.),("frozen_K1",333.)])
def test_driver_actual_h(tmp_path,monkeypatch,mode,expected):
    for base,H in [(tmp_path/"K1",111.),(tmp_path/"reference/F2",222.),(tmp_path/"reference/frozen",333.)]:
        p=base/"nominal/S/tiny/nominal_plan.json";p.parent.mkdir(parents=True);p.write_text(json.dumps(dict(H_s=H,plan={})))
    witness=tmp_path/"existing/J2/executions/own/dev/tiny_1001_S.json";witness.parent.mkdir(parents=True);witness.write_text(json.dumps(dict(flags=[])))
    monkeypatch.setattr(driver,"J2",tmp_path/"existing")
    monkeypatch.setattr(driver,"TestWorld",lambda *a:None)
    monkeypatch.setattr(driver,"K1_FROZEN",tmp_path/"reference/frozen");monkeypatch.setattr(driver,"ROOT",tmp_path);monkeypatch.setattr(driver,"F2",tmp_path/"reference")
    monkeypatch.setattr(driver,"setup",lambda *a:(SimpleNamespace(parcel_mass={}),None,SimpleNamespace()))
    monkeypatch.setattr(driver,"plan_from_dict",lambda x:None)
    monkeypatch.setattr(driver.rr,"bernoulli_failure_flags",lambda *a:[])
    monkeypatch.setattr(driver.rr,"make_world",lambda *a:None)
    monkeypatch.setattr(driver.rr,"initial_state",lambda *a:None)
    class ReachedPhysical(Exception):pass
    observed=[]
    def evaluate(p,i,phys,state,H,*a,**kw):observed.append(H);raise ReachedPhysical
    monkeypatch.setattr(driver.rr,"evaluate_plan",evaluate)
    with pytest.raises(ReachedPhysical):driver.shift(("K1","tiny","S","dev",1001,mode))
    assert observed==[expected]
