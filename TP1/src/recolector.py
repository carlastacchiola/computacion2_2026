from __future__ import annotations

import signal
import time

from src.procfs import list_pids


def run_collector(shared_pids, stop_event, interval_seconds: float = 1.0) -> None:
   
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not stop_event.is_set():
        pids = list_pids()
        shared_pids[:] = pids

        stop_event.wait(interval_seconds)