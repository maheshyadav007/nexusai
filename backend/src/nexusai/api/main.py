import uvicorn

from nexusai.api.app import create_app
from nexusai.kernel.config import load_config


def run() -> None:
    config = load_config()
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    run()
