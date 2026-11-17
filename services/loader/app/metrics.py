from contextlib import contextmanager
from time import monotonic

from prometheus_client import Counter, Gauge, Histogram


RUNS = Counter("loader_runs", "Completed loader runs by phase and outcome", ["phase", "outcome"])
RUN_DURATION = Histogram(
    "loader_run_duration_seconds", "Loader run duration including retries within a run", ["phase"],
    buckets=(0.1, 1, 5, 10, 30, 60, 120, 300, 600, 900),
)
LAST_SUCCESS = Gauge("loader_last_success_timestamp_seconds", "Last successful run in this process", ["phase"])
COMPANIES = Counter("loader_companies", "Company processing outcomes", ["outcome"])
COMPANY_DURATION = Histogram(
    "loader_company_duration_seconds", "Company processing duration from worker start through storage",
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 60, 120),
)
SOAP_RETRIES = Counter("loader_soap_retries", "SOAP retries scheduled with backoff", ["operation"])

for phase in ("connect", "initial", "incremental"):
    for outcome in ("success", "error"):
        RUNS.labels(phase, outcome)
for outcome in ("created", "unchanged", "skipped", "failed"):
    COMPANIES.labels(outcome)


@contextmanager
def observe_run(phase: str):
    started = monotonic()
    try:
        yield
    except Exception:
        RUNS.labels(phase, "error").inc()
        raise
    else:
        RUNS.labels(phase, "success").inc()
        LAST_SUCCESS.labels(phase).set_to_current_time()
    finally:
        RUN_DURATION.labels(phase).observe(monotonic() - started)
