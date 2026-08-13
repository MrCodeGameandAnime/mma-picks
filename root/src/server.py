from pathlib import Path

from flask import Flask

from .app.config import load_config
from .app.db import initialize_database
from .app.api_v1 import api_v1
from .app.web import web
from .app.formatting import format_money
from .app.rapidapi import AllowAllApiAccessPolicy, LoggingApiUsageLogger


APP_DIR = Path(__file__).resolve().parent / "app"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


def create_app(config=None, *, api_access_policy=None, api_usage_logger=None) -> Flask:
    config = config or load_config()
    initialize_database(config.database_path)
    flask_app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(STATIC_DIR),
    )
    flask_app.config["DATABASE_PATH"] = str(config.database_path)
    flask_app.config["ODDS_API_KEY"] = config.odds_api_key
    flask_app.config["ODDS_API_SPORT_KEY"] = config.odds_api_sport_key
    flask_app.config["ODDS_API_REGIONS"] = config.odds_api_regions
    flask_app.config["ODDS_API_MARKETS"] = config.odds_api_markets
    flask_app.config["ODDS_API_TIMEOUT_SECONDS"] = config.odds_api_timeout_seconds
    flask_app.config["SERVER_HOST"] = config.server_host
    flask_app.config["SERVER_PORT"] = config.server_port
    flask_app.secret_key = config.flask_secret_key
    flask_app.config["TEMPLATES_DIR"] = str(TEMPLATES_DIR)
    flask_app.config["STATIC_DIR"] = str(STATIC_DIR)
    flask_app.jinja_env.filters["money"] = format_money
    flask_app.extensions["api_access_policy"] = api_access_policy or AllowAllApiAccessPolicy()
    flask_app.extensions["api_usage_logger"] = api_usage_logger or LoggingApiUsageLogger(
        flask_app.logger
    )
    flask_app.register_blueprint(web)
    flask_app.register_blueprint(api_v1)

    return flask_app
