import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from kith project root before any test
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)
