import os


def list_pids(proc_root="/proc"):
    pids = []

    for entry in os.listdir(proc_root):
        if entry.isdigit():
            pids.append(int(entry))

    return sorted(pids)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            return file.read()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def parse_status(text):
    data = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        data[key] = value.strip()

    return data


def read_process_status(pid, proc_root="/proc"):
    path = os.path.join(proc_root, str(pid), "status")
    text = read_text(path)

    if text is None:
        return None

    return parse_status(text)


def get_process_summary(pid):
    status = read_process_status(pid)

    if status is None:
        return None

    return {
        "pid": pid,
        "name": status.get("Name", ""),
        "state": status.get("State", ""),
        "ppid": status.get("PPid", ""),
        "threads": status.get("Threads", ""),
        "vmrss": status.get("VmRSS", "0 kB"),
    }


def list_process_summaries(limit=30):
    processes = []

    for pid in list_pids():
        summary = get_process_summary(pid)

        if summary is None:
            continue

        processes.append(summary)

        if len(processes) >= limit:
            break

    return processes