from __future__ import annotations
import csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"src"
if str(SRC) not in sys.path:
    sys.path.insert(0,str(SRC))
import numpy as np
from mdt.trust import TrustAssessment,TrustDecision,TrustSignals
from mdt.trust_validation import canonical_experiments,sensitivity_grid,validation_report
from mdt.optimization.signature_algorithm import reference_slot_problem,run_trust_rh_signature,solve_stability_assignment
OUT=ROOT/'artifacts'/'trust_rh'; OUT.mkdir(parents=True,exist_ok=True)
canonical=canonical_experiments(); sensitivity=sensitivity_grid(); report=validation_report()
auth=TrustAssessment(TrustDecision.AUTHORIZED,1.0,.82,.62,TrustSignals(1,1,1,1,0,24,()))
blocked=TrustAssessment(TrustDecision.BLOCKED,.5,.82,.62,TrustSignals(1,0,1,1,0,24,('EVENT_LEDGER_MISMATCH',)))
jobs=['J1','J2','J3','J4']; costs,prior,cap=reference_slot_problem(jobs)
stability=run_trust_rh_signature(auth,jobs,costs,prior,cap,stability_penalty=2.0)
ungated=solve_stability_assignment(jobs,costs,prior,cap,stability_penalty=0.0)
gated=run_trust_rh_signature(blocked,jobs,costs,prior,cap,stability_penalty=2.0)
penalty_rows=[]
for gamma in (0,.5,1,2,5):
 r=solve_stability_assignment(jobs,costs,prior,cap,stability_penalty=gamma); penalty_rows.append({'stability_penalty':gamma,'objective':r.objective_value,'churn_count':r.churn_count,'status':r.status})
checks={
 'trust_canonical_all_pass':report['canonical_passed']==report['canonical_total']==7,
 'trust_sensitivity_complete':report['sensitivity_cases']==96,
 'authorized_executes_signature':stability.optimizer_executed and stability.status=='OPTIMAL',
 'blocked_does_not_execute':not gated.optimizer_executed and gated.status=='BLOCKED',
 'stability_penalty_not_more_churn_than_ungated':stability.churn_count<=ungated.churn_count,
 'stability_sensitivity_complete':len(penalty_rows)==5 and all(r['status']=='OPTIMAL' for r in penalty_rows),
}
payload={'algorithm':'TRUST-RH','null_hypothesis':'Trust-gating does not reduce invalid schedule release under degraded twin evidence, or stability-aware recovery does not reduce schedule churn relative to an ungated/zero-stability optimizer.','evidence_class':'synthetic engineering authorization and scheduling evidence','seed':None,'authorization_experiments':canonical,'trust_sensitivity_cases':len(sensitivity),'stability_reference':stability.to_dict(),'ungated_zero_stability_baseline':ungated.to_dict(),'blocked_reference':gated.to_dict(),'checks':checks,'claim_boundary':'TRUST-RH trust scores and schedule results are engineering evidence, not calibrated probabilities of physical-state truth or realized production outcomes.'}
(OUT/'authorization_experiments.json').write_text(json.dumps(canonical,indent=2),encoding='utf-8'); (OUT/'sensitivity.json').write_text(json.dumps(sensitivity,indent=2),encoding='utf-8'); (OUT/'signature_evidence.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
with (OUT/'sensitivity.csv').open('w',newline='',encoding='utf-8') as f: w=csv.DictWriter(f,fieldnames=list(sensitivity[0])); w.writeheader(); w.writerows(sensitivity)
with (OUT/'stability_sensitivity.csv').open('w',newline='',encoding='utf-8') as f: w=csv.DictWriter(f,fieldnames=penalty_rows[0].keys()); w.writeheader(); w.writerows(penalty_rows)
passed=sum(checks.values()); (OUT/'VALIDATION_REPORT.md').write_text(f'# TRUST-RH Validation Report\n\nChecks: **{passed}/{len(checks)} passed**.\n\nCanonical trust experiments: **{report["canonical_passed"]}/{report["canonical_total"]}**. Trust sensitivity cases: **{report["sensitivity_cases"]}**.\n\nStability-aware churn: **{stability.churn_count}** vs zero-stability baseline **{ungated.churn_count}**.\n\n{payload["claim_boundary"]}\n',encoding='utf-8')
print(f'TRUST_RH_EVIDENCE={passed}/{len(checks)}'); print(f'TRUST_RH_CANONICAL={report["canonical_passed"]}/{report["canonical_total"]}'); print(f'TRUST_RH_SENSITIVITY={report["sensitivity_cases"]}'); print(f'TRUST_RH_STABILITY_SENSITIVITY={len(penalty_rows)}')
if not all(checks.values()): raise SystemExit(1)
