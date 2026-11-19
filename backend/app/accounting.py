"""Poll per-client nftables counters and persist monotonic session usage."""
import logging
from datetime import datetime, timezone

from backend.app.config import get_settings
from backend.app.netctl import NetctlError, read_counters, revoke_client
from database.database import connect

logger = logging.getLogger(__name__)


def counter_delta(previous: int | None, current: int) -> int:
    """Return a non-negative delta, treating a lower counter as a reset epoch."""
    if current < 0 or (previous is not None and previous < 0):
        raise ValueError("Counter values cannot be negative")
    return current if previous is None or current < previous else current - previous


def expire_sessions() -> int:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        rows = db.execute(
            "SELECT id, client_ip FROM sessions WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        ).fetchall()
        db.execute(
            "UPDATE sessions SET status='expired', ended_at=? WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= ?",
            (now, now),
        )
    settings = get_settings()
    if settings.firewall_enabled and settings.firewall_backend == "nftables":
        for row in rows:
            try:
                revoke_client(row["client_ip"])
            except NetctlError:
                logger.exception("Could not revoke expired session %s", row["id"])
    return len(rows)


def account_active_sessions() -> int:
    settings = get_settings()
    if not settings.firewall_enabled or settings.firewall_backend != "nftables":
        return 0

    with connect() as db:
        sessions = db.execute(
            "SELECT id, client_ip, voucher_id FROM sessions WHERE status='active'"
        ).fetchall()

    processed = 0
    for session in sessions:
        try:
            current_up, current_down = read_counters(session["client_ip"])
        except NetctlError:
            logger.exception("Could not read counters for session %s", session["id"])
            continue

        exhausted = False
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                """SELECT s.status, s.last_counter_up, s.last_counter_down,
                          v.quota_bytes, v.used_bytes
                   FROM sessions s JOIN vouchers v ON v.id=s.voucher_id
                   WHERE s.id=?""", (session["id"],)
            ).fetchone()
            if not current or current["status"] != "active":
                db.rollback()
                continue

            # Recalculate inside the write transaction so multiple API workers
            # cannot apply the same kernel-counter delta twice.
            delta_up = counter_delta(current["last_counter_up"], current_up)
            delta_down = counter_delta(current["last_counter_down"], current_down)
            delta = delta_up + delta_down
            new_used = min(current["quota_bytes"], current["used_bytes"] + delta)
            db.execute(
                """UPDATE sessions SET bytes_up=bytes_up+?, bytes_down=bytes_down+?,
                   last_counter_up=?, last_counter_down=? WHERE id=? AND status='active'""",
                (delta_up, delta_down, current_up, current_down, session["id"]),
            )
            db.execute("UPDATE vouchers SET used_bytes=? WHERE id=?", (new_used, session["voucher_id"]))
            if new_used >= current["quota_bytes"]:
                db.execute(
                    "UPDATE sessions SET status='limit_reached', ended_at=?, revocation_pending=1 WHERE id=? AND status='active'",
                    (datetime.now(timezone.utc).isoformat(), session["id"]),
                )
                exhausted = True
            db.commit()
        processed += 1
    return processed
