import uvicorn

from nexusai.api.app import create_app
from nexusai.kernel.config import load_config
from nexusai.kernel.logging import configure_logging


def run() -> None:
    configure_logging()
    config = load_config()
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    run()
