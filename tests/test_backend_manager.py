"""What the manager's thread pool does when a worker will not finish.

Every backend operation runs on that pool, and a decrypt sits on a pinentry
prompt that may never be answered. ``shutdown()`` is called from the UI thread
-- at quit, and on every settings change -- so a join on the pool turns one
stuck worker into an application that cannot be closed.

The subprocess deadlines are the other half of this; see
``TestPassCannotRunForever`` in test_pass_backend.py. Neither half is enough on
its own: a deadline still leaves the interface frozen until it expires, and a
non-blocking shutdown still leaves the interpreter joining the pool at exit.
"""

import threading
import time

import pytest

from gtkpass.backends import PasswordMetadata
from gtkpass.backends.demo import DemoBackend
from gtkpass.backends.manager import BackendManager

#: Long enough that a loaded machine does not fail this by being slow, and far
#: below what a join on a blocked worker would cost.
PATIENCE_SECONDS = 5.0


class BlockingBackend(DemoBackend):
    """A backend whose listing does not return until it is released.

    Stands in for a decrypt waiting on a passphrase prompt that nobody
    answers, which is the case that wedges a worker in practice.
    """

    def __init__(self) -> None:
        super().__init__(demo_data=[])
        self.started = threading.Event()
        self.release = threading.Event()

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        self.started.set()
        self.release.wait(60)
        return []


@pytest.fixture
def blocked():
    """A blocking backend that is always released again.

    The pool's threads are not daemons, so a worker left blocked outlives the
    test and the interpreter joins it at exit -- which looks like pytest
    hanging rather than like a test failing.
    """
    backend = BlockingBackend()
    yield backend
    backend.release.set()


class TestShutdownDoesNotWaitForAStuckWorker:
    def test_it_returns_while_a_task_is_still_running(self, blocked):
        manager = BackendManager()
        manager.add_backend("blocked", blocked)
        manager.list_passwords_async("blocked")
        assert blocked.started.wait(PATIENCE_SECONDS), "the task never started"

        started = time.monotonic()
        manager.shutdown()
        elapsed = time.monotonic() - started

        assert elapsed < PATIENCE_SECONDS, (
            "shutdown() waited for the worker; called from the UI thread, that "
            "is a frozen window"
        )

    def test_work_that_had_not_started_is_dropped(self, blocked):
        """Queued tasks are cancelled rather than run after the shutdown.

        Without this they keep the pool alive after the manager was replaced,
        working on behalf of backends the window has already forgotten.
        """
        manager = BackendManager()
        manager.add_backend("blocked", blocked)
        # Occupy every worker, so the last submission can only be queued.
        for _ in range(manager._executor._max_workers):
            manager.list_passwords_async("blocked")
        queued = manager.list_passwords_async("blocked")
        assert blocked.started.wait(PATIENCE_SECONDS), "nothing ever started"

        manager.shutdown()

        assert queued.cancelled()
