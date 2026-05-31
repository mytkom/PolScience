"""API configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = _REPO_ROOT / "data" / "LudzieNaukiDumpDB" / "new_prof_search.sqlite"
DEFAULT_ARTIFACTS = _REPO_ROOT / "data" / "retrieval_artifacts"
MAX_TOP_K = 5000


@dataclass(frozen=True, slots=True)
class ApiSettings:
    db_path: Path
    artifacts_dir: Path
    eager_load: bool

    def validate_paths(self) -> tuple[bool, bool]:
        return self.db_path.is_file(), self.artifacts_dir.is_dir()


def load_settings() -> ApiSettings:
    db_raw = os.environ.get("POLSCIENCE_DB_PATH", str(DEFAULT_DB))
    artifacts_raw = os.environ.get("POLSCIENCE_ARTIFACTS_DIR", str(DEFAULT_ARTIFACTS))
    eager = os.environ.get("POLSCIENCE_EAGER_LOAD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return ApiSettings(
        db_path=Path(db_raw).expanduser().resolve(),
        artifacts_dir=Path(artifacts_raw).expanduser().resolve(),
        eager_load=eager,
    )
