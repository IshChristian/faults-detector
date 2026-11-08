import fakeredis
from rq import SimpleWorker

from app.worker.jobs import ping
from app.worker.queues import get_queue


def test_ping_job_runs_on_default_queue():
    conn = fakeredis.FakeRedis()
    q = get_queue("default", connection=conn)
    job = q.enqueue(ping, "x")
    SimpleWorker([q], connection=conn).work(burst=True)
    job.refresh()
    assert job.is_finished and job.return_value() == "pong:x"


def test_sessions_queue_is_separate():
    conn = fakeredis.FakeRedis()
    sessions = get_queue("sessions", connection=conn)
    job = sessions.enqueue(ping, "long")
    SimpleWorker([get_queue("default", connection=conn)], connection=conn).work(burst=True)
    job.refresh()
    assert job.get_status() == "queued"
    SimpleWorker([sessions], connection=conn).work(burst=True)
    job.refresh()
    assert job.return_value() == "pong:long"
