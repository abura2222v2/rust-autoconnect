"""Pure helpers for reproducible, privacy-preserving benchmark records."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
import uuid
from typing import Any, Iterable


BENCHMARK_VERSION = "rust-load-v1"
MIN_PHASE_SECONDS = 2.0
MAX_PHASE_SECONDS = 600.0


def normalize_component(value: str) -> str:
    """Return a stable display-safe component name without device identifiers."""
    return " ".join(str(value or "Unknown").strip().split())[:160] or "Unknown"


def configuration_key(cpu: str, storage: str, benchmark_version: str = BENCHMARK_VERSION) -> str:
    payload = {
        "benchmark_version": normalize_component(benchmark_version),
        "cpu": normalize_component(cpu).casefold(),
        "storage": normalize_component(storage).casefold(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_valid_timings(time_to_menu: float, demo_load_time: float) -> bool:
    values = (time_to_menu, demo_load_time)
    return all(math.isfinite(value) and MIN_PHASE_SECONDS <= value <= MAX_PHASE_SECONDS for value in values)


def build_run(
    installation_id: str,
    cpu: str,
    storage: str,
    storage_bus: str,
    time_to_menu: float,
    demo_load_time: float,
    benchmark_version: str = BENCHMARK_VERSION,
) -> dict[str, Any]:
    if not is_valid_timings(time_to_menu, demo_load_time):
        raise ValueError("benchmark timings are outside the accepted range")

    cpu_label = normalize_component(cpu)
    storage_label = normalize_component(storage)
    return {
        "id": str(uuid.uuid4()),
        "installation_id": str(installation_id),
        "configuration_key": configuration_key(cpu_label, storage_label, benchmark_version),
        "cpu": cpu_label,
        "storage": storage_label,
        "storage_bus": normalize_component(storage_bus),
        "benchmark_version": normalize_component(benchmark_version),
        "time_to_menu": round(float(time_to_menu), 3),
        "demo_load_time": round(float(demo_load_time), 3),
        "total_time": round(float(time_to_menu) + float(demo_load_time), 3),
        "created_at": int(time.time()),
        "sync_state": "pending",
    }


def median(values: Iterable[float]) -> float | None:
    numbers = [float(value) for value in values]
    return round(statistics.median(numbers), 3) if numbers else None
