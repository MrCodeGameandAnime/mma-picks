import sys

from src.server import app


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "run":
        print("Usage: python main.py run")
        return 2

    app.run(host="127.0.0.1", port=5000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
