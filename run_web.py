"""Запуск веб-сайта."""
import uvicorn
import os

from shared.config import get_config

if __name__ == "__main__":
    config = get_config()
    uvicorn.run(
        "web.main:app",
        host=config["web"]["host"],
        port=config["web"]["port"],
        reload=os.environ.get("LONDO_RELOAD", "1").lower() in {"1", "true", "yes", "on"},
    )
