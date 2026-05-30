"""Expert retrieval: BM25 + bi-encoder + PPR fusion over Ludzie Nauki profiles."""

from .corpus import ScientistDocument, build_scientist_corpus, load_corpus_jsonl, save_corpus_jsonl
from .fusion import FusionWeights, fuse_scores, minmax_normalize
from .modes import SearchMode
from .pipeline import QueryResult, build_artifacts, query_experts

__all__ = [
    "FusionWeights",
    "QueryResult",
    "ScientistDocument",
    "SearchMode",
    "build_artifacts",
    "build_scientist_corpus",
    "fuse_scores",
    "load_corpus_jsonl",
    "minmax_normalize",
    "query_experts",
    "save_corpus_jsonl",
]
