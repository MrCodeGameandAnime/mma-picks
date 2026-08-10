from pathlib import Path

from flask import Flask

from .app.config import load_config
from .app.db import initialize_database
from .app.api_v1 import api_v1
from .app.web import web


APP_DIR = Path(__file__).resolve().parent / "app"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


def create_app(config=None) -> Flask:
    config = config or load_config()
    initialize_database(config.database_path)
    flask_app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(STATIC_DIR),
    )
    flask_app.config["DATABASE_PATH"] = str(config.database_path)
    flask_app.config["TEMPLATES_DIR"] = str(TEMPLATES_DIR)
    flask_app.config["STATIC_DIR"] = str(STATIC_DIR)
    flask_app.register_blueprint(web)
    flask_app.register_blueprint(api_v1)

    return flask_app
