"""Tell a deliberate owner stop apart from any other cancellation.

Socket handlers answer through their return value (the Socket.IO ack), so a handler
the owner stopped must still return its "stopped" reply or the renderer waits for its
RPC timeout. Every other cancellation (loop/server shutdown, an outer timeout, a
caller cancelling the handler) must propagate. Code that stops a handler task calls
``request_stop``; the handler's ``except CancelledError`` calls ``acknowledge_stop``
and returns its reply only when that is True, re-raising otherwise.
"""

import asyncio
import weakref

_requested = weakref.WeakKeyDictionary()


def request_stop(task):
    """Cancel ``task`` as a deliberate stop its handler may acknowledge."""
    if task.cancel():
        _requested[task] = _requested.get(task, 0) + 1
        return True
    return False


def acknowledge_stop(task=None):
    """True when every pending cancellation of ``task`` was a deliberate stop.

    Consumes those stops (``Task.uncancel``) so the handler may return normally; when
    another cancellation is also pending the task stays cancelled and the caller must
    re-raise."""
    task = task or asyncio.current_task()
    stops = _requested.pop(task, 0) if task is not None else 0
    if not stops:
        return False
    remaining = task.cancelling()
    for _ in range(min(stops, remaining)):
        remaining = task.uncancel()
    return remaining == 0
