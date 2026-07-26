from __future__ import annotations

import os
import time

from src.procfs import read_process_status
from src.senales import ignorar_senales_de_control


def infer_fd_type(target: str) -> str:
    if target.startswith("socket:"):
        return "socket"
    if target.startswith("pipe:"):
        return "pipe"
    if target.startswith("/dev/pts") or target.startswith("/dev/tty"):
        return "tty"
    if target.startswith("anon_inode:"):
        return "anon_inode"
    if target.startswith("/"):
        return "file"
    return "other"


def collect_fds(pids: list[int], limit: int | None = 30, per_process_limit: int = 8) -> list[dict]:
    target_pids = pids[:limit] if limit is not None else pids
    processes = []

    for pid in target_pids:
        status = read_process_status(pid)
        if status is None:
            continue

        fd_dir = f"/proc/{pid}/fd"

        try:
            fd_names = sorted(os.listdir(fd_dir), key=lambda x: int(x))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue

        fds = []
        for fd_name in fd_names[:per_process_limit]:
            path = os.path.join(fd_dir, fd_name)
            try:
                target = os.readlink(path)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue

            fds.append({"fd": fd_name, "target": target, "type": infer_fd_type(target)})

        processes.append({"pid": pid, "name": status.get("Name", ""), "fds": fds})

    return processes


def run_fds_analyzer(shared_pids, output_queue, stop_event, interval_seconds=5.0):
    ignorar_senales_de_control()

    while not stop_event.is_set():
        pids = list(shared_pids)
        output_queue.put({
            "type": "fds",
            "timestamp": time.time(),
            "processes": collect_fds(pids),
        })
        stop_event.wait(interval_seconds)