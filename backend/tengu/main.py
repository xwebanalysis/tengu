"""Process entry point."""

from __future__ import annotations

import argparse

import uvicorn

from .api import create_app
from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Tengu web quality auditor")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    cfg = Config.from_env()
    app = create_app(cfg)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port or cfg.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
