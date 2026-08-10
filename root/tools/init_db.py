from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.app.config import load_config
from src.app.db import initialize_database


if __name__ == "__main__":
    config = load_config()
    initialize_database(config.database_path)
    print(f"Initialized database at {config.database_path}")
