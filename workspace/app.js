const $ = (id) => document.getElementById(id);
const state = { factory: null, twin: null, risk: null, operational: null, ie: null, ledger: null, recovery: null, simulation: null, stress: null, history: null, synthetic: null, fileText: "", currentRunId: null };
const SCENARIO_PRESETS = {
  baseline: { label:"Baseline benchmark", dueFactor:1.20, processingCv:0.08, mtbf:180, mttr:6, stressMachine:"M5", stressMtbf:60, stressMttr:8, replications:24, riskAversion:0.25, stabilityPenalty:0.15 },
  reliability: { label:"Reliability shock", dueFactor:1.35, processingCv:0.14, mtbf:100, mttr:8, stressMachine:"M5", stressMtbf:32, stressMttr:14, replications:24, riskAversion:0.45, stabilityPenalty:0.25 },
  demand: { label:"Due-date pressure", dueFactor:1.70, processingCv:0.12, mtbf:120, mttr:8, stressMachine:"M5", stressMtbf:40, stressMttr:12, replications:24, riskAversion:0.55, stabilityPenalty:0.30 },
  variability: { label:"Process variability", dueFactor:1.35, processingCv:0.28, mtbf:120, mttr:8, stressMachine:"M5", stressMtbf:40, stressMttr:10, replications:36, riskAversion:0.50, stabilityPenalty:0.35 },
};

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  let payload;
  try { payload = await response.json(); } catch { payload = { detail: await response.text() }; }
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload));
  return payload;
}
const num = (id) => Number($(id).value);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[char]));
const scenario = () => {
  const machine = $("stressMachine").value || null;
  return {
    backend: $("backend").value,
    due_factor: num("dueFactor"), replications: Math.round(num("replications")), base_seed: 20260815,
    processing_cv: num("processingCv"), mtbf: num("mtbf"), mttr: num("mttr"), risk_aversion: num("riskAversion"),
    stability_penalty: num("stabilityPenalty"),
    stressed_machine_id: machine,
    stressed_machine_mtbf: machine ? num("stressMtbf") : null,
    stressed_machine_mttr: machine ? num("stressMttr") : null,
  };
};
function fmt(v, d=2){ return Number.isFinite(Number(v)) ? Number(v).toFixed(d) : "—"; }
function pct(v, d=1){ return Number.isFinite(Number(v)) ? `${(100*Number(v)).toFixed(d)}%` : "—"; }
function busy(button, value=true){ button.disabled=value; button.classList.toggle("busy", value); }
function shortId(value){ return value ? String(value).slice(0,8) : "—"; }
function workflowStatus(message, stateName="ready"){
  const status=$("workflowStatus");
  if(!status) return;
  status.textContent=message;
  status.dataset.state=stateName;
}
function workflowStep(id, stateName){
  const button=$(id);
  if(!button) return;
  button.classList.toggle("workflow-running", stateName==="running");
  button.classList.toggle("workflow-complete", stateName==="complete");
}
function revealWorkflowTarget(id){
  requestAnimationFrame(()=>$(id)?.scrollIntoView({behavior:"smooth",block:"start"}));
}
async function applyScenarioPreset(name){
  const preset=SCENARIO_PRESETS[name];
  if(!preset) return;
  const values={dueFactor:preset.dueFactor,processingCv:preset.processingCv,mtbf:preset.mtbf,mttr:preset.mttr,stressMtbf:preset.stressMtbf,stressMttr:preset.stressMttr,replications:preset.replications,riskAversion:preset.riskAversion,stabilityPenalty:preset.stabilityPenalty};
  Object.entries(values).forEach(([id,value])=>{ if($(id)) $(id).value=String(value); });
  if($("stressMachine")) $("stressMachine").value=preset.stressMachine;
  document.querySelectorAll("[data-preset]").forEach(button=>button.classList.toggle("active",button.dataset.preset===name));
  $("scenarioPresetStatus").textContent=preset.label;
  ["nominalBtn","trajectoryBtn","stressBtn"].forEach(id=>workflowStep(id,"ready"));
  workflowStatus(`PRESET LOADED · ${preset.label} · choose a run step`,"ready");
  try{
    await Promise.all([
      refreshContext(),
      api(`/v1/ai/lateness-risk?due_factor=${num("dueFactor")}`).then(renderRisk),
    ]);
  }catch(e){ workflowStatus(`PRESET PARTIAL · ${e.message}`,"error"); }
}

function renderTwinContext(twin, operational, ie){
  state.twin=twin; state.operational=operational; state.ie=ie;
  const eventCount=Number(twin.event_count||0);
  $("twinStateId").textContent=eventCount
    ? `State ${twin.state_id||"—"} · ${eventCount} replayed event${eventCount===1?"":"s"}`
    : `Baseline state ${twin.state_id||"—"} · no ingested events`;
  $("twinClock").textContent=fmt(twin.timestamp,1);
  $("twinEvents").textContent=String(twin.event_count ?? 0);
  $("twinWip").textContent=String(twin.wip_jobs ?? 0);
  $("constraintMachine").textContent=ie.constraint?.machine_id || "—";
  $("constraintLoad").textContent=`workload ${fmt(ie.constraint?.workload,1)}`;
  $("conwipState").textContent=`CONWIP ${ie.conwip?.release_allowed ? "release open" : "held"} · cap ${ie.conwip?.wip_limit ?? "—"}`;
  const probabilities=operational.future_bottleneck_probability||{};
  const predicted=Object.entries(probabilities).sort((a,b)=>Number(b[1])-Number(a[1]))[0];
  $("predictedBottleneck").textContent=predicted?.[0] || "—";
  $("aiBottleneck").textContent=predicted?.[0] || "—";
  $("aiBottleneckProbability").textContent=predicted ? `${pct(predicted[1])} modeled probability` : "—";
  const anomalies=Object.entries(operational.machine_anomaly||{}).filter(([,row])=>Boolean(row.is_anomaly)).map(([id])=>id);
  $("aiAnomalies").textContent=anomalies.length ? anomalies.join(", ") : "NONE";
  $("anomalyState").textContent=anomalies.length ? `${anomalies.length} anomaly flag${anomalies.length>1?"s":""}` : "no anomaly flags";
  $("reviewState").textContent=anomalies.length ? "REVIEW REQUIRED" : "PENDING";
  renderMachineBoard(twin, operational);
  renderConstraints(ie);
}

function renderMachineBoard(twin, operational){
  const anomalyMap=operational?.machine_anomaly||{};
  const queued=new Set(twin.queued_operations||[]);
  const operationMap=twin.operations||{};
  const cards=Object.entries(twin.machines||{}).map(([id,machine])=>{
    const anomaly=Boolean(anomalyMap[id]?.is_anomaly);
    const active=machine.active_operation_id||"—";
    const queue=[...queued].filter(op=>operationMap[op]?.machine_id===id).length;
    return `<div class="machine-tile ${esc(machine.status)} ${anomaly?"anomaly":""}"><div class="machine-tile-top"><strong>${esc(id)}</strong><span class="machine-status">${esc(String(machine.status).toUpperCase())}</span></div><div class="machine-active">${active==="—"?"No active operation":`Running <b>${esc(active)}</b>`}</div><div class="machine-tile-meta"><span>${queue} queued</span><span>${anomaly?"anomaly flag":"ledger-sourced"}</span></div></div>`;
  });
  $("machineBoard").innerHTML=cards.length?cards.join(""):`<p class="muted">No machine state available.</p>`;
}

function renderConstraints(ie){
  const rows=ie?.capacity||[];
  $("constraintTable").innerHTML=rows.length?`<table class="evidence-table"><thead><tr><th>Machine</th><th>Load</th><th>Capacity</th><th>Utilization</th><th>Slack</th><th>Signal</th></tr></thead><tbody>${rows.map(row=>{const ratio=Number(row.load_ratio||0);const binding=ratio>=.85;return `<tr class="${binding?"binding":""}"><td><b>${esc(row.machine_id)}</b></td><td>${fmt(row.workload,1)}</td><td>${fmt(row.effective_available_time,1)}</td><td>${pct(ratio)}</td><td>${fmt(row.capacity_gap,1)}</td><td><span class="status-dot ${binding?"hot":"ok"}">${binding?"PRESSURE":"SLACK"}</span></td></tr>`;}).join("")}</tbody></table>`:`<p class="muted">No capacity plan available.</p>`;
}

