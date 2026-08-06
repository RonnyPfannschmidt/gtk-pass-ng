"""Marshalling results from worker threads back onto the UI thread."""

import logging
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from gtkpass._gi import GLib

logger = logging.getLogger(__name__)


def on_ui_thread(
    future: Future,
    on_success: Callable[[Any], None],
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Deliver a future's outcome to the UI thread.

    ``Future.add_done_callback`` runs on the worker thread, and touching a
    widget from there corrupts GTK's state in ways that surface much later, so
    the callback only schedules an idle handler.  This is the one place that
    crossing is done.
    """

    def deliver(completed: Future) -> None:
        try:
            result = completed.result()
        except BaseException as error:  # noqa: BLE001 - reported, not swallowed
            GLib.idle_add(_once, on_error or _log_error, error)
        else:
            GLib.idle_add(_once, on_success, result)

    future.add_done_callback(deliver)


def _once(callback: Callable[[Any], None], value: Any) -> bool:
    """Run an idle callback exactly once.

    Returning GLib.SOURCE_REMOVE is not optional: a truthy return re-arms the
    source and the callback fires forever.
    """
    callback(value)
    return GLib.SOURCE_REMOVE


def _log_error(error: BaseException) -> None:
    logger.error("Background task failed: %s", error)
