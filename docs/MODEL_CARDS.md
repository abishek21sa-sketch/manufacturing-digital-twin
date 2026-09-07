# Model Cards — V1.0 Operational AI

All four packaged models are deterministic research/demo artifacts. Their
metrics are reported on synthetic benchmark-derived scenarios and must not be
quoted as production accuracy for a named factory.

## Shared controls

- Data generation and evaluation are seeded and versioned.
- Scenario/group splits keep records from the same generated scenario out of
  both training and test partitions.
- Each task has a simple baseline and a challenger comparison.
- The test set is not used to tune the selected model.
- Model artifacts are packaged with the release and loaded by the API.
- Outputs carry an evidence label and a decision-use description.
- Monitoring, recalibration, and retraining require plant-specific data and
  approval; they are not implied by these artifacts.

## Lateness-risk classification

- Intended use: rank residual jobs by estimated lateness risk so the finite-
  capacity objective can weight tardiness.
- Model: standardized logistic regression.
- Baseline/challenger: class-prior baseline and histogram gradient boosting.
- Test metrics: ROC-AUC 0.9718, PR-AUC 0.9361, F1 0.8466, Brier 0.0598,
  10-bin ECE 0.0189.
- Do not use for: autonomous dispatch, safety decisions, personnel decisions,
  or plant-wide probability claims without calibration.
- Known limits: labels come from generated FT06 perturbations; calibration is
  conditional on that synthetic distribution.

## Remaining/cycle-time regression

- Intended use: estimate expected flow-time consequence for a residual job.
- Model: standardized Ridge regression.
- Baseline/challenger: remaining-touch-time baseline and histogram gradient
  boosting regressor.
- Test metrics: MAE 7.078, RMSE 8.786, R² 0.543.
- Do not use for: contractual delivery promises or staffing decisions without
  plant-specific time-study and historical validation.
- Known limits: waiting, routing, and reliability effects are generated from
  the benchmark scenario model.

## Future bottleneck prediction

- Intended use: select a machine to stress in future-state evaluation when the
  operator has not chosen one.
- Model: standardized multinomial/logistic classifier.
- Baseline/challenger: static workload constraint and histogram gradient
  boosting classifier.
- Test metrics: top-1 accuracy 0.667, ROC-AUC 0.9344, PR-AUC 0.7848.
- Do not use for: declaring a permanent plant constraint or overriding a
  planner's local knowledge.
- Known limits: the target is the maximum pressure index in seeded simulation.

## Operational anomaly detection

- Intended use: prioritize machine-state patterns for human review and
  future-state stress testing.
- Model: Isolation Forest trained on generated normal envelopes.
- Baseline: downtime-only threshold.
- Test metrics: ROC-AUC 0.9683, PR-AUC 0.9539.
- Output semantics: the anomaly index is a score, not a probability and not a
  root-cause diagnosis.
- Do not use for: automatic shutdown, quality disposition, or personnel
  accountability.
- Known limits: evaluation anomalies are injected distortions, not labeled
  plant failures.

## Acceptance criteria for a future plant model

Before any production claim, repeat the cards with a documented site data
contract, time-based or forward-chaining evaluation, leakage review, calibrated
uncertainty, subgroup/shift analysis where relevant, drift thresholds,
rollback criteria, and planner/operator acceptance evidence.
