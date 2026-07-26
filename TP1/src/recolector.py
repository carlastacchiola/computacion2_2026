from __future__ import annotations

import time

from src.procfs import list_pids
from src.senales import ignorar_senales_de_control


def run_collector(shared_pids, stop_event, interval_seconds: float = 1.0) -> None:
    ignorar_senales_de_control()

    while not stop_event.is_set():
        pids = list_pids()
        shared_pids[:] = pids

        stop_event.wait(interval_seconds)