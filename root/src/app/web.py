from flask import Blueprint


web = Blueprint("web", __name__)


@web.get("/")
def home():
    return "<p>Hello, World!</p>"
