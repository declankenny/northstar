"""The jobs the in-app scheduler runs. A job exists because it is listed here (see northstar/scheduler.py)."""

from northstar import rate_fetch
from northstar.scheduler import Job

REGISTRY: tuple[Job, ...] = (
    Job(rate_fetch.JOB, rate_fetch.run, rate_fetch.TIME_PROPERTY),
)
