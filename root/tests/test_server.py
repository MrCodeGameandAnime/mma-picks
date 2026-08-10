from src.server import app


def test_root_route_is_available():
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "<p>Hello, World!</p>"
