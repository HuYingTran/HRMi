"""Kết nối và khởi tạo cơ sở dữ liệu SQLite."""
import sqlite3
from pathlib import Path

from flask import current_app, g

LEAVE_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type  TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'unpaid', 'business', 'other')),
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    half_day    INTEGER NOT NULL DEFAULT 0,
    days        REAL NOT NULL,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    review_note TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reviewed_at TEXT
);
"""

# Bảng công theo tháng của từng nhân viên, đi qua quy trình:
# sent (chờ NV xác nhận) -> submitted (chờ cấp trên duyệt) <-> returned (bị trả lại) -> confirmed (đã chốt)
TIMESHEET_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
    id            INTEGER PRIMARY KEY,
    employee_id   INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    month         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'sent'
                  CHECK (status IN ('sent', 'submitted', 'returned', 'confirmed')),
    data          TEXT,
    employee_note TEXT,
    manager_note  TEXT,
    sent_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    submitted_at  TEXT,
    confirmed_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at  TEXT,
    UNIQUE (employee_id, month)
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'employee')),
    employee_id   INTEGER REFERENCES employees(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS departments (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    parent_id  INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    manager_id INTEGER REFERENCES employees(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id                INTEGER PRIMARY KEY,
    code              TEXT NOT NULL UNIQUE,
    full_name         TEXT NOT NULL,
    gender            TEXT,
    dob               TEXT,
    phone             TEXT,
    email             TEXT,
    address           TEXT,
    department_id     INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    position          TEXT,
    hire_date         TEXT,
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    annual_leave_days REAL NOT NULL DEFAULT 12,
    rfid_uid          TEXT UNIQUE,
    fingerprint_id    INTEGER UNIQUE,
    photo             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS attendance_logs (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    ts          TEXT NOT NULL,
    method      TEXT NOT NULL CHECK (method IN ('rfid', 'fingerprint', 'manual')),
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_attendance_emp_ts ON attendance_logs(employee_id, ts);
CREATE INDEX IF NOT EXISTS idx_attendance_ts ON attendance_logs(ts);

""" + LEAVE_TABLE.format(name="leave_requests") + """
CREATE INDEX IF NOT EXISTS idx_leave_emp ON leave_requests(employee_id, start_date);

""" + TIMESHEET_TABLE.format(name="timesheets") + """
-- Cấu hình dạng key/value (vd. ma trận phân quyền perm.<vai trò>.<quyền>)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Giải trình của nhân viên cho từng ngày trong bảng công
CREATE TABLE IF NOT EXISTS timesheet_explanations (
    id            INTEGER PRIMARY KEY,
    timesheet_id  INTEGER NOT NULL REFERENCES timesheets(id) ON DELETE CASCADE,
    day           TEXT NOT NULL,
    reason        TEXT NOT NULL,
    proposed_in   TEXT,
    proposed_out  TEXT,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    reply         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (timesheet_id, day)
);
"""


def connect(path):
    """Mở một kết nối mới. Mỗi luồng (web, phần cứng) dùng kết nối riêng."""
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn):
    """Bổ sung cột mới cho CSDL tạo từ phiên bản cũ."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(departments)")}
    if "parent_id" not in cols:
        conn.execute("ALTER TABLE departments ADD COLUMN parent_id INTEGER "
                     "REFERENCES departments(id) ON DELETE SET NULL")
    if "manager_id" not in cols:
        conn.execute("ALTER TABLE departments ADD COLUMN manager_id INTEGER "
                     "REFERENCES employees(id) ON DELETE SET NULL")
    if "photo" not in {r["name"] for r in conn.execute("PRAGMA table_info(employees)")}:
        conn.execute("ALTER TABLE employees ADD COLUMN photo TEXT")
    # tài khoản nhân viên
    ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "role" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
    if "employee_id" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN employee_id INTEGER "
                     "REFERENCES employees(id) ON DELETE CASCADE")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_employee ON users(employee_id) "
                 "WHERE employee_id IS NOT NULL")

    # bảng công phiên bản đầu (chỉ có bản đã chốt) -> thêm trạng thái quy trình
    tcols = {r["name"] for r in conn.execute("PRAGMA table_info(timesheets)")}
    if "status" not in tcols:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            "BEGIN;"
            + TIMESHEET_TABLE.format(name="timesheets_new")
            + "INSERT INTO timesheets_new (id, employee_id, month, status, data, manager_note, "
              "sent_at, confirmed_by, confirmed_at) SELECT id, employee_id, month, 'confirmed', data, "
              "note, confirmed_at, confirmed_by, confirmed_at FROM timesheets;"
              "DROP TABLE timesheets;"
              "ALTER TABLE timesheets_new RENAME TO timesheets;"
              "COMMIT;"
        )
        conn.execute("PRAGMA foreign_keys = ON")

    # thêm loại đơn 'business' (công tác): SQLite không sửa được CHECK nên dựng lại bảng
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'leave_requests'").fetchone()[0]
    if "'business'" not in ddl:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            "BEGIN;"
            + LEAVE_TABLE.format(name="leave_requests_new")
            + "INSERT INTO leave_requests_new SELECT id, employee_id, leave_type, start_date, "
              "end_date, half_day, days, reason, status, review_note, created_at, reviewed_at "
              "FROM leave_requests;"
              "DROP TABLE leave_requests;"
              "ALTER TABLE leave_requests_new RENAME TO leave_requests;"
              "CREATE INDEX IF NOT EXISTS idx_leave_emp ON leave_requests(employee_id, start_date);"
              "COMMIT;"
        )
        conn.execute("PRAGMA foreign_keys = ON")


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
