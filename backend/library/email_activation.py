"""Best-effort local OS wake signal. The outbox remains the durable queue.

Phase 2 contract (NOT installed or operational by this module):
* On a host supporting Unix datagram sockets, provision an absolute socket path
  in a protected directory. Only the application identity may write to it.
* The OS-managed receiver must consume `library-email-wake-v1`, coalesce signals,
  and activate one fixed process_email_outbox service. It must not interpret
  datagrams as shell commands. No general sudo/systemctl permission is needed.
* Use receive_email_wake in one fixed socket-activated service: it consumes the
  inherited socket and executes the bounded worker in the SAME process. The
  process_email_outbox command remains the independent recovery entry point.
* Enable LIBRARY_EMAIL_WAKE_ENABLED and LIBRARY_EMAIL_WAKE_SOCKET only after
  verification. These settings do not enable enqueue, ownership or delivery.
* A separate boot/recovery timer must invoke the same bounded command for lost
  signals, the worker exit race, future retry times and expired leases. Signals
  are not durable. Successful sendto proves only local signal submission.
"""
import logging
import os
import socket
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)
_batch = ContextVar("library_email_wake_batch", default=None)


def wake_worker():
    if not getattr(settings, "LIBRARY_EMAIL_WAKE_ENABLED", False):
        return False
    try:
        path = getattr(settings, "LIBRARY_EMAIL_WAKE_SOCKET", "")
        if not path or not os.path.isabs(path) or not hasattr(socket, "AF_UNIX"):
            raise ValueError("Invalid local activation socket")
        # Fixed protocol, no shell, credentials, message bodies or arbitrary commands.
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
            channel.settimeout(0.1)
            channel.sendto(b"library-email-wake-v1", path)
        return True  # Signal accepted locally, NOT evidence of worker execution.
    except Exception:
        logger.warning("Library email wake failed; pending work requires recovery.")
        return False


@contextmanager
def coalesce_wakeups():
    """Share callbacks without inspecting Django internals or losing savepoint rules.

    Scheduler commits can happen inside this scope; signal once on exit. When an
    outer transaction is still open, its callbacks signal once after its commit.
    A partially completed scheduler also wakes its already committed work.
    """
    if _batch.get() is not None:
        yield
        return
    state = {"active": True, "ready": False, "sent": False}
    token = _batch.set(state)
    try:
        yield
    finally:
        _batch.reset(token)
        state["active"] = False
        if state["ready"] and not state["sent"]:
            state["sent"] = True
            wake_worker()


def wake_after_commit(*, using=None):
    if not getattr(settings, "LIBRARY_EMAIL_WAKE_ENABLED", False):
        return
    state = _batch.get()

    def committed():
        if state is None:
            wake_worker()
        elif not state["sent"]:
            state["ready"] = True
            if not state["active"]:
                state["sent"] = True
                wake_worker()

    transaction.on_commit(committed, using=using, robust=True)
