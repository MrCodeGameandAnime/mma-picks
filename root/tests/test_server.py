from pathlib import Path

from main import main
from src.app.config import AppConfig
from src.server import APP_DIR, STATIC_DIR, TEMPLATES_DIR, create_app


def test_app_factory_uses_a_temporary_database(tmp_path):
    database_path = tmp_path / "tracker.db"
    app = create_app(AppConfig(database_path=database_path))

    assert database_path.exists()
    assert app.config["DATABASE_PATH"] == str(database_path)
    assert Path(app.jinja_loader.searchpath[0]).resolve() == TEMPLATES_DIR.resolve()
    assert Path(app.static_folder).resolve() == STATIC_DIR.resolve()
    assert Path(app.config["TEMPLATES_DIR"]).resolve() == TEMPLATES_DIR.resolve()
    assert Path(app.config["STATIC_DIR"]).resolve() == STATIC_DIR.resolve()
    assert set(app.blueprints) == {"web", "api_v1"}

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert "Dashboard" in response.get_data(as_text=True)


def test_api_v1_blueprint_is_registered(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))

    response = app.test_client().get("/api/v1")
    static_response = app.test_client().get("/static/style.css")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "version": "v1"}
    assert static_response.status_code == 200
    assert "metric-grid" in static_response.get_data(as_text=True)


def test_invalid_cli_does_not_create_an_application():
    def unexpected_factory():
        raise AssertionError("invalid CLI input must not create the application")

    assert main(["invalid"], app_factory=unexpected_factory) == 2


def test_run_cli_still_delegates_to_the_application():
    calls = []

    class FakeApp:
        def run(self, **kwargs):
            calls.append(kwargs)

    assert main(["run"], app_factory=lambda: FakeApp()) == 0
    assert calls == [{"host": "127.0.0.1", "port": 5000}]
