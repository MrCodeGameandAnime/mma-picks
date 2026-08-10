import sys


def main(argv=None, app_factory=None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments != ["run"]:
        print("Usage: python main.py run")
        return 2

    if app_factory is None:
        from src.server import create_app

        app_factory = create_app

    app = app_factory()
    app.run(host="127.0.0.1", port=5000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
