from __future__ import annotations

from queue import Empty


def run_aggregator(input_queue, snapshot, stop_event):
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