"""RQ queues on Valkey.

default:  short jobs (alert delivery, clip export, retention).
sessions: long upload-processing jobs, served by its own single worker (concurrency 1),
          so a multi-hour session never delays alerts (V1 spec §4).
"""
from typing import Literal

import redis
from rq import Queue

from app.config import get_settings

QueueName = Literal["default", "sessions"]


def get_queue(name: QueueName, connection: redis.Redis | None = None) -> Queue:
    conn = connection or redis.Redis.from_url(get_settings().redis_url)
    return Queue(name, connection=conn)


def get_sessions_queue() -> Queue:
    """FastAPI dependency for the long-running sessions queue; tests override it."""
    return get_queue("sessions")