function renderRisk(payload){
  state.risk = payload;
  const jobs=payload.jobs||[];
  $("riskList").innerHTML = jobs.length ? jobs.map(job => {
    const score = Math.max(0, Math.min(1, Number(job.risk_score || 0)));
    return `<div class="risk-row"><strong>${job.job_id}</strong><div class="risk-bar"><div class="risk-fill" style="width:${score*100}%"></div></div><span class="risk-score">${(score*100).toFixed(1)}%</span></div>`;
  }).join("") : `<p class="muted">No residual jobs require a lateness forecast.</p>`;
}

function renderTimeline(operations, downtimes=[]){
  if (!state.factory || !operations?.length) return;
  const machines = state.factory.machine_ids;
  const W=1320, left=78, right=24, top=34, lane=66, H=top+machines.length*lane+38;
  const currentTime=Number(state.twin?.timestamp||0);
  const maxT = Math.max(1, currentTime, ...operations.map(o=>Number(o.finish)), ...downtimes.map(d=>Number(d.finish)));
  const x = t => left + (Number(t)/maxT)*(W-left-right);
  const svg=$("timeline"); svg.setAttribute("viewBox",`0 0 ${W} ${H}`); svg.setAttribute("height", H);
  let out="";
  const ticks=10;
  for(let i=0;i<=ticks;i++){ const t=maxT*i/ticks, xx=x(t); out += `<line class="timeline-grid" x1="${xx}" y1="${top-12}" x2="${xx}" y2="${H-20}"/><text class="time-label" x="${xx+2}" y="16">${fmt(t,0)}</text>`; }
  machines.forEach((m,idx)=>{ const y=top+idx*lane; out += `<text class="machine-label" x="7" y="${y+29}">${m}</text><line class="timeline-grid" x1="${left}" y1="${y+lane-8}" x2="${W-right}" y2="${y+lane-8}"/>`; });
  if(currentTime>0){ const xx=x(currentTime); out += `<line class="current-marker" x1="${xx}" y1="${top-15}" x2="${xx}" y2="${H-18}"/><text class="time-label" x="${xx+4}" y="${H-5}">twin now ${fmt(currentTime,1)}</text>`; }
  const riskMap=Object.fromEntries((state.risk?.jobs||[]).map(j=>[j.job_id,Number(j.risk_score||0)]));
  operations.forEach(op=>{ const idx=machines.indexOf(op.machine_id); if(idx<0)return; const y=top+idx*lane+11, xx=x(op.start), width=Math.max(4,x(op.finish)-xx); const r=riskMap[op.job_id]||0; const hue=196-170*r; const fill=`hsl(${hue} 49% ${38+6*r}%)`; out += `<g><rect x="${xx}" y="${y}" width="${width}" height="31" rx="3" fill="${fill}"><title>${op.operation_id} · ${op.machine_id} · ${fmt(op.start)}→${fmt(op.finish)} · risk ${fmt(r*100,1)}%</title></rect>${width>42?`<text class="op-label" x="${xx+5}" y="${y+20}">${op.operation_id}</text>`:""}</g>`; });
  downtimes.forEach(d=>{ const idx=machines.indexOf(d.machine_id); if(idx<0)return; const y=top+idx*lane+5, xx=x(d.start), width=Math.max(2,x(d.finish)-xx); out += `<rect x="${xx}" y="${y}" width="${width}" height="43" fill="#a64232" opacity=".34"><title>${d.machine_id} downtime ${fmt(d.start)}→${fmt(d.finish)}</title></rect>`; });
  svg.innerHTML=out;
  $("timelineNote").textContent=`Horizon ${fmt(maxT,1)} · ${operations.length} operations${downtimes.length?` · ${downtimes.length} downtime intervals`:""}`;
}

function renderDecisionPacket(payload){
  const decision=payload.decision||{};
  state.currentRunId=payload.run_id||null;
  $("decisionPacket").classList.remove("hidden");
  $("decisionAction").textContent=decision.action||"—";
  $("decisionRationale").textContent=decision.rationale||"—";
  const impact=decision.expected_modeled_impact||{};
  const base=impact.baseline_spt_total_tardiness, nominal=impact.nominal_optimized_total_tardiness;
  $("decisionImpact").textContent=Number.isFinite(Number(base))&&Number.isFinite(Number(nominal)) ? `nominal tardiness ${fmt(base,1)} → ${fmt(nominal,1)}` : (impact.label||"modeled impact recorded");
  const uncertainty=decision.uncertainty||{};
  $("decisionUncertainty").textContent=uncertainty.stressed_machine ? `stress ${uncertainty.stressed_machine} · ${uncertainty.monte_carlo_replications||"—"} MC reps` : `process CV ${fmt(uncertainty.processing_cv_scenario_assumption,2)}`;
  const solver=payload.nominal_optimized?.solver||{};
  const quality=payload.nominal_optimized?.solution_quality||{};
  $("decisionSolver").textContent=`${solver.backend||"—"} · ${quality.termination_status||solver.status||"—"} · ${quality.feasible?"feasible":"unverified"}`;
  $("decisionEvidence").textContent=decision.evidence_level||"—";
  const assumptions=decision.assumptions||[], tradeoffs=decision.trade_offs||[];
  const stability=payload.stability?.nominal;
  $("decisionDetails").innerHTML=`<strong>Assumptions</strong><ul>${assumptions.map(x=>`<li>${esc(x)}</li>`).join("")}</ul><strong>Trade-offs</strong><ul>${tradeoffs.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>${stability?`<strong>Schedule change evidence</strong><p>${stability.changed_operations} changed operations · ${fmt(stability.total_start_time_displacement,1)} time units displaced · γ ${fmt(payload.stability?.penalty_weight,2)}</p>`:""}`;
  const disposition=(decision.human_disposition||"pending").toUpperCase();
  $("decisionDisposition").textContent=disposition;
  $("reviewState").textContent=disposition;
  $("decisionRunId").textContent=`Run ${shortId(state.currentRunId)} · full ID ${state.currentRunId||"—"}`;
  renderStability(payload);
}

function renderStability(payload){
  const metrics=payload?.stability?.nominal;
  if(!metrics){ $("stabilityMetrics").innerHTML=`<p class="muted">Run recovery to calculate schedule change evidence.</p>`; $("scheduleChangeList").innerHTML=""; return; }
  $("stabilityEvidenceLabel").textContent=`γ ${fmt(payload.stability.penalty_weight,2)} · ${payload.stability.evidence_label||"CALCULATED"}`;
  $("stabilityMetrics").innerHTML=[
    ["Changed operations",metrics.changed_operations],
    ["Start-time changes",metrics.start_time_changes],
    ["Machine reassignments",metrics.machine_reassignments],
    ["Time displaced",fmt(metrics.total_start_time_displacement,1)],
    ["Frozen-zone violations",metrics.frozen_zone_violations?.length||0],
  ].map(([label,value])=>`<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
  const changes=metrics.change_log||[];
  if(changes.length){
    const rows=changes.slice(0,8).map(row=>`<div class="change-row"><strong>${esc(row.operation_id)}</strong><span>${fmt(row.prior_start,1)} → ${fmt(row.candidate_start,1)}</span><b>Δ ${fmt(row.start_delta,1)}</b></div>`).join("");
    $("scheduleChangeList").innerHTML=`<div class="change-list-title">Largest plan movements</div>${rows}`;
  } else {
    $("scheduleChangeList").innerHTML=`<p class="muted">No schedule movements against the SPT status quo.</p>`;
  }
}

function renderLedger(payload){
  state.ledger=payload;
  const rows=payload?.events||[];
  $("eventLedger").innerHTML=rows.length?`<table class="evidence-table ledger-table"><thead><tr><th>#</th><th>Event</th><th>At</th><th>Entity</th><th>Source</th><th>State mutation</th><th>Replay</th></tr></thead><tbody>${rows.slice().reverse().map(row=>{const change=row.state_change||{};const count=(change.machines||[]).length+(change.jobs||[]).length+(change.operations||[]).length;return `<tr><td>${row.sequence}</td><td><b>${esc(row.event_type)}</b><small>${esc(row.event_id)}</small></td><td>${fmt(row.timestamp,1)}</td><td>${esc(row.operation_id||row.job_id||row.machine_id||"—")}</td><td>${esc(row.source)}</td><td>${count} state object${count===1?"":"s"} changed<br><small>${esc(row.after_state_id)}</small></td><td><span class="status-dot ${row.accepted?"ok":"hot"}">${row.accepted?"ACCEPTED":"REJECTED"}</span></td></tr>`;}).join("")}</tbody></table>`:`<p class="muted">No persisted events. The zero-state twin is still a valid benchmark state.</p>`;
}

function renderHistory(rows){
  state.history=rows;
  $("decisionHistory").innerHTML=rows?.length?`<table class="evidence-table history-table"><thead><tr><th>Run</th><th>Kind</th><th>Twin</th><th>Solver</th><th>Recommendation</th><th>Human disposition</th></tr></thead><tbody>${rows.map(row=>{const result=row.result||{};const recommendation=result.stress_test?.recommended_policy||result.decision?.recommended_schedule||result.status;return `<tr><td><b>${esc(shortId(row.run_id))}</b><small>${esc(row.created_at_utc)}</small></td><td>${esc(row.decision_kind)}</td><td>${esc(row.twin_state_id)}<small>${row.twin_event_count} events · t=${fmt(row.twin_timestamp,1)}</small></td><td>${esc(row.solver_backend)}</td><td>${esc(recommendation)}</td><td><span class="status-dot ${row.human_disposition==="approved"?"ok":row.human_disposition==="rejected"?"hot":"neutral"}">${esc(String(row.human_disposition||"pending").toUpperCase())}</span></td></tr>`;}).join("")}</tbody></table>`:`<p class="muted">No auditable decision runs yet.</p>`;
}

function renderPolicies(payload){
  state.stress=payload;
  const rows=payload.stress_test?.summaries||[], recommended=payload.stress_test?.recommended_policy;
  $("policyRows").innerHTML=rows.length ? rows.map(p=>`<div class="policy ${p.policy===recommended?"recommended":""}"><h3>${p.policy}${p.policy===recommended?'<span class="policy-badge">RECOMMENDED</span>':""}</h3><div class="metric-line"><span>Mean tardiness</span><strong>${fmt(p.mean_total_tardiness)}</strong></div><div class="metric-line"><span>CVaR95 tardiness</span><strong>${fmt(p.cvar95_total_tardiness)}</strong></div><div class="metric-line"><span>Mean makespan</span><strong>${fmt(p.mean_makespan)}</strong></div><div class="metric-line"><span>Service level</span><strong>${pct(p.mean_service_level)}</strong></div><div class="metric-line"><span>Robust score</span><strong>${fmt(p.robust_score)}</strong></div></div>`).join("") : `<p class="muted">No feasible policy comparison is available.</p>`;
  const rec=$("recommendation"); rec.classList.remove("empty"); rec.innerHTML=`<div><span class="recommendation-label">RECOMMENDATION</span><strong>${recommended||"NO ACTION"}</strong><span>${payload.stress_test?.rationale||"Selected by the configured stochastic robust objective."}</span></div>`;
  renderDecisionPacket(payload);
}


function trustControls(){ return {freshness_horizon:num("trustFreshnessHorizon"),authorize_threshold:num("trustAuthorizeThreshold"),review_threshold:num("trustReviewThreshold")}; }
function renderTrustRh(trust, optimizerExecuted=null){
  const sig=trust.signals||{};
  $("trustRhBadge").textContent=trust.decision||"UNKNOWN";
  $("trustRhScore").textContent=fmt(trust.score,3);
  $("trustRhStructural").textContent=fmt(sig.structural_consistency,3);
  $("trustRhLedger").textContent=fmt(sig.event_ledger_consistency,3);
  $("trustRhEvidence").textContent=fmt(sig.model_evidence_coverage,3);
  $("trustRhFreshness").textContent=fmt(sig.freshness,3);
  if(optimizerExecuted!==null) $("trustRhOptimizer").textContent=optimizerExecuted?"EXECUTED":"GATED / NOT EXECUTED";
  const reasons=sig.hard_stop_reasons||[];
  $("trustRhReasons").textContent=reasons.length?`Hard stops: ${reasons.join(", ")}`:`Evidence boundary: ${trust.evidence_boundary||"engineering authorization evidence"}`;
}
async function assessTrustRh(){
  const b=$("assessTrustBtn"); busy(b);
  try{
    const c=trustControls();
    const q=new URLSearchParams(c).toString();
    const trust=await api(`/v1/twin/trust?${q}`); renderTrustRh(trust,null);
  }catch(e){ alert(e.message); } finally{ busy(b,false); }
}
async function runTrustedRecovery(){
  const b=$("trustedRecoveryBtn"); busy(b);
  try{
    const c=trustControls(), s=scenario();
    const payload=await api("/v1/decision/trusted-recovery",{method:"POST",body:JSON.stringify({backend:s.backend,due_factor:s.due_factor,time_limit_seconds:30,processing_cv:s.processing_cv,mtbf:s.mtbf,mttr:s.mttr,stability_penalty:s.stability_penalty,...c})});
    renderTrustRh(payload.trust,payload.optimizer_executed);
    if(payload.optimizer_executed){ state.recovery=payload; renderTimeline(payload.nominal_optimized?.operations||payload.optimized?.operations||[],[]); renderDecisionPacket(payload); }
  }catch(e){ alert(e.message); } finally{ busy(b,false); }
}

async function refreshContext(){
  const s=scenario();
  const [twin,operational,ie]=await Promise.all([
    api("/v1/twin/state"),
    api(`/v1/ai/operational?due_factor=${s.due_factor}&processing_cv=${s.processing_cv}&mtbf=${s.mtbf}&mttr=${s.mttr}`),
    api(`/v1/ie/control-plan?due_factor=${s.due_factor}&horizon=100&buffer_time=5&wip_limit=3`)
  ]);
  renderTwinContext(twin,operational,ie);
}

async function loadNominal(){
  const b=$("nominalBtn"); busy(b);
  workflowStep("nominalBtn","running");
  workflowStatus("STEP 01 · building synchronized recovery…","running");
  try{
    const s=scenario();
    const payload=await api("/v1/decision/recovery",{method:"POST",body:JSON.stringify({backend:s.backend,due_factor:s.due_factor,time_limit_seconds:30,processing_cv:s.processing_cv,mtbf:s.mtbf,mttr:s.mttr,stability_penalty:s.stability_penalty})});
    state.recovery=payload;
    renderTimeline(payload.nominal_optimized?.operations||payload.optimized?.operations||[],[]);
    $("timelineLabel").textContent="OPTIMIZED DECISION · SYNCHRONIZED TWIN";
    renderDecisionPacket(payload);
    await loadHistory();
    workflowStep("nominalBtn","complete");
    workflowStatus("STEP 01 COMPLETE · synchronized recovery loaded","complete");
  }catch(e){ workflowStatus(`STEP 01 BLOCKED · ${e.message}`,"error"); alert(e.message); }
  finally{ busy(b,false); }
}
async function runTrajectory(){
  const b=$("trajectoryBtn"); busy(b);
  workflowStep("trajectoryBtn","running");
  workflowStatus("STEP 02 · simulating representative future…","running");
  try{
    const s=scenario();
    const payload=await api("/v1/simulation/run",{method:"POST",body:JSON.stringify({policy:"OPTIMIZED",backend:s.backend,due_factor:s.due_factor,seed:s.base_seed,processing_cv:s.processing_cv,mtbf:s.mtbf,mttr:s.mttr,stressed_machine_id:s.stressed_machine_id,stressed_machine_mtbf:s.stressed_machine_mtbf,stressed_machine_mttr:s.stressed_machine_mttr,include_events:true})});
    state.simulation=payload; renderTimeline(payload.operations,payload.downtime_intervals||[]); $("timelineLabel").textContent="SIMULATED FUTURE STATE";
    workflowStep("trajectoryBtn","complete");
    workflowStatus(`STEP 02 COMPLETE · ${payload.operations?.length||0} operations simulated`,"complete");
    revealWorkflowTarget("timeline");
  }catch(e){workflowStatus(`STEP 02 BLOCKED · ${e.message}`,"error"); alert(e.message);} finally{busy(b,false);}
}
async function runStress(){
  const b=$("stressBtn"); busy(b);
  workflowStep("stressBtn","running");
  workflowStatus("STEP 03 · comparing four policies with common-random-number simulation…","running");
  try{ const payload=await api("/v1/decision/stress-test",{method:"POST",body:JSON.stringify(scenario())}); renderPolicies(payload); const recommended=payload.stress_test?.recommended_policy||"no robust recommendation"; workflowStep("stressBtn","complete"); workflowStatus(`STEP 03 COMPLETE · recommendation ${recommended}`,"complete"); revealWorkflowTarget("decisionSurface"); }
  catch(e){workflowStatus(`STEP 03 BLOCKED · ${e.message}`,"error"); alert(e.message);} finally{busy(b,false);}
}

async function setDisposition(disposition){
  if(!state.currentRunId){ alert("Run a recovery or stress test first."); return; }
  const note=$("decisionNote").value.trim()||null;
  try{
    const payload=await api(`/v1/decisions/${state.currentRunId}/disposition`,{method:"POST",body:JSON.stringify({disposition,note})});
    const value=String(payload.human_disposition||disposition).toUpperCase();
    $("decisionDisposition").textContent=value; $("reviewState").textContent=value;
    await loadHistory();
  }catch(e){ alert(e.message); }
}

async function dataAction(replay=false){ const box=$("dataResult"); if(!state.fileText){box.textContent="Choose a CSV first.";return;} try{ const payload=await api(replay?"/v1/data/replay-events":"/v1/data/validate-events",{method:"POST",body:JSON.stringify({csv_text:state.fileText})}); box.textContent=JSON.stringify(payload,null,2); }catch(e){box.textContent=`ERROR\n${e.message}`;} }
function renderSyntheticDataset(payload){
  state.synthetic=payload;
  const metrics=payload.metrics||{};
  const integrity=payload.integrity||{};
  $("syntheticDatasetSummary").innerHTML=[
    ["Rows",Number(payload.rows||0).toLocaleString(),"reproducible scenario observations"],
    ["Fields",payload.columns,"schema columns"],
    ["Scenario families",Object.keys(payload.distributions?.scenario_classes||{}).length,"balanced operating conditions"],
    ["Mean utilization",`${fmt(metrics.mean_machine_utilization_pct,1)}%`,`synthetic operating signal`],
    ["Mean risk",fmt(metrics.mean_risk_score,3),"derived risk label"],
    ["Integrity",integrity.ready?"READY":"CHECK","SHA-256 + manifest verified"],
  ].map(([label,value,note])=>`<div class="dataset-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join("");
  $("syntheticDatasetBoundary").textContent=`${payload.evidence_label||"SYNTHETIC / REPRODUCIBLE"} · ${payload.dataset_role||"demo-only"} · seed ${payload.seed} · SHA-256 ${shortId(payload.sha256)}`;
  $("syntheticDatasetDownload").href=payload.download_url||"/v1/data/synthetic/download";
}
async function loadSyntheticDataset(){ try{ renderSyntheticDataset(await api("/v1/data/synthetic")); }catch(e){ $("syntheticDatasetSummary").innerHTML=`<p class="error">Dataset integrity unavailable: ${esc(e.message)}</p>`; $("syntheticDatasetBoundary").textContent="Synthetic dataset could not be verified; do not use it until the integrity endpoint is healthy."; } }
async function runCopilotScenario(){ const b=$("copilotScenarioBtn"), q=$("scenarioPrompt").value.trim(); if(!q)return; busy(b); try{ const payload=await api("/v1/copilot/run-scenario",{method:"POST",body:JSON.stringify({request:q,backend:$("backend").value,time_limit_seconds:30,base_seed:20260815})}); $("copilotResult").textContent=`Interpreted scenario\n${JSON.stringify(payload.interpretation,null,2)}\n\nDeterministic recommendation: ${payload.engineering_result.stress_test?.recommended_policy||"not ready"}`; if(payload.engineering_result.stress_test) renderPolicies(payload.engineering_result); }catch(e){$("copilotResult").textContent=`Gemini unavailable/error: ${e.message}`;}finally{busy(b,false);} }
async function explainEvidence(){ const b=$("copilotExplainBtn"), q=$("explainPrompt").value.trim(); if(!q)return; busy(b); try{ const s=scenario(); const payload=await api("/v1/copilot/explain",{method:"POST",body:JSON.stringify({question:q,...s})}); const a=payload.answer; $("copilotResult").textContent=`${a.answer}\n\nEvidence used: ${(a.evidence_used||[]).join(", ")||"—"}\nAssumptions: ${(a.assumptions||[]).join("; ")||"—"}\nCaveats: ${(a.caveats||[]).join("; ")||"—"}\nNext action: ${a.recommended_next_action||"—"}`; }catch(e){$("copilotResult").textContent=`Gemini unavailable/error: ${e.message}`;}finally{busy(b,false);} }


function downloadEvidence(){
  const payload=state.stress||state.recovery;
  if(!payload){ alert("Run a recovery or stress test first."); return; }
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a");
  a.href=url; a.download=`mdt-decision-evidence-${state.currentRunId||"latest"}.json`;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
function configureDemoMode(){
  const demo=new URLSearchParams(window.location.search).get("mode")==="demo";
  if(!demo) return;
  $("demoModeBadge").classList.remove("hidden");
  $("dueFactor").value="1.35"; $("processingCv").value="0.14"; $("mtbf").value="100"; $("mttr").value="8";
  $("replications").value="12"; $("riskAversion").value="0.45"; $("stressMtbf").value="32"; $("stressMttr").value="14";
}

async function loadLedger(){ try{ renderLedger(await api("/v1/twin/ledger")); }catch(e){ $("eventLedger").innerHTML=`<p class="error">Ledger unavailable: ${esc(e.message)}</p>`; } }
async function loadHistory(){ try{ renderHistory(await api("/v1/decisions?limit=12")); }catch(e){ $("decisionHistory").innerHTML=`<p class="error">Decision history unavailable: ${esc(e.message)}</p>`; } }

async function bootstrap(){
  try{
    const [health,factory,readiness,copilot]=await Promise.all([api("/health"),api("/v1/factory"),api("/v1/data/readiness"),api("/v1/copilot/status")]);
    state.factory=factory;
    $("apiStatus").textContent="TWIN ONLINE"; $("apiStatus").className="status-pill ok";
    $("versionStatus").textContent=`v${health.version}`;
    $("solverStatus").textContent=health.gurobi_python_available?"Gurobi ready":"HiGHS mode";
    $("geminiStatus").textContent=copilot.api_key_configured&&copilot.sdk_available?`${copilot.model} ready`:"Gemini optional";
    factory.machine_ids.forEach(m=>$("stressMachine").insertAdjacentHTML("beforeend",`<option value="${m}">${m}</option>`));
    configureDemoMode();
    if(new URLSearchParams(window.location.search).get("mode")==="demo" && factory.machine_ids.includes("M5")) $("stressMachine").value="M5";
    $("dataSchema").textContent=readiness.canonical_event_columns.join("  |  ");
    await loadSyntheticDataset();
    $("copilotResult").textContent=copilot.api_key_configured?`Gemini configured: ${copilot.model}`:"Set GEMINI_API_KEY in .env to enable the interrogation layer. All deterministic engineering features remain available.";
    await refreshContext();
    await loadLedger();
    await loadHistory();
    await assessTrustRh();
    renderRisk(await api(`/v1/ai/lateness-risk?due_factor=${num("dueFactor")}`));
    await loadNominal();
  }catch(e){ $("apiStatus").textContent="TWIN ERROR"; $("apiStatus").className="status-pill"; $("copilotResult").textContent=e.message; }
}

$("assessTrustBtn").addEventListener("click",assessTrustRh); $("trustedRecoveryBtn").addEventListener("click",runTrustedRecovery);
$("nominalBtn").addEventListener("click",loadNominal); $("trajectoryBtn").addEventListener("click",runTrajectory); $("stressBtn").addEventListener("click",runStress);
$("dueFactor").addEventListener("change",async()=>{try{renderRisk(await api(`/v1/ai/lateness-risk?due_factor=${num("dueFactor")}`));await refreshContext();}catch(e){console.error(e);}});
["processingCv","mtbf","mttr"].forEach(id=>$(id).addEventListener("change",()=>refreshContext().catch(console.error)));
$("stabilityPenalty").addEventListener("change",()=>{if(state.recovery)renderStability(state.recovery);});
$("eventFile").addEventListener("change",async(e)=>{ const f=e.target.files?.[0]; state.fileText=f?await f.text():""; $("dataResult").textContent=f?`${f.name} loaded (${state.fileText.length} characters). Ready to validate.`:"No file selected."; });
$("downloadEvidenceBtn").addEventListener("click",downloadEvidence);
$("validateDataBtn").addEventListener("click",()=>dataAction(false)); $("replayDataBtn").addEventListener("click",()=>dataAction(true));
$("copilotScenarioBtn").addEventListener("click",runCopilotScenario); $("copilotExplainBtn").addEventListener("click",explainEvidence);
$("refreshLedgerBtn").addEventListener("click",loadLedger); $("refreshHistoryBtn").addEventListener("click",loadHistory);
document.querySelectorAll("[data-preset]").forEach(button=>button.addEventListener("click",()=>applyScenarioPreset(button.dataset.preset)));
document.querySelectorAll("[data-disposition]").forEach(btn=>btn.addEventListener("click",()=>setDisposition(btn.dataset.disposition)));
bootstrap();
