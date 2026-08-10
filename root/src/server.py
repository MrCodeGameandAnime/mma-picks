from flask import Flask

from .app.config import load_config
from .app.db import initialize_database
from .app.api_v1 import api_v1
from .app.web import web


def create_app(config=None) -> Flask:
    config = config or load_config()
    initialize_database(config.database_path)
    flask_app = Flask("hello")
    flask_app.config["DATABASE_PATH"] = str(config.database_path)
    flask_app.register_blueprint(web)
    flask_app.register_blueprint(api_v1)

    return flask_app
