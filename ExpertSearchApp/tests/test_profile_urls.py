from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api.profile_urls import build_ludzie_profile_url  # noqa: E402


class TestProfileUrls(unittest.TestCase):
    def test_full_slug(self) -> None:
        url = build_ludzie_profile_url(
            "veX4uEZvEf4",
            given_name="Przemysław",
            surname="Buczkowski",
        )
        self.assertEqual(
            url,
            "https://ludzie.nauka.gov.pl/ln/profiles/przemys%C5%82aw.buczkowski.veX4uEZvEf4",
        )

    def test_compound_surname_spaces_removed(self) -> None:
        url = build_ludzie_profile_url(
            "060hSMNoknU",
            given_name="Magdalena",
            surname="Żak de Carvalho",
        )
        self.assertEqual(
            url,
            "https://ludzie.nauka.gov.pl/ln/profiles/magdalena.%C5%BCakdecarvalho.060hSMNoknU",
        )

    def test_id_only_when_names_missing(self) -> None:
        url = build_ludzie_profile_url("abc123")
        self.assertEqual(url, "https://ludzie.nauka.gov.pl/ln/profiles/abc123")


if __name__ == "__main__":
    unittest.main()
