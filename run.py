"""Единая точка запуска сайта и Discord-бота."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    env = os.environ.copy()
    env["LONDO_RELOAD"] = "0"
    processes = [
        subprocess.Popen([sys.executable, str(project_dir / "run_web.py")], cwd=project_dir, env=env),
        subprocess.Popen([sys.executable, str(project_dir / "run_bot.py")], cwd=project_dir, env=env),
    ]

    def stop_processes(signum, _frame) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, stop_processes)
    signal.signal(signal.SIGTERM, stop_processes)

    try:
        while True:
            for process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    stop_processes(signal.SIGTERM, None)
            signal.pause()
    finally:
        stop_processes(signal.SIGTERM, None)


if __name__ == "__main__":
    main()