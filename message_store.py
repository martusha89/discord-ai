import aiosqlite
import os
import config

_db = None
_available = False


async def init():
    """Initialize SQLite with FTS5. Tries persistent volume first, falls back to local."""
    global _db, _available

    db_path = config.DB_PATH
    db_dir = os.path.dirname(db_path)

    # Try persistent volume path first
    if db_dir and not os.path.isdir(db_dir):
        # No volume mounted — fall back to local (ephemeral but functional)
        db_path = config.DB_FALLBACK_PATH
        print(f"[DB] No volume at {config.DB_PATH}, using fallback: {db_path}")
    else:
        print(f"[DB] Using persistent storage: {db_path}")

    try:
        _db = await aiosqlite.connect(db_path)
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA synchronous=NORMAL")

        # Main messages table
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE,
                channel_id TEXT NOT NULL,
                channel_name TEXT,
                guild_id TEXT,
                author_id TEXT NOT NULL,
                author_name TEXT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_bot INTEGER DEFAULT 0
            )
        """)

        # FTS5 virtual table for full-text search
        await _db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                author_name,
                channel_name,
                content='messages',
                content_rowid='id',
                tokenize='porter unicode61'
            )
        """)

        # Triggers to keep FTS in sync
        await _db.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content, author_name, channel_name)
                VALUES (new.id, new.content, new.author_name, new.channel_name);
            END
        """)
        await _db.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, author_name, channel_name)
                VALUES ('delete', old.id, old.content, old.author_name, old.channel_name);
            END
        """)
        await _db.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, author_name, channel_name)
                VALUES ('delete', old.id, old.content, old.author_name, old.channel_name);
                INSERT INTO messages_fts(rowid, content, author_name, channel_name)
                VALUES (new.id, new.content, new.author_name, new.channel_name);
            END
        """)

        await _db.commit()
        _available = True
        print("[DB] Message store ready.")

    except Exception as e:
        print(f"[DB] Failed to initialize: {e}")
        _available = False


async def log_message(message):
    """Store a Discord message. Silently skips if DB unavailable."""
    if not _available or not _db:
        return

    try:
        await _db.execute("""
            INSERT OR IGNORE INTO messages
            (discord_id, channel_id, channel_name, guild_id, author_id, author_name, content, created_at, is_bot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(message.id),
            str(message.channel.id),
            getattr(message.channel, 'name', 'DM'),
            str(message.guild.id) if message.guild else None,
            str(message.author.id),
            message.author.display_name,
            message.content,
            message.created_at.isoformat(),
            1 if message.author.bot else 0,
        ))
        await _db.commit()
    except Exception as e:
        print(f"[DB] Log error: {e}")


async def search(query, guild_id=None, channel_id=None, author_name=None, limit=5):
    """Full-text search across stored messages, scoped to a guild."""
    if not _available or not _db:
        return []

    # Build FTS query — quote the user input, add * for prefix matching
    fts_query = " ".join(f'"{word}"' for word in query.split() if word.strip())
    if not fts_query:
        return []

    sql = """
        SELECT m.channel_name, m.author_name, m.created_at, m.content, m.discord_id, m.channel_id
        FROM messages_fts f
        JOIN messages m ON m.id = f.rowid
        WHERE messages_fts MATCH ?
    """
    params = [fts_query]

    if guild_id:
        sql += " AND m.guild_id = ?"
        params.append(str(guild_id))

    if channel_id:
        sql += " AND m.channel_id = ?"
        params.append(str(channel_id))

    if author_name:
        sql += " AND m.author_name LIKE ?"
        params.append(f"%{author_name}%")

    sql += " AND m.is_bot = 0"
    sql += " ORDER BY m.created_at DESC LIMIT ?"
    params.append(limit)

    try:
        async with _db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "channel_name": r[0],
                    "author_name": r[1],
                    "created_at": r[2],
                    "content": r[3],
                    "discord_id": r[4],
                    "channel_id": r[5],
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[DB] Search error: {e}")
        return []


async def get_channel_messages(channel_id, limit=200, hours=None):
    """Get messages from a channel, optionally filtered by time range."""
    if not _available or not _db:
        return []

    sql = """
        SELECT author_name, content, created_at, is_bot
        FROM messages
        WHERE channel_id = ? AND content != ''
    """
    params = [str(channel_id)]

    if hours:
        sql += " AND created_at > datetime('now', ?)"
        params.append(f"-{hours} hours")

    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    try:
        async with _db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            # Return oldest-first for summary context
            return [
                {
                    "author_name": r[0],
                    "content": r[1],
                    "created_at": r[2],
                    "is_bot": r[3],
                }
                for r in reversed(rows)
            ]
    except Exception as e:
        print(f"[DB] Channel messages error: {e}")
        return []


async def get_stats():
    """Return message count stats."""
    if not _available or not _db:
        return {"available": False}

    try:
        async with _db.execute("SELECT COUNT(*) FROM messages") as cursor:
            total = (await cursor.fetchone())[0]
        async with _db.execute("SELECT COUNT(DISTINCT channel_id) FROM messages") as cursor:
            channels = (await cursor.fetchone())[0]
        async with _db.execute("SELECT COUNT(DISTINCT author_id) FROM messages WHERE is_bot = 0") as cursor:
            users = (await cursor.fetchone())[0]
        return {"available": True, "total_messages": total, "channels": channels, "users": users}
    except Exception:
        return {"available": False}


async def close():
    """Close database connection."""
    global _db, _available
    if _db:
        await _db.close()
        _db = None
        _available = False
