from pathlib import Path
HTML=Path('workspace/index.html').read_text(encoding='utf-8')
JS=Path('workspace/app.js').read_text(encoding='utf-8')
def test_trust_rh_has_dedicated_operator_surface():
    for token in ['TRUST-RH AUTHORIZATION GATE','Should this twin be trusted enough to optimize?','Freshness horizon','Authorize threshold','Review threshold','Run trust-gated recovery']:
        assert token in HTML
def test_trust_rh_surface_calls_gated_api_and_exposes_optimizer_status():
    assert '/v1/twin/trust' in JS and '/v1/decision/trusted-recovery' in JS
    assert 'optimizer_executed' in JS and 'GATED / NOT EXECUTED' in JS
