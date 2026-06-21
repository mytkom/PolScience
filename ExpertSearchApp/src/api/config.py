"""API configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MONOREPO_ROOT = _PROJECT_ROOT.parent
DEFAULT_DB = _MONOREPO_ROOT / "data" / "LudzieNaukiDumpDB" / "new_prof_search.sqlite"
DEFAULT_ARTIFACTS = _MONOREPO_ROOT / "data" / "retrieval_artifacts"
DEFAULT_GRAPHS = _MONOREPO_ROOT / "data" / "graphs"
MAX_TOP_K = 5000


@dataclass(frozen=True, slots=True)
class ApiSettings:
    db_path: Path
    artifacts_dir: Path
    graphs_dir: Path
    eager_load: bool

    def validate_paths(self) -> tuple[bool, bool, bool]:
        db_ok = self.db_path.is_file()
        artifacts_ok = self.artifacts_dir.is_dir()
        graphs_ok = self.graphs_dir.is_dir() and any(self.graphs_dir.glob("*.gexf"))
        return db_ok, artifacts_ok, graphs_ok


def load_settings() -> ApiSettings:
    db_raw = os.environ.get("POLSCIENCE_DB_PATH", str(DEFAULT_DB))
    artifacts_raw = os.environ.get("POLSCIENCE_ARTIFACTS_DIR", str(DEFAULT_ARTIFACTS))
    graphs_raw = os.environ.get("POLSCIENCE_GRAPHS_DIR", str(DEFAULT_GRAPHS))
    eager = os.environ.get("POLSCIENCE_EAGER_LOAD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return ApiSettings(
        db_path=Path(db_raw).expanduser().resolve(),
        artifacts_dir=Path(artifacts_raw).expanduser().resolve(),
        graphs_dir=Path(graphs_raw).expanduser().resolve(),
        eager_load=eager,
    )
