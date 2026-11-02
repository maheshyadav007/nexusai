import uvicorn

from nexusai.api.app import create_app
from nexusai.kernel.config import load_config

KEEP_ALIVE_SECONDS = 75


def run() -> None:
    config = load_config()
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_config=None,
        # Longer than the frontend keeps an idle connection, so it never reuses one just closed.
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )


if __name__ == "__main__":
    run()
