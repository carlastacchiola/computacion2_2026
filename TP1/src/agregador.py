from __future__ import annotations

import signal
from queue import Empty


def run_aggregator(input_queue, snapshot, stop_event):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not stop_event.is_set():
        try:
            message = input_queue.get(timeout=0.5)
        except Empty:
            continue

        message_type = message.get("type")
        if message_type is None:
            continue

        snapshot[message_type] = {
            "timestamp": message.get("timestamp"),
            "data": message,
        }