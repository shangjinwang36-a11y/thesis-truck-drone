from types import SimpleNamespace as NS
import pytest
from tdr import complete_joint as cj,nominal_accounting as na
from tdr.terminal_joint import close

@pytest.mark.parametrize('strategy,cross',[('S',False),('R',False),('X',True)])
def test_no_free_new_budget_without_global_envelope(monkeypatch,strategy,cross):
 monkeypatch.setattr(cj,'version',lambda p:p.name)
 ctx=NS(alg=NS(),strategy=strategy,state=NS(nominal_cross=cross));p=NS(name='parent');e=object()
 tok=na._ACTIVE.set(None)
 try:assert close(p,e,ctx)==(p,e,0)
 finally:na._ACTIVE.reset(tok)
 assert ctx.alg._terminal_joint_records[0]['skip']=='NO_GLOBAL_ENVELOPE'

@pytest.mark.parametrize('strategy,cross',[('S',False),('R',False),('X',True)])
def test_shared_rule_never_reserves_or_exceeds_exhausted_envelope(monkeypatch,strategy,cross):
 monkeypatch.setattr(cj,'version',lambda p:p.name)
 ctx=NS(alg=NS(),strategy=strategy,state=NS(nominal_cross=cross));p=NS(name='parent');e=object()
 with na.cap_physical(10)as envelope:
  envelope.used=10
  assert close(p,e,ctx)==(p,e,0)
  assert envelope.used==10
 assert ctx.alg._terminal_joint_records[0]['skip']=='NO_UNSPENT_PHYSICAL_BUDGET'

def test_terminal_stage_moves_shared_family_not_S_only():
 for strategy in ['S','R','X']:
  ctx=NS(mode='nominal',scenario_on=True,alg=NS(complete_joint=True,complete_joint_stage='terminal'),strategy=strategy)
  assert not cj.enabled(ctx)
  ctx.alg.complete_joint_stage='interleaved'
  assert cj.enabled(ctx)

def test_no_graph_literals_old_plan_load_or_RNG_draw():
 import inspect,tdr.terminal_joint as md
 s=inspect.getsource(md)
 for bad in ['RC100','C50','read(','load_case','random.','p001','p079']:
  assert bad not in s


def test_terminal_context_import_has_own_unconditional_local_alias():
 import ast,inspect,textwrap
 from tdr.experiment import build_case_nominal
 tree=ast.parse(textwrap.dedent(inspect.getsource(build_case_nominal)))
 branch=next(n for n in ast.walk(tree)if isinstance(n,ast.If)and any(isinstance(x,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='terminal_ctx'for t in x.targets)for x in n.body))
 idx=next(i for i,n in enumerate(branch.body)if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='terminal_ctx'for t in n.targets))
 assert any(isinstance(n,ast.ImportFrom)and any(a.asname=='TerminalSolveContext'for a in n.names)for n in branch.body[:idx])
 assert branch.body[idx].value.func.id=='TerminalSolveContext'
