"""Kết nối và khởi tạo cơ sở dữ liệu SQLite."""
import sqlite3
from pathlib import Path

from flask import current_app, g

LEAVE_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type  TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'unpaid', 'business', 'wedding',
                                                    'child_wedding', 'bereavement', 'maternity', 'other')),
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

# Cột hồ sơ mở rộng của employees (thêm bằng _migrate, kiểu TEXT)
PROFILE_COLUMNS = ("id_number", "id_issue_date", "id_issue_place", "tax_code", "social_insurance_no",
                   "bank_account", "bank_name", "hometown", "marital_status", "education",
                   "emergency_name", "emergency_relation", "emergency_phone",
                   "termination_date", "termination_reason")

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

-- Lịch làm việc: ngày lễ (hưởng lương), ngày nghỉ hoán đổi, ngày làm bù
CREATE TABLE IF NOT EXISTS holidays (
    day  TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'holiday' CHECK (kind IN ('holiday', 'off', 'makeup'))
);

-- Đơn trong ngày: đi muộn, về sớm, quên chấm công, ra ngoài, đăng ký làm thêm (OT)
CREATE TABLE IF NOT EXISTS attendance_requests (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    req_type    TEXT NOT NULL CHECK (req_type IN ('late', 'early', 'forgot', 'out', 'overtime')),
    day         TEXT NOT NULL,
    time_from   TEXT,
    time_to     TEXT,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    review_note TEXT,
    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_attreq_emp_day ON attendance_requests(employee_id, day);

-- Ca làm việc; gán cho phòng ban (áp dụng cả nhánh con) hoặc từng nhân viên
CREATE TABLE IF NOT EXISTS shifts (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    work_start    TEXT NOT NULL,
    work_end      TEXT NOT NULL,
    lunch_start   TEXT NOT NULL,
    lunch_end     TEXT NOT NULL,
    grace_minutes INTEGER NOT NULL DEFAULT 5,
    work_days     TEXT NOT NULL DEFAULT '0,1,2,3,4'
);

-- Điều chỉnh số ngày phép năm (cộng / trừ thủ công), kèm lý do
CREATE TABLE IF NOT EXISTS leave_adjustments (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    year        INTEGER NOT NULL,
    days        REAL NOT NULL,
    note        TEXT NOT NULL,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_leave_adj_emp ON leave_adjustments(employee_id, year);

-- Hàng đợi email: luồng nền gửi dần, mất mạng thì thử lại sau
CREATE TABLE IF NOT EXISTS email_outbox (
    id         INTEGER PRIMARY KEY,
    recipient  TEXT NOT NULL,
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    event      TEXT,
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    error      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    next_try   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    sent_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON email_outbox(status, next_try);

-- Người phụ thuộc (giảm trừ gia cảnh khi tính thuế TNCN)
CREATE TABLE IF NOT EXISTS dependents (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    full_name   TEXT NOT NULL,
    relation    TEXT NOT NULL,
    dob         TEXT,
    id_number   TEXT,
    tax_code    TEXT,
    deduct_from TEXT,
    deduct_to   TEXT,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_dependents_emp ON dependents(employee_id);

-- Giấy tờ đính kèm hồ sơ; file nằm trong DOCUMENT_DIR/<employee_id>/
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    filename    TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_documents_emp ON documents(employee_id);

-- Hợp đồng lao động; trạng thái hiệu lực / sắp hết hạn / hết hạn tính từ ngày khi xem
CREATE TABLE IF NOT EXISTS contracts (
    id               INTEGER PRIMARY KEY,
    employee_id      INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    number           TEXT,
    type             TEXT NOT NULL CHECK (type IN ('probation', 'fixed', 'indefinite', 'seasonal')),
    sign_date        TEXT,
    start_date       TEXT NOT NULL,
    end_date         TEXT,
    position         TEXT,
    salary           REAL NOT NULL DEFAULT 0,
    insurance_salary REAL NOT NULL DEFAULT 0,
    allowances       TEXT NOT NULL DEFAULT '[]',
    note             TEXT,
    document_id      INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    status           TEXT NOT NULL DEFAULT 'signed' CHECK (status IN ('signed', 'terminated')),
    terminated_on    TEXT,
    reminded_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_contracts_emp ON contracts(employee_id, start_date);

-- Quá trình công tác: vào làm, điều chuyển, đổi chức danh, thay đổi lương, nghỉ việc...
CREATE TABLE IF NOT EXISTS employment_history (
    id             INTEGER PRIMARY KEY,
    employee_id    INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    from_value     TEXT,
    to_value       TEXT,
    decision_no    TEXT,
    decided_by     TEXT,
    note           TEXT,
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_history_emp ON employment_history(employee_id, effective_date);
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
    if "shift_id" not in cols:
        conn.execute("ALTER TABLE departments ADD COLUMN shift_id INTEGER "
                     "REFERENCES shifts(id) ON DELETE SET NULL")
    ecols = {r["name"] for r in conn.execute("PRAGMA table_info(employees)")}
    if "photo" not in ecols:
        conn.execute("ALTER TABLE employees ADD COLUMN photo TEXT")
    if "shift_id" not in ecols:
        conn.execute("ALTER TABLE employees ADD COLUMN shift_id INTEGER "
                     "REFERENCES shifts(id) ON DELETE SET NULL")
    for col in PROFILE_COLUMNS:  # hồ sơ mở rộng & nghỉ việc
        if col not in ecols:
            conn.execute(f"ALTER TABLE employees ADD COLUMN {col} TEXT")
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

    # thêm loại đơn mới (công tác, kết hôn, tang, thai sản...): SQLite không sửa được CHECK nên dựng lại bảng
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'leave_requests'").fetchone()[0]
    if "'maternity'" not in ddl:
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
