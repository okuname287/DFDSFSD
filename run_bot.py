"""Запуск Discord-бота."""
import os

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from bot.main import run_bot

if __name__ == "__main__":
    run_bot()
