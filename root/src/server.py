from flask import Flask

from .app.config import load_config
from .app.db import initialize_database


def create_app() -> Flask:
    config = load_config()
    initialize_database(config.database_path)
    flask_app = Flask("hello")
    flask_app.config["DATABASE_PATH"] = str(config.database_path)

    @flask_app.get("/")
    def hello_world():
        return "<p>Hello, World!</p>"

    return flask_app


app = create_app()
