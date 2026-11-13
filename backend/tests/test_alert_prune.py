from app.db import alerts_db
from app.db.database import get_connection


def test_prune_drops_old_outbox_and_digest_rows():
    alerts_db.create_alert_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM alert_outbox")
        conn.execute("DELETE FROM alert_digests")
    alerts_db.enqueue("u", 9001, "push", "hotel", "2025-01-01T00:00:00Z")
    alerts_db.enqueue("u", 9002, "push", "hotel", "2026-11-01T00:00:00Z")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alert_digests (user_id, week, status, sent_at)"
            " VALUES ('u', '2025-W01', 'sent', '2025-01-02T00:00:00Z'),"
            " ('u', '2026-W45', 'sent', '2026-11-05T00:00:00Z')"
        )
    assert alerts_db.prune("2026-06-01T00:00:00Z") == 2
    with get_connection() as conn:
        assert (
            conn.execute("SELECT notification_id FROM alert_outbox").fetchall()[0][0]
            == 9002
        )
        assert (
            conn.execute("SELECT week FROM alert_digests").fetchall()[0][0]
            == "2026-W45"
        )
