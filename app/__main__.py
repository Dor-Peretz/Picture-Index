from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from app.paths import is_frozen, user_data_dir, web_dir

HOST = "127.0.0.1"
DEFAULT_PORT = 8766


def _setup_logging() -> None:
    log_file = user_data_dir() / "picture-index.log"
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not is_frozen():
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        logging.getLogger().addHandler(console)


def _free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    return start


def main() -> None:
    _setup_logging()
    from app.main import app

    port = int(os.environ.get("PICTURE_INDEX_PORT", _free_port()))
    url = f"http://{HOST}:{port}"
    logging.getLogger(__name__).info("Starting Picture Index at %s web=%s", url, web_dir())

    def open_browser() -> None:
        time.sleep(0.7)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    uvicorn.Server(config).run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Picture Index failed to start")
        if not is_frozen():
            raise
        sys.exit(1)
