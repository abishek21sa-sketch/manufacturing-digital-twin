"""TRUST-RH signature algorithm: trust authorization + stability-aware slot MILP."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Sequence
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from mdt.trust import TrustAssessment, TrustDecision

@dataclass(frozen=True)
class TrustRHScheduleResult:
    algorithm: str
    status: str
    optimizer_executed: bool
    objective_value: float | None
    job_to_slot: dict[str,int]
    churn_count: int
    prior_slots: dict[str,int]
    stability_penalty: float
    claim_boundary: str
    def to_dict(self): return asdict(self)

class TrustRHError(ValueError): pass

def solve_stability_assignment(job_ids:Sequence[str], base_costs:np.ndarray, prior_slots:Sequence[int], slot_capacity:Sequence[int], *, stability_penalty:float=1.0)->TrustRHScheduleResult:
    jobs=list(job_ids); costs=np.asarray(base_costs,dtype=float); prior=np.asarray(prior_slots,dtype=int); cap=np.asarray(slot_capacity,dtype=int)
    n=len(jobs)
    if n==0: raise TrustRHError('at least one job is required')
    if costs.ndim!=2 or costs.shape[0]!=n: raise TrustRHError('base_costs shape must be [job,slot]')
    T=costs.shape[1]
    if prior.shape!=(n,) or np.any(prior<0) or np.any(prior>=T): raise TrustRHError('prior_slots must contain one valid slot per job')
    if cap.shape!=(T,) or np.any(cap<0) or int(cap.sum())<n: raise TrustRHError('slot capacity is invalid or insufficient')
    if stability_penalty<0: raise TrustRHError('stability_penalty must be non-negative')
    c=np.zeros(n*T)
    for j in range(n):
        for t in range(T): c[j*T+t]=costs[j,t]+stability_penalty*(0 if t==prior[j] else 1)
    integ=np.ones(n*T,dtype=int); lb=np.zeros(n*T); ub=np.ones(n*T)
    rows=[]; lo=[]; hi=[]
    for j in range(n):
        row=np.zeros(n*T); row[j*T:(j+1)*T]=1; rows.append(row); lo.append(1); hi.append(1)
    for t in range(T):
        row=np.zeros(n*T)
        for j in range(n): row[j*T+t]=1
        rows.append(row); lo.append(-np.inf); hi.append(float(cap[t]))
    res=milp(c,integrality=integ,bounds=Bounds(lb,ub),constraints=LinearConstraint(np.asarray(rows),np.asarray(lo),np.asarray(hi)),options={'disp':False})
    if not res.success or res.x is None:
        return TrustRHScheduleResult('TRUST-RH','INFEASIBLE',True,None,{},0,{j:int(p) for j,p in zip(jobs,prior)},float(stability_penalty),'No schedule claim: stability assignment was infeasible.')
    x=res.x.reshape(n,T); assignment={jobs[j]:int(np.argmax(x[j])) for j in range(n)}
    churn=sum(int(assignment[j]!=int(prior[i])) for i,j in enumerate(jobs))
    return TrustRHScheduleResult('TRUST-RH','OPTIMAL',True,float(res.fun),assignment,int(churn),{j:int(p) for j,p in zip(jobs,prior)},float(stability_penalty),'Synthetic scheduling evidence only; the slot abstraction does not prove realized plant performance.')

def run_trust_rh_signature(trust:TrustAssessment, job_ids:Sequence[str], base_costs:np.ndarray, prior_slots:Sequence[int], slot_capacity:Sequence[int], *, stability_penalty:float=1.0)->TrustRHScheduleResult:
    if trust.decision != TrustDecision.AUTHORIZED:
        return TrustRHScheduleResult('TRUST-RH',trust.decision.value,False,None,{},0,{str(j):int(p) for j,p in zip(job_ids,prior_slots)},float(stability_penalty),'Optimizer was not executed because twin trust evidence did not authorize scheduling.')
    return solve_stability_assignment(job_ids,base_costs,prior_slots,slot_capacity,stability_penalty=stability_penalty)

def reference_slot_problem(job_ids:Sequence[str])->tuple[np.ndarray,list[int],list[int]]:
    jobs=list(job_ids); n=len(jobs); T=max(n,1)
    prior=list(range(n)); cap=[1]*T
    # Due/order proxy: later slots cost progressively more, while some jobs have a mild incentive to move earlier.
    costs=np.zeros((n,T),dtype=float)
    for j in range(n):
        preferred=max(0,j-1 if j%2 else j)
        for t in range(T): costs[j,t]=abs(t-preferred)+0.05*t
    return costs,prior,cap
