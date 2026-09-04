import os
import sys
import tempfile
from pathlib import Path

# Isolated SQLite DB + no background scheduler for the test session.
_tmp = tempfile.mkdtemp(prefix="rankpilot-test-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["EMAIL_BACKEND"] = "file"
os.environ["OUTBOX_DIR"] = f"{_tmp}/outbox"
os.environ["MEDIA_DIR"] = f"{_tmp}/media"
os.environ["AI_PROVIDER"] = "none"
os.environ["SERP_PROVIDER"] = "none"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
