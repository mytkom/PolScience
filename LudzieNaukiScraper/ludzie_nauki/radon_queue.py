from __future__ import annotations

import logging
import sqlite3

from ludzie_nauki import db
from ludzie_nauki.http_client import RadonClient

LOG = logging.getLogger(__name__)


def drain_radon_queue(
    conn: sqlite3.Connection,
    radon: RadonClient,
    *,
    max_items: int | None = None,
) -> int:
    """
    FIFO drain: one institution per iteration (commit-friendly for concurrent Pass 1).
    Returns number of queue rows successfully processed and removed.
    """
    done = 0
    while max_items is None or done < max_items:
        row = conn.execute(
            """
            SELECT institution_id, ludzie_name FROM radon_institution_queue
            ORDER BY enqueued_at ASC LIMIT 1
            """
        ).fetchone()
        if not row:
            break
        iid = str(row["institution_id"])
        name = str(row["ludzie_name"])
        payload = radon.portal_search_institution(iid)
        pl: dict | None = payload if isinstance(payload, dict) else None
        db.upsert_institution_from_radon_payload(conn, pl, ludzie_id=iid, ludzie_name=name)
        db.radon_queue_delete(conn, iid)
        done += 1
        LOG.debug("radon queue drained %s", iid)
    return done
