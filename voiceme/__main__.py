"""Start the server with:  python -m voiceme"""

from __future__ import annotations

import logging

import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s: %(message)s")
    print(f"\n  VoiceMe -> http://{settings.host}:{settings.port}\n")
    uvicorn.run(
        "voiceme.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
