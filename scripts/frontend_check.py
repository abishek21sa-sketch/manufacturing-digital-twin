from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    assets = (
        root / "workspace/index.html",
        root / "workspace/methodology.html",
        root / "workspace/app.js",
        root / "workspace/methodology.js",
        root / "workspace/styles.css",
    )
    failures: list[str] = []
    for path in assets:
        if not path.exists() or path.stat().st_size < 500:
            failures.append(f"missing/empty frontend asset: {path.relative_to(root)}")
    if not failures:
        html = (root / "workspace/index.html").read_text(encoding="utf-8")
        methodology = (root / "workspace/methodology.html").read_text(encoding="utf-8")
        js = (root / "workspace/app.js").read_text(encoding="utf-8")
        method_js = (root / "workspace/methodology.js").read_text(encoding="utf-8")
        for token in (
            'id="timeline"', 'id="twinStateId"', 'id="decisionPacket"',
            'data-disposition="approved"', 'MANUFACTURING DIGITAL TWIN · V1.0',
            'href="/methodology"', 'HUMAN DECISION GATE',
        ):
            if token not in html:
                failures.append(f"workspace missing contract token: {token}")
        for endpoint in (
            "/v1/decision/stress-test", "/v1/simulation/run", "/v1/data/replay-events",
            "/v1/copilot/run-scenario", "/v1/decisions/", "/v1/ai/operational", "/v1/ie/control-plan",
        ):
            if endpoint not in js:
                failures.append(f"workspace does not call {endpoint}")
        for token in (
            "Engineering Methodology", "LITTLE'S LAW", "NO-REGRET SERVICE GUARD",
            "SCENARIO-BASED CVaR POLICY MILP", "VALIDATION BOUNDARY",
        ):
            if token not in methodology:
                failures.append(f"methodology page missing: {token}")
        if "/v1/methodology/evidence" not in method_js:
            failures.append("methodology page does not load packaged validation evidence")
        joined = "\n".join((html, methodology, js, method_js))
        if "https://" in joined or "http://" in joined:
            failures.append("frontend contains an external runtime URL; frontend must remain offline-capable")
    node = shutil.which("node")
    if node and not failures:
        for js_path in (root / "workspace/app.js", root / "workspace/methodology.js"):
            subprocess.run([node, "--check", str(js_path)], check=True)
        print("NODE_JS_SYNTAX=PASS")
    else:
        print("NODE_JS_SYNTAX=SKIPPED_NOT_REQUIRED")
    if failures:
        raise SystemExit("\n".join(failures))
    print("FRONTEND_CHECK=PASS")


if __name__ == "__main__":
    main()
