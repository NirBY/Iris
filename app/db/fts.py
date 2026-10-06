"""FTS5 index over messages, kept in sync by triggers (external-content table)."""

FTS_STATEMENTS = [
    """CREATE VIRTUAL TABLE messages_fts USING fts5(
        text, transcript, sender_name,
        content='messages', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2')""",
    """CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, text, transcript, sender_name)
        VALUES (new.id, new.text, new.transcript, new.sender_name);
    END""",
    """CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, text, transcript, sender_name)
        VALUES ('delete', old.id, old.text, old.transcript, old.sender_name);
    END""",
    # Redacted messages must have empty FTS content, so index blanks for them.
    """CREATE TRIGGER messages_au AFTER UPDATE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, text, transcript, sender_name)
        VALUES ('delete', old.id, old.text, old.transcript, old.sender_name);
        INSERT INTO messages_fts(rowid, text, transcript, sender_name)
        SELECT new.id,
               CASE WHEN new.redacted THEN NULL ELSE new.text END,
               CASE WHEN new.redacted THEN NULL ELSE new.transcript END,
               new.sender_name;
    END""",
]
