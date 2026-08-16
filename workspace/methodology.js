const $ = (id) => document.getElementById(id);
async function api(path){ const r=await fetch(path); const p=await r.json(); if(!r.ok) throw new Error(p.detail||JSON.stringify(p)); return p; }
const fmt=(v,d=3)=>Number.isFinite(Number(v))?Number(v).toFixed(d):"—";
const pct=(v,d=1)=>Number.isFinite(Number(v))?`${(100*Number(v)).toFixed(d)}%`:"—";

async function bootstrap(){
  try{
    const data=await api("/v1/methodology/evidence");
    $("methodVersion").textContent=`v${data.version}`;
    const late=data.ai.lateness.production_model, cycle=data.ai.cycle_time.production_model, bottleneck=data.ai.bottleneck.production_model, anomaly=data.ai.anomaly.production_model;
    $("methodEvidenceGrid").innerHTML=`
      <div class="evidence-tile"><span>Benchmark</span><strong>${data.benchmark.instance.toUpperCase()}</strong><small>${data.benchmark.jobs} jobs · ${data.benchmark.machines} machines · ${data.benchmark.operations} operations</small></div>
      <div class="evidence-tile"><span>Lateness ROC-AUC</span><strong>${fmt(late.roc_auc)}</strong><small>Brier ${fmt(late.brier)} · synthetic holdout</small></div>
      <div class="evidence-tile"><span>Cycle-time MAE</span><strong>${fmt(cycle.mae,2)}</strong><small>baseline ${fmt(data.ai.cycle_time.baseline.mae,2)}</small></div>
      <div class="evidence-tile"><span>Bottleneck top-1</span><strong>${pct(bottleneck.top1_accuracy)}</strong><small>baseline ${pct(data.ai.bottleneck.baseline.top1_accuracy)}</small></div>
      <div class="evidence-tile"><span>Anomaly ROC-AUC</span><strong>${fmt(anomaly.roc_auc)}</strong><small>PR-AUC ${fmt(anomaly.pr_auc)}</small></div>`;
    $("lateEvidence").textContent=`ROC-AUC ${fmt(late.roc_auc)} · PR-AUC ${fmt(late.pr_auc)} · Brier ${fmt(late.brier)}`;
    $("cycleEvidence").textContent=`MAE ${fmt(cycle.mae,2)} vs baseline ${fmt(data.ai.cycle_time.baseline.mae,2)}`;
    $("bottleneckEvidence").textContent=`Top-1 ${pct(bottleneck.top1_accuracy)} vs baseline ${pct(data.ai.bottleneck.baseline.top1_accuracy)}`;
    $("anomalyEvidence").textContent=`ROC-AUC ${fmt(anomaly.roc_auc)} · PR-AUC ${fmt(anomaly.pr_auc)}`;
  }catch(e){
    $("methodEvidenceGrid").innerHTML=`<p class="error">Methodology evidence could not be loaded: ${e.message}</p>`;
  }
}
bootstrap();
