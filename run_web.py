"""Запуск веб-сайта."""
import uvicorn

from shared.config import get_config

if __name__ == "__main__":
    config = get_config()
    uvicorn.run(
        "web.main:app",
        host=config["web"]["host"],
        port=config["web"]["port"],
        reload=True,
    )
