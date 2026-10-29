import threading
from concurrent.futures import ThreadPoolExecutor

from django.db import connection


def race(calls):
    """Start every call at the same moment, each on its own connection, and return each outcome."""
    barrier = threading.Barrier(len(calls))

    def run(call):
        try:
            barrier.wait()
            return call()
        except Exception as exc:
            return exc
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def outcome(result) -> str:
    return type(result).__name__ if isinstance(result, Exception) else 'ok'
