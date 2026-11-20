"""Executa as probes com timeout, em paralelo quando possível.

O adaptador roda primeiro porque as outras probes dependem dele (gateway e
DNS configurado). Ping, DNS e HTTP rodam em paralelo depois.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.probes import adapter, dns, http, ping

ProbeFn = Callable[[dict[str, Any]], ProbeResult]

FIRST: tuple[tuple[str, ProbeFn], ...] = ((adapter.NAME, adapter.run),)
PARALLEL: tuple[tuple[str, ProbeFn], ...] = (
    (ping.NAME, ping.run),
    (dns.NAME, dns.run),
    (http.NAME, http.run),
)
PROBE_TIMEOUT_S = 30.0


def _safe(name: str, fn: ProbeFn, ctx: dict[str, Any]) -> ProbeResult:
    start = time.perf_counter()
    try:
        result = fn(ctx)
    except Exception:  # uma probe com bug não pode derrubar o diagnóstico
        result = ProbeResult(name, ok=False, error=ErrorCode.UNEXPECTED)
    result.duration_ms = round((time.perf_counter() - start) * 1000)
    return result


def run_all(
    first: tuple[tuple[str, ProbeFn], ...] = FIRST,
    parallel: tuple[tuple[str, ProbeFn], ...] = PARALLEL,
    timeout: float = PROBE_TIMEOUT_S,
    on_progress: Callable[[str], None] | None = None,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    ctx: dict[str, Any] = {}

    for name, fn in first:
        if on_progress:
            on_progress(name)
        result = _safe(name, fn, ctx)
        results.append(result)
        if result.ok:
            ctx.update(result.data)

    if not parallel:
        return results

    pool = ThreadPoolExecutor(max_workers=len(parallel))
    try:
        futures = []
        for name, fn in parallel:
            if on_progress:
                on_progress(name)
            futures.append((name, pool.submit(_safe, name, fn, dict(ctx))))
        deadline = time.monotonic() + timeout
        for name, future in futures:
            try:
                results.append(future.result(timeout=max(0.0, deadline - time.monotonic())))
            except FutureTimeout:
                results.append(ProbeResult(name, ok=False, error=ErrorCode.TIMEOUT))
    finally:
        # Não espera threads presas: o diagnóstico sai mesmo com uma probe travada.
        pool.shutdown(wait=False, cancel_futures=True)
    return results
