"""Finite systemd datagram adapter. No polling, subprocesses, bind or unlink."""
from contextlib import contextmanager
import os
import socket

from django.core.exceptions import ImproperlyConfigured

from .email_execution import drain_outbox

WAKE_MESSAGE = b"library-email-wake-v1"


@contextmanager
def inherited_socket(path):
    """Take ownership of exactly fd 3, leaving systemd's copy alive on exit."""
    channel = None
    try:
        try:
            pid = int(os.environ.get("LISTEN_PID", "0"))
            count = int(os.environ.get("LISTEN_FDS", "0"))
        except ValueError:
            raise ImproperlyConfigured("Invalid socket activation environment.") from None
        if (pid != os.getpid() or count != 1 or not path or not os.path.isabs(path)
                or not hasattr(socket, "AF_UNIX")):
            raise ImproperlyConfigured("Email receiver requires one inherited systemd Unix datagram socket.")
        for name in ("LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES", "LISTEN_PIDFDID"):
            os.environ.pop(name, None)
        os.set_inheritable(3, False)
        channel = socket.socket(fileno=3)
        if (channel.family != socket.AF_UNIX
                or channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_DGRAM
                or os.fsdecode(channel.getsockname()) != path):
            raise ImproperlyConfigured("Unexpected email activation socket type or path.")
        channel.setblocking(False)
        yield channel
    finally:
        if channel is not None:
            # Never shutdown() or unlink(): systemd retains this same socket.
            channel.close()


def receive_and_process(channel, *, limit=100, max_batches=5, max_signals=256,
                        recover_if_idle=False):
    if not 1 <= max_signals <= 4096 or not 1 <= limit <= 10000 or not 1 <= max_batches <= 100:
        raise ValueError("Invalid receiver bounds.")
    received = valid = 0
    for _ in range(max_signals):
        try:
            # The extra byte rejects oversized messages sharing the valid prefix.
            message = channel.recv(len(WAKE_MESSAGE) + 1)
        except BlockingIOError:
            break
        received += 1
        valid += message == WAKE_MESSAGE
    result = {"signals": received, "valid": valid, "invalid": received - valid}
    if valid or (received == 0 and recover_if_idle):
        result["worker"] = drain_outbox(limit=limit, max_batches=max_batches)
    # Do not consume after delivery: arrivals during work/exit remain queued and
    # systemd reactivates this same service. A timer covers lost/busy signals,
    # remaining rows at the batch cap, future retries and expired leases.
    return result
