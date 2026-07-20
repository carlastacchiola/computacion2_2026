from __future__ import annotations

import signal
import time

from src.procfs import list_pids, read_process_status


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


def collect_signals(limit: int | None = 30) -> list[dict]:
    result = []

    for pid in list_pids():
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

        if limit is not None and len(result) >= limit:
            break

    return result


def run_signals_analyzer(output_queue, stop_event, interval_seconds=10.0):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not stop_event.is_set():
        output_queue.put({
            "type": "senales",
            "timestamp": time.time(),
            "processes": collect_signals(),
        })
        stop_event.wait(interval_seconds)