const $ = (id) => document.getElementById(id);
const state = { factory: null, twin: null, risk: null, operational: null, ie: null, recovery: null, simulation: null, stress: null, fileText: "", currentRunId: null };

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  let payload;
  try { payload = await response.json(); } catch { payload = { detail: await response.text() }; }
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload));
  return payload;
}
const num = (id) => Number($(id).value);
const scenario = () => {
  const machine = $("stressMachine").value || null;
  return {
    backend: $("backend").value,
    due_factor: num("dueFactor"), replications: Math.round(num("replications")), base_seed: 20260815,
    processing_cv: num("processingCv"), mtbf: num("mtbf"), mttr: num("mttr"), risk_aversion: num("riskAversion"),
    stressed_machine_id: machine,
    stressed_machine_mtbf: machine ? num("stressMtbf") : null,
    stressed_machine_mttr: machine ? num("stressMttr") : null,
  };
};
function fmt(v, d=2){ return Number.isFinite(Number(v)) ? Number(v).toFixed(d) : "—"; }
function pct(v, d=1){ return Number.isFinite(Number(v)) ? `${(100*Number(v)).toFixed(d)}%` : "—"; }
function busy(button, value=true){ button.disabled=value; button.classList.toggle("busy", value); }
function shortId(value){ return value ? String(value).slice(0,8) : "—"; }

function renderTwinContext(twin, operational, ie){
  state.twin=twin; state.operational=operational; state.ie=ie;
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
  $("decisionDetails").innerHTML=`<strong>Assumptions</strong><ul>${assumptions.map(x=>`<li>${x}</li>`).join("")}</ul><strong>Trade-offs</strong><ul>${tradeoffs.map(x=>`<li>${x}</li>`).join("")}</ul>`;
  const disposition=(decision.human_disposition||"pending").toUpperCase();
  $("decisionDisposition").textContent=disposition;
  $("reviewState").textContent=disposition;
  $("decisionRunId").textContent=`Run ${shortId(state.currentRunId)} · full ID ${state.currentRunId||"—"}`;
}

function renderPolicies(payload){
  state.stress=payload;
  const rows=payload.stress_test?.summaries||[], recommended=payload.stress_test?.recommended_policy;
  $("policyRows").innerHTML=rows.length ? rows.map(p=>`<div class="policy ${p.policy===recommended?"recommended":""}"><h3>${p.policy}${p.policy===recommended?'<span class="policy-badge">RECOMMENDED</span>':""}</h3><div class="metric-line"><span>Mean tardiness</span><strong>${fmt(p.mean_total_tardiness)}</strong></div><div class="metric-line"><span>CVaR95 tardiness</span><strong>${fmt(p.cvar95_total_tardiness)}</strong></div><div class="metric-line"><span>Mean makespan</span><strong>${fmt(p.mean_makespan)}</strong></div><div class="metric-line"><span>Service level</span><strong>${pct(p.mean_service_level)}</strong></div><div class="metric-line"><span>Robust score</span><strong>${fmt(p.robust_score)}</strong></div></div>`).join("") : `<p class="muted">No feasible policy comparison is available.</p>`;
  const rec=$("recommendation"); rec.classList.remove("empty"); rec.innerHTML=`<div><span class="recommendation-label">RECOMMENDATION</span><strong>${recommended||"NO ACTION"}</strong><span>${payload.stress_test?.rationale||"Selected by the configured stochastic robust objective."}</span></div>`;
  renderDecisionPacket(payload);
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
  try{
    const s=scenario();
    const payload=await api("/v1/decision/recovery",{method:"POST",body:JSON.stringify({backend:s.backend,due_factor:s.due_factor,time_limit_seconds:30,processing_cv:s.processing_cv,mtbf:s.mtbf,mttr:s.mttr})});
    state.recovery=payload;
    renderTimeline(payload.nominal_optimized?.operations||payload.optimized?.operations||[],[]);
    $("timelineLabel").textContent="OPTIMIZED DECISION · SYNCHRONIZED TWIN";
    renderDecisionPacket(payload);
  }catch(e){ alert(e.message); }
  finally{ busy(b,false); }
}
async function runTrajectory(){
  const b=$("trajectoryBtn"); busy(b);
  try{
    const s=scenario();
    const payload=await api("/v1/simulation/run",{method:"POST",body:JSON.stringify({policy:"OPTIMIZED",backend:s.backend,due_factor:s.due_factor,seed:s.base_seed,processing_cv:s.processing_cv,mtbf:s.mtbf,mttr:s.mttr,stressed_machine_id:s.stressed_machine_id,stressed_machine_mtbf:s.stressed_machine_mtbf,stressed_machine_mttr:s.stressed_machine_mttr,include_events:true})});
    state.simulation=payload; renderTimeline(payload.operations,payload.downtime_intervals||[]); $("timelineLabel").textContent="SIMULATED FUTURE STATE";
  }catch(e){alert(e.message);} finally{busy(b,false);}
}
async function runStress(){
  const b=$("stressBtn"); busy(b);
  try{ const payload=await api("/v1/decision/stress-test",{method:"POST",body:JSON.stringify(scenario())}); renderPolicies(payload); }
  catch(e){alert(e.message);} finally{busy(b,false);}
}

async function setDisposition(disposition){
  if(!state.currentRunId){ alert("Run a recovery or stress test first."); return; }
  const note=$("decisionNote").value.trim()||null;
  try{
    const payload=await api(`/v1/decisions/${state.currentRunId}/disposition`,{method:"POST",body:JSON.stringify({disposition,note})});
    const value=String(payload.human_disposition||disposition).toUpperCase();
    $("decisionDisposition").textContent=value; $("reviewState").textContent=value;
  }catch(e){ alert(e.message); }
}

async function dataAction(replay=false){ const box=$("dataResult"); if(!state.fileText){box.textContent="Choose a CSV first.";return;} try{ const payload=await api(replay?"/v1/data/replay-events":"/v1/data/validate-events",{method:"POST",body:JSON.stringify({csv_text:state.fileText})}); box.textContent=JSON.stringify(payload,null,2); }catch(e){box.textContent=`ERROR\n${e.message}`;} }
async function runCopilotScenario(){ const b=$("copilotScenarioBtn"), q=$("scenarioPrompt").value.trim(); if(!q)return; busy(b); try{ const payload=await api("/v1/copilot/run-scenario",{method:"POST",body:JSON.stringify({request:q,backend:$("backend").value,time_limit_seconds:30,base_seed:20260815})}); $("copilotResult").textContent=`Interpreted scenario\n${JSON.stringify(payload.interpretation,null,2)}\n\nDeterministic recommendation: ${payload.engineering_result.stress_test?.recommended_policy||"not ready"}`; if(payload.engineering_result.stress_test) renderPolicies(payload.engineering_result); }catch(e){$("copilotResult").textContent=`Gemini unavailable/error: ${e.message}`;}finally{busy(b,false);} }
async function explainEvidence(){ const b=$("copilotExplainBtn"), q=$("explainPrompt").value.trim(); if(!q)return; busy(b); try{ const s=scenario(); const payload=await api("/v1/copilot/explain",{method:"POST",body:JSON.stringify({question:q,...s})}); const a=payload.answer; $("copilotResult").textContent=`${a.answer}\n\nEvidence used: ${(a.evidence_used||[]).join(", ")||"—"}\nAssumptions: ${(a.assumptions||[]).join("; ")||"—"}\nCaveats: ${(a.caveats||[]).join("; ")||"—"}\nNext action: ${a.recommended_next_action||"—"}`; }catch(e){$("copilotResult").textContent=`Gemini unavailable/error: ${e.message}`;}finally{busy(b,false);} }

async function bootstrap(){
  try{
    const [health,factory,readiness,copilot]=await Promise.all([api("/health"),api("/v1/factory"),api("/v1/data/readiness"),api("/v1/copilot/status")]);
    state.factory=factory;
    $("apiStatus").textContent="TWIN ONLINE"; $("apiStatus").className="status-pill ok";
    $("versionStatus").textContent=`v${health.version}`;
    $("solverStatus").textContent=health.gurobi_python_available?"Gurobi ready":"HiGHS mode";
    $("geminiStatus").textContent=copilot.api_key_configured&&copilot.sdk_available?`${copilot.model} ready`:"Gemini optional";
    factory.machine_ids.forEach(m=>$("stressMachine").insertAdjacentHTML("beforeend",`<option value="${m}">${m}</option>`));
    $("dataSchema").textContent=readiness.canonical_event_columns.join("  |  ");
    $("copilotResult").textContent=copilot.api_key_configured?`Gemini configured: ${copilot.model}`:"Set GEMINI_API_KEY in .env to enable the interrogation layer. All deterministic engineering features remain available.";
    await refreshContext();
    renderRisk(await api(`/v1/ai/lateness-risk?due_factor=${num("dueFactor")}`));
    await loadNominal();
  }catch(e){ $("apiStatus").textContent="TWIN ERROR"; $("apiStatus").className="status-pill"; $("copilotResult").textContent=e.message; }
}

$("nominalBtn").addEventListener("click",loadNominal); $("trajectoryBtn").addEventListener("click",runTrajectory); $("stressBtn").addEventListener("click",runStress);
$("dueFactor").addEventListener("change",async()=>{try{renderRisk(await api(`/v1/ai/lateness-risk?due_factor=${num("dueFactor")}`));await refreshContext();}catch(e){console.error(e);}});
["processingCv","mtbf","mttr"].forEach(id=>$(id).addEventListener("change",()=>refreshContext().catch(console.error)));
$("eventFile").addEventListener("change",async(e)=>{ const f=e.target.files?.[0]; state.fileText=f?await f.text():""; $("dataResult").textContent=f?`${f.name} loaded (${state.fileText.length} characters). Ready to validate.`:"No file selected."; });
$("validateDataBtn").addEventListener("click",()=>dataAction(false)); $("replayDataBtn").addEventListener("click",()=>dataAction(true));
$("copilotScenarioBtn").addEventListener("click",runCopilotScenario); $("copilotExplainBtn").addEventListener("click",explainEvidence);
document.querySelectorAll("[data-disposition]").forEach(btn=>btn.addEventListener("click",()=>setDisposition(btn.dataset.disposition)));
bootstrap();
