"""Build public Ludzie Nauki profile URLs (ln/profiles slug format)."""

from __future__ import annotations

from urllib.parse import quote

LUDZIE_PROFILE_BASE = "https://ludzie.nauka.gov.pl/ln/profiles/"


def _given_slug(value: str | None) -> str:
    """Lowercase given name; keeps Polish diacritics (encoded in URL)."""
    return str(value or "").strip().lower()


def _surname_slug(value: str | None) -> str:
    """Lowercase surname with internal spaces removed (e.g. Żak de Carvalho → żakdecarvalho)."""
    raw = str(value or "").strip().lower()
    return "".join(raw.split())


def build_ludzie_profile_url(
    profile_id: str,
    *,
    given_name: str | None = None,
    surname: str | None = None,
) -> str:
    """
    Canonical pattern: https://ludzie.nauka.gov.pl/ln/profiles/{given}.{surname}.{id}
    Examples: przemysław.buczkowski.veX4uEZvEf4; magdalena.żakdecarvalho.060hSMNoknU
    """
    segments: list[str] = []
    first = _given_slug(given_name)
    last = _surname_slug(surname)
    if first:
        segments.append(first)
    if last:
        segments.append(last)
    segments.append(str(profile_id).strip())
    slug = ".".join(segments)
    return LUDZIE_PROFILE_BASE + quote(slug, safe=".")
