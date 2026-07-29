from __future__ import annotations

import signal
import time

from src.procfs import read_process_status
from src.senales import ignorar_senales_de_control


SIGNAL_NAMES = {
    num: name for name, num in signal.__dict__.items()
    if name.startswith("SIG") and "_" not in name and isinstance(num, signal.Signals)
}


def decode_signal_mask(hex_mask: str | None) -> list[str]:
    if not hex_mask:
        return []

    try:
        mask = int(hex_mask, 16)
    except ValueError:
        return []

    names = []
    for signum in range(1, 65):
        if mask & (1 << (signum - 1)):
            names.append(SIGNAL_NAMES.get(signum, f"SIG{signum}"))

    return names


def collect_signals(pids: list[int], limit: int | None = 30) -> list[dict]:
    target_pids = pids[:limit] if limit is not None else pids
    result = []

    for pid in target_pids:
        status = read_process_status(pid)
        if status is None:
            continue

        result.append({
            "pid": pid,
            "name": status.get("Name", ""),
            "sigblk": decode_signal_mask(status.get("SigBlk")),
            "sigign": decode_signal_mask(status.get("SigIgn")),
            "sigcgt": decode_signal_mask(status.get("SigCgt")),
            "sigpnd": decode_signal_mask(status.get("SigPnd")),
            "shdpnd": decode_signal_mask(status.get("ShdPnd")),
        })

    return result


def run_signals_analyzer(shared_pids, output_queue, stop_event, interval_value):
    ignorar_senales_de_control()

    while not stop_event.is_set():
        pids = list(shared_pids)
        output_queue.put({
            "type": "senales",
            "timestamp": time.time(),
            "processes": collect_signals(pids),
        })
        stop_event.wait(interval_value.value)