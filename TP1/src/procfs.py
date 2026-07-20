from __future__ import annotations

import os
from dataclasses import dataclass


PROC_ROOT = "/proc"


@dataclass
class ProcessSummary:
    pid: int
    name: str
    command: str
    state: str
    ppid: int | None
    threads: int | None
    vmrss_kb: int | None
    utime: int | None
    stime: int | None
    cpu_percent: float | None = None


def list_pids(proc_root: str = PROC_ROOT) -> list[int]:
    pids: list[int] = []

    for entry in os.listdir(proc_root):
        if entry.isdigit():
            pids.append(int(entry))

    return sorted(pids)


def read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            return file.read()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def parse_status(text: str) -> dict[str, str]:
    data: dict[str, str] = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        data[key] = value.strip()

    return data


def parse_kb(value: str | None) -> int | None:
    if not value:
        return None

    parts = value.split()
    if not parts:
        return None

    try:
        return int(parts[0])
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def read_cmdline(pid: int, proc_root: str = PROC_ROOT) -> str:
    text = read_text(os.path.join(proc_root, str(pid), "cmdline"))
    if not text:
        return ""

    command = text.replace("\x00", " ").strip()
    return command


def parse_stat(text: str) -> dict[str, int | str] | None:
    close_paren = text.rfind(")")
    open_paren = text.find("(")

    if open_paren == -1 or close_paren == -1 or close_paren < open_paren:
        return None

    pid_text = text[:open_paren].strip()
    comm = text[open_paren + 1 : close_paren]
    fields = text[close_paren + 2 :].split()

    if len(fields) < 22:
        return None

    try:
        return {
            "pid": int(pid_text),
             "comm": comm,
            "state": fields[0],
            "ppid": int(fields[1]),
            "minflt": int(fields[7]),
            "cminflt": int(fields[8]),
            "majflt": int(fields[9]),
            "cmajflt": int(fields[10]),
            "utime": int(fields[11]),
            "stime": int(fields[12]),
        }
    except ValueError:
        return None


def read_process_stat(pid: int, proc_root: str = PROC_ROOT) -> dict[str, int | str] | None:
    text = read_text(os.path.join(proc_root, str(pid), "stat"))
    if text is None:
        return None

    return parse_stat(text)


def read_process_summary(pid: int, proc_root: str = PROC_ROOT) -> ProcessSummary | None:
    status_text = read_text(os.path.join(proc_root, str(pid), "status"))
    if status_text is None:
        return None

    status = parse_status(status_text)
    stat = read_process_stat(pid, proc_root)
    command = read_cmdline(pid, proc_root)

    return ProcessSummary(
        pid=pid,
        name=status.get("Name", ""),
        command=command,
        state=str(stat.get("state")) if stat else status.get("State", ""),
        ppid=int(stat["ppid"]) if stat and isinstance(stat.get("ppid"), int) else parse_int(status.get("PPid")),
        threads=int(stat["num_threads"])
        if stat and isinstance(stat.get("num_threads"), int)
        else parse_int(status.get("Threads")),
        vmrss_kb=parse_kb(status.get("VmRSS")),
        utime=int(stat["utime"]) if stat and isinstance(stat.get("utime"), int) else None,
        stime=int(stat["stime"]) if stat and isinstance(stat.get("stime"), int) else None,
    )


def list_process_summaries(limit: int | None = None) -> list[ProcessSummary]:
    summaries: list[ProcessSummary] = []

    for pid in list_pids():
        summary = read_process_summary(pid)
        if summary is None:
            continue

        summaries.append(summary)

        if limit is not None and len(summaries) >= limit:
            break

    return summaries


def cpu_ticks(summary: ProcessSummary) -> int | None:
    if summary.utime is None or summary.stime is None:
        return None

    return summary.utime + summary.stime


def cpu_tick_snapshot() -> dict[int, int]:
    snapshot: dict[int, int] = {}

    for summary in list_process_summaries():
        ticks = cpu_ticks(summary)
        if ticks is None:
            continue

        snapshot[summary.pid] = ticks

    return snapshot


def calculate_cpu_percent(
    old_ticks: int,
    new_ticks: int,
    elapsed_seconds: float,
    clock_ticks: int | None = None,
) -> float:
    if elapsed_seconds <= 0:
        return 0.0

    if clock_ticks is None:
        clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

    delta_ticks = max(0, new_ticks - old_ticks)
    cpu_seconds = delta_ticks / clock_ticks
    return (cpu_seconds / elapsed_seconds) * 100.0

def read_process_status(pid: int, proc_root: str = PROC_ROOT) -> dict[str, str] | None:
    status_text = read_text(os.path.join(proc_root, str(pid), "status"))
    if status_text is None:
        return None

    return parse_status(status_text)