from __future__ import annotations

from collections import Counter
from threading import Lock
from time import perf_counter


class MetricsRegistry:
    """Small dependency-free Prometheus text registry for platform metrics."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._errors: Counter[str] = Counter()
        self._latency_seconds: Counter[str] = Counter()
        self._request_count = 0
        self._started = perf_counter()

    def observe_request(self, method: str, route: str, status_code: int, elapsed_seconds: float) -> None:
        with self._lock:
            self._requests[(method, route, status_code)] += 1
            self._latency_seconds[route] += elapsed_seconds
            self._request_count += 1
            if status_code >= 500:
                self._errors[route] += 1

    def render(self) -> str:
        with self._lock:
            lines = [
                "# HELP mdt_process_uptime_seconds Process uptime in seconds.",
                "# TYPE mdt_process_uptime_seconds gauge",
                f"mdt_process_uptime_seconds {perf_counter() - self._started:.6f}",
                "# HELP mdt_http_requests_total HTTP requests by method, route and status.",
                "# TYPE mdt_http_requests_total counter",
            ]
            for (method, route, status), count in sorted(self._requests.items()):
                labels = f'method="{method}",route="{route}",status="{status}"'
                lines.append(f"mdt_http_requests_total{{{labels}}} {count}")
            lines.extend([
                "# HELP mdt_http_request_duration_seconds_sum Request duration sum by route.",
                "# TYPE mdt_http_request_duration_seconds_sum counter",
            ])
            for route, total in sorted(self._latency_seconds.items()):
                lines.append(f'mdt_http_request_duration_seconds_sum{{route="{route}"}} {total:.6f}')
            lines.extend([
                "# HELP mdt_http_errors_total HTTP 5xx responses by route.",
                "# TYPE mdt_http_errors_total counter",
            ])
            for route, count in sorted(self._errors.items()):
                lines.append(f'mdt_http_errors_total{{route="{route}"}} {count}')
            return "\n".join(lines) + "\n"
