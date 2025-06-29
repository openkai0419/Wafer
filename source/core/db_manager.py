class DBManager:
    """Manage SQLite connections and schema."""
    def __init__(self, db_path, connect_func, apply_pragmas):
        self.db_path = db_path
        self.connect_func = connect_func
        self.apply_pragmas = apply_pragmas
        self.conn = None
        self.read_conn = None

    def start(self):
        self.conn = self.connect_func(self.db_path, timeout=3.0, check_same_thread=False)
        self.apply_pragmas(self.conn)
        self.read_conn = self.connect_func(
            f"file:{self.db_path}?mode=ro&immutable=1", timeout=1.0, uri=True
        )
        self.apply_pragmas(self.read_conn, read_only=True)

    def close(self):
        if self.conn:
            self.conn.close()
        if self.read_conn:
            self.read_conn.close()

    def get_writer_cursor(self):
        return self.conn.cursor()

    def get_reader_cursor(self):
        return self.read_conn.cursor()

    def ensure_schema(self):
        cur = self.get_writer_cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS images (
                path TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                status TEXT DEFAULT NULL
            )
        """)
        cur.execute("PRAGMA table_info(images)")
        columns = [row[1] for row in cur.fetchall()]
        if "status" not in columns:
            cur.execute("ALTER TABLE images ADD COLUMN status TEXT DEFAULT NULL")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                path TEXT PRIMARY KEY,
                aspect_ratio REAL,
                mtime REAL,
                size INTEGER,
                created REAL,
                collected_at REAL,
                FOREIGN KEY(path) REFERENCES images(path) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meta_info (
                path TEXT,
                key TEXT,
                value TEXT,
                PRIMARY KEY(path, key),
                FOREIGN KEY(path) REFERENCES images(path) ON DELETE CASCADE
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_path ON meta_info(path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_key ON meta_info(key)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_value ON meta_info(value)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_path_key ON meta_info(path, key)")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_path ON images(path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_size ON images(size)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime)")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_path ON meta(path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_aspect_ratio ON meta(aspect_ratio)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_mtime ON meta(mtime)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_size ON meta(size)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_created ON meta(created)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_collected ON meta(collected_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_path_aspect ON meta(path, aspect_ratio)")
        cur.close()

    def integrity_check(self):
        try:
            result = self.conn.execute("PRAGMA quick_check").fetchone()
            return result[0] == "ok"
        except Exception:
            return False

    def backup_and_recreate(self, backup_path):
        if self.conn:
            self.conn.close()
        if self.db_path.exists():
            import shutil, os
            shutil.copy(self.db_path, backup_path)
            os.remove(self.db_path)
        self.conn = self.connect_func(self.db_path)
        self.apply_pragmas(self.conn)

