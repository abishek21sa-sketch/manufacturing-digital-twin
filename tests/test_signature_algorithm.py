from types import SimpleNamespace
import numpy as np
import pytest
from mdt.optimization.signature_algorithm import TrustRHError, reference_slot_problem, run_trust_rh_signature, solve_stability_assignment
from mdt.trust import TrustDecision, assess_trust

def trust(decision='authorized'):
    machine=SimpleNamespace(machine_id='M1'); op=SimpleNamespace(operation_id='O1'); job=SimpleNamespace(job_id='J1',operations=(op,)); factory=SimpleNamespace(machines=(machine,),jobs=(job,)); snap=SimpleNamespace(machines={'M1':1},jobs={'J1':1},operations={'O1':1},event_count=1,timestamp=10.)
    ref=10. if decision=='authorized' else 100.
    return assess_trust(snapshot=snap,factory_model=factory,ledger_events=[1],model_evidence={'a':True,'b':True,'c':True,'d':True},reference_time=ref)

def test_signature_authorized_solves_stability_milp():
    jobs=['A','B','C']; costs,prior,cap=reference_slot_problem(jobs); r=run_trust_rh_signature(trust(),jobs,costs,prior,cap,stability_penalty=2)
    assert r.status=='OPTIMAL' and r.optimizer_executed and set(r.job_to_slot)==set(jobs); assert r.churn_count>=0

def test_signature_blocks_optimizer_on_untrusted_twin():
    jobs=['A','B']; costs,prior,cap=reference_slot_problem(jobs); r=run_trust_rh_signature(trust('stale'),jobs,costs,prior,cap)
    assert r.status in {'HUMAN_REVIEW','BLOCKED'} and not r.optimizer_executed and r.job_to_slot=={}

def test_signature_validation_edges():
    with pytest.raises(TrustRHError): solve_stability_assignment([],np.zeros((0,0)),[],[])
    with pytest.raises(TrustRHError): solve_stability_assignment(['A'],np.zeros((2,1)),[0],[1])
    with pytest.raises(TrustRHError): solve_stability_assignment(['A'],np.zeros((1,1)),[2],[1])
    with pytest.raises(TrustRHError): solve_stability_assignment(['A'],np.zeros((1,1)),[0],[0])
    with pytest.raises(TrustRHError): solve_stability_assignment(['A'],np.zeros((1,1)),[0],[1],stability_penalty=-1)
