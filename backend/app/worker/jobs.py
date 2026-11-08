def ping(message: str) -> str:
    """Smoke-test job: proves a worker is consuming a queue."""
    return f"pong:{message}"
