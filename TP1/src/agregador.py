from __future__ import annotations

from queue import Empty

from src.senales import ignorar_senales_de_control


def run_aggregator(input_queue, snapshot, stop_event):
    ignorar_senales_de_control()

    while not stop_event.is_set():
        try:
            message = input_queue.get(timeout=0.5)
        except Empty:
            continue

        message_type = message.get("type")
        if message_type is None:
            continue

        snapshot[message_type] = message