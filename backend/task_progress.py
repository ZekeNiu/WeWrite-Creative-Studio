"""Only completed work advances a job's visible progress clock."""
from contextlib import asynccontextmanager
from . import store


def completed(job_id, label):
    if job_id:
        store.update_job(job_id, last_completed_at=store.now(), last_completed_label=label)


@asynccontextmanager
async def request(job_id, label, completed_label):
    if job_id:
        store.update_job(job_id, active_request_started_at=store.now(), active_request_label=label)
    try:
        yield
    except BaseException:
        if job_id:
            store.update_job(job_id, active_request_started_at=None, active_request_label=None)
        raise
    else:
        if job_id:
            patch=dict(active_request_started_at=None, active_request_label=None)
            if completed_label:
                patch.update(last_completed_at=store.now(), last_completed_label=completed_label)
            store.update_job(job_id, **patch)
