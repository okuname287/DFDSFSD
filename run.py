"""Единая точка запуска сайта и Discord-бота."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    env = os.environ.copy()
    env["LONDO_RELOAD"] = "0"
    web_process = subprocess.Popen(
        [sys.executable, str(project_dir / "run_web.py")], cwd=project_dir, env=env
    )
    bot_process = subprocess.Popen(
        [sys.executable, str(project_dir / "run_bot.py")], cwd=project_dir, env=env
    )
    processes = [web_process, bot_process]

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
            web_exit_code = web_process.poll()
            if web_exit_code is not None:
                print(f"Web process stopped with exit code {web_exit_code}", flush=True)
                stop_processes(signal.SIGTERM, None)

            bot_exit_code = bot_process.poll()
            if bot_exit_code is not None:
                print(
                    f"Bot process stopped with exit code {bot_exit_code}; restarting",
                    flush=True,
                )
                bot_process = subprocess.Popen(
                    [sys.executable, str(project_dir / "run_bot.py")],
                    cwd=project_dir,
                    env=env,
                )
                processes[1] = bot_process
            time.sleep(1)
    finally:
        stop_processes(signal.SIGTERM, None)


if __name__ == "__main__":
    main()