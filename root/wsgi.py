"""WSGI entry point for hosts that provide a production WSGI server."""

from src.server import create_app


app = create_app()
