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

    def test_the_capability_query_is_not_held_up(self, blocked):
        """Reading what a backend can sync must never wait for what it is doing.

        The sync action consults it on the UI thread every time the backends
        change, and it answers out of state fixed when the backend was built.
        Behind the same lock as the operations, it would be the window waiting
        on a decrypt to find out whether a button should be grey.
        """
        manager = BackendManager()
        manager.add_backend("blocked", blocked)
        manager.list_passwords_async("blocked")
        assert blocked.started.wait(PATIENCE_SECONDS), "the task never started"

        started = time.monotonic()
        manager.sync_capabilities()
        elapsed = time.monotonic() - started

        assert elapsed < PATIENCE_SECONDS

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


class OverlapRecordingBackend(DemoBackend):
    """Notices whether two calls were ever inside it at once."""

    def __init__(self) -> None:
        super().__init__(demo_data=[])
        self.overlapped = False
        self._inside = 0
        # Guards the counter only. What is under test is the lock around the
        # backend, so this one must not be it.
        self._counter = threading.Lock()

    def _occupy(self) -> None:
        with self._counter:
            self._inside += 1
            self.overlapped = self.overlapped or self._inside > 1
        # Long enough that four workers starting together are inside at once.
        time.sleep(0.05)
        with self._counter:
            self._inside -= 1

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        self._occupy()
        return []

    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        self._occupy()


class RendezvousBackend(DemoBackend):
    """Listing waits for a second caller to arrive somewhere else.

    A barrier rather than a sleep: it proves two backends really did run at the
    same time instead of merely finishing quickly.
    """

    def __init__(self, barrier: threading.Barrier) -> None:
        super().__init__(demo_data=[])
        self.barrier = barrier

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        self.barrier.wait()
        return []


class TestOneBackendIsUsedOneCallAtATime:
    """Four workers share every backend, and no backend is written for that.

    The Direct and Pass backends share a GitStore, so a commit landing during a
    `pull --rebase` collides on .git/index.lock. The Secret Service backend
    shares one D-Bus connection between every call. A decrypt reading a .gpg
    file while git rewrites the tree can read half of another revision.
    """

    def test_two_calls_to_one_backend_do_not_overlap(self):
        manager = BackendManager()
        backend = OverlapRecordingBackend()
        manager.add_backend("one", backend)

        futures = [manager.list_passwords_async("one") for _ in range(4)]
        for future in futures:
            future.result(PATIENCE_SECONDS)
        manager.shutdown()

        assert not backend.overlapped

    def test_a_read_and_a_write_do_not_overlap(self):
        """The dangerous pair: the git commit a save makes, during a listing."""
        manager = BackendManager()
        backend = OverlapRecordingBackend()
        manager.add_backend("one", backend)

        futures = [
            manager.list_passwords_async("one"),
            manager.edit_password_async("one", "entry", "secret\n"),
            manager.list_passwords_async("one"),
            manager.edit_password_async("one", "other", "secret\n"),
        ]
        for future in futures:
            future.result(PATIENCE_SECONDS)
        manager.shutdown()

        assert not backend.overlapped

    def test_different_backends_still_run_at_the_same_time(self):
        """One lock per backend, not one for the manager.

        A store on a slow mount must not hold up an unrelated one, and the
        window lists every configured backend at once.
        """
        barrier = threading.Barrier(2, timeout=PATIENCE_SECONDS)
        manager = BackendManager()
        manager.add_backend("one", RendezvousBackend(barrier))
        manager.add_backend("two", RendezvousBackend(barrier))

        futures = [
            manager.list_passwords_async("one"),
            manager.list_passwords_async("two"),
        ]
        try:
            for future in futures:
                # BrokenBarrierError here means they were serialized against
                # each other and neither could reach the meeting point.
                future.result(PATIENCE_SECONDS * 2)
        finally:
            manager.shutdown()
