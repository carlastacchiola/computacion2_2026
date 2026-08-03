from __future__ import annotations

import os
import time

from src.procfs import parse_status, read_text
from src.senales import ignorar_senales_de_control


def parse_thread_stat(text: str) -> dict | None:
    close = text.rfind(")")
    fields = text[close + 2:].split()
    if len(fields) < 15:
        return None
    return {"state": fields[0], "utime": int(fields[11]), "stime": int(fields[12])}


def _listar_tids(pid: int) -> list[int]:
    try:
        return sorted(int(x) for x in os.listdir(f"/proc/{pid}/task") if x.isdigit())
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return []


def _tomar_snapshot_de_ticks(pids: list[int], per_process_limit: int) -> dict[tuple[int, int], int]:
    snapshot: dict[tuple[int, int], int] = {}

    for pid in pids:
        for tid in _listar_tids(pid)[:per_process_limit]:
            stat_text = read_text(f"/proc/{pid}/task/{tid}/stat")
            parsed = parse_thread_stat(stat_text) if stat_text else None
            if parsed is not None:
                snapshot[(pid, tid)] = parsed["utime"] + parsed["stime"]

    return snapshot


def collect_threads(
    pids: list[int],
    limit: int | None = 30,
    per_process_limit: int = 8,
    sample_seconds: float = 0.3,
) -> list[dict]:
    target_pids = pids[:limit] if limit is not None else pids

    ticks_antes = _tomar_snapshot_de_ticks(target_pids, per_process_limit)
    inicio = time.monotonic()
    time.sleep(sample_seconds)
    transcurrido = time.monotonic() - inicio

    clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

    result = []

    for pid in target_pids:
        tids = _listar_tids(pid)
        if not tids:
            continue

        threads = []

        for tid in tids[:per_process_limit]:
            base = f"/proc/{pid}/task/{tid}"
            comm = read_text(f"{base}/comm")
            stat_text = read_text(f"{base}/stat")
            status_text = read_text(f"{base}/status")

            parsed_stat = parse_thread_stat(stat_text) if stat_text else None
            parsed_status = parse_status(status_text) if status_text else {}

            cpu_percent = None
            if parsed_stat is not None and transcurrido > 0:
                ticks_actuales = parsed_stat["utime"] + parsed_stat["stime"]
                anterior = ticks_antes.get((pid, tid))
                if anterior is not None:
                    delta = max(0, ticks_actuales - anterior)
                    cpu_percent = (delta / clock_ticks / transcurrido) * 100.0

            threads.append({
                "tid": tid,
                "name": comm.strip() if comm else "",
                "state": parsed_stat["state"] if parsed_stat else "",
                "cpu_percent": cpu_percent,
                "voluntary_ctxt_switches": parsed_status.get("voluntary_ctxt_switches"),
                "nonvoluntary_ctxt_switches": parsed_status.get("nonvoluntary_ctxt_switches"),
            })

        result.append({"pid": pid, "threads": threads})

    return result


def run_threads_analyzer(shared_pids, output_queue, stop_event, interval_value, verbose_value):
    ignorar_senales_de_control()

    while not stop_event.is_set():
        pids = list(shared_pids)
        per_process_limit = 40 if verbose_value.value else 8

        output_queue.put({
            "type": "threads",
            "timestamp": time.time(),
            "processes": collect_threads(pids, per_process_limit=per_process_limit),
        })
        stop_event.wait(max(0.0, interval_value.value - 0.3))