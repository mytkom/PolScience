"""Search mode selector: which text fields feed BM25 and bi-encoder indexes."""

from __future__ import annotations

from enum import StrEnum


class SearchMode(StrEnum):
    """Which text fields drive BM25 / bi-encoder recall."""

    PUBLICATIONS = "publications"
    """Publication titles plus profile keywords and taxonomy (specific topics)."""

    PROFILE = "profile"
    """Profile keywords, specialties, domains, institutions, about-me (exploratory)."""

    @classmethod
    def parse(cls, value: str) -> SearchMode:
        normalized = value.strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in cls)
            raise ValueError(f"Unknown search mode {value!r}; use one of: {allowed}") from exc

    @classmethod
    def parse_build_modes(cls, value: str) -> list[SearchMode]:
        normalized = value.strip().lower()
        if normalized in ("all", "both"):
            return [cls.PUBLICATIONS, cls.PROFILE]
        return [cls.parse(normalized)]
