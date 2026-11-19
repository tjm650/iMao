"""Poll per-client nftables counters and persist monotonic session usage."""
import logging
from datetime import datetime, timezone

from backend.app.config import get_settings
from backend.app.netctl import NetctlError, read_counters, revoke_client
from database.database import connect

logger = logging.getLogger(__name__)


def account_active_sessions() -> int:
    settings = get_settings()
    with connect() as db:
        sessions = db.execute(
            """SELECT s.id, s.client_ip, s.bytes_up, s.bytes_down,
                      s.last_counter_up, s.last_counter_down,
                      v.id AS voucher_id, v.quota_bytes, v.used_bytes
               FROM sessions s JOIN vouchers v ON v.id = s.voucher_id
               WHERE s.status = 'active'"""
        ).fetchall()

    processed = 0
    for session in sessions:
        try:
            current_up, current_down = read_counters(session["client_ip"])
        except NetctlError:
            logger.exception("Could not read counters for session %s", session["id"])
            continue

        previous_up = session["last_counter_up"]
        previous_down = session["last_counter_down"]
        # A counter reset is treated as a new counter epoch; prior totals remain in SQLite.
        delta_up = current_up if previous_up is None or current_up < previous_up else current_up - previous_up
        delta_down = current_down if previous_down is None or current_down < previous_down else current_down - previous_down
        delta = delta_up + delta_down
        exhausted = False
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                """SELECT s.status, v.quota_bytes, v.used_bytes
                   FROM sessions s JOIN vouchers v ON v.id=s.voucher_id
                   WHERE s.id=?""", (session["id"],)
            ).fetchone()
            if not current or current["status"] != "active":
                db.rollback()
                continue
            new_used = min(current["quota_bytes"], current["used_bytes"] + delta)
            db.execute(
                """UPDATE sessions SET bytes_up=bytes_up+?, bytes_down=bytes_down+?,
                   last_counter_up=?, last_counter_down=? WHERE id=? AND status='active'""",
                (delta_up, delta_down, current_up, current_down, session["id"]),
            )
            db.execute("UPDATE vouchers SET used_bytes=? WHERE id=?", (new_used, session["voucher_id"]))
            if new_used >= current["quota_bytes"]:
                db.execute(
                    "UPDATE sessions SET status='limit_reached', ended_at=? WHERE id=? AND status='active'",
                    (datetime.now(timezone.utc).isoformat(), session["id"]),
                )
                exhausted = True
            db.commit()
        if exhausted:
            try:
                revoke_client(session["client_ip"])
            except NetctlError:
                logger.exception("Quota reached but network revocation failed for %s", session["client_ip"])
        processed += 1
    return processed
