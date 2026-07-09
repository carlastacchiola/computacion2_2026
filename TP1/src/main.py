from procfs import list_process_summaries


def main():
    processes = list_process_summaries(limit=30)

    print(f"{'PID':>8} {'PPID':>8} {'TH':>4} {'RSS':>12} {'STATE':<20} NAME")
    print("-" * 80)

    for proc in processes:
        print(
            f"{proc['pid']:>8} "
            f"{proc['ppid']:>8} "
            f"{proc['threads']:>4} "
            f"{proc['vmrss']:>12} "
            f"{proc['state']:<20} "
            f"{proc['name']}"
        )


if __name__ == "__main__":
    main()