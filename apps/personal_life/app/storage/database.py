import sqlite3
from pathlib import Path
from typing import Any

import pymysql

from ..config import get_settings


APP_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = APP_DIR / "data"
SQLITE_DB_PATH = DATA_DIR / "personal_life.db"

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS quick_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    due_date TEXT,
    priority INTEGER NOT NULL DEFAULT 2,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    scheduled_for TEXT NOT NULL,
    start_time TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_name TEXT NOT NULL,
    category TEXT NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    as_of_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS asset_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    asset_name TEXT NOT NULL,
    category TEXT NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    snapshot_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (asset_id) REFERENCES assets(id)
);

CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL DEFAULT 'daily',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS routine_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER NOT NULL,
    checkin_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (routine_id, checkin_date),
    FOREIGN KEY (routine_id) REFERENCES routines(id)
);

CREATE TABLE IF NOT EXISTS profile_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    value_text TEXT NOT NULL,
    value_type TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium',
    memory_kind TEXT NOT NULL DEFAULT 'preference',
    source TEXT NOT NULL DEFAULT 'imported',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (category, memory_key)
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    remind_on TEXT NOT NULL,
    remind_time TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    origin_type TEXT NOT NULL DEFAULT 'manual',
    origin_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    notified_at TEXT
);

CREATE TABLE IF NOT EXISTS assistant_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    message TEXT NOT NULL,
    interpreted_as TEXT,
    created_type TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS home_arrival_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    person TEXT NOT NULL,
    confidence REAL NOT NULL,
    sensor_timestamp TEXT NOT NULL,
    processing_result TEXT NOT NULL,
    wake_success INTEGER NOT NULL,
    tts_success INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS posture_warning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posture_type TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    score REAL NOT NULL,
    sensor_timestamp TEXT NOT NULL,
    processing_result TEXT NOT NULL,
    tts_success INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS riding_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id TEXT NOT NULL DEFAULT '__legacy__',
    event_id TEXT,
    event_type TEXT NOT NULL,
    policy_key TEXT NOT NULL,
    sensor_timestamp TEXT NOT NULL,
    rule_result TEXT NOT NULL,
    ai_called INTEGER NOT NULL DEFAULT 0,
    ai_result TEXT NOT NULL DEFAULT '',
    speak INTEGER NOT NULL DEFAULT 0,
    message_text TEXT,
    priority TEXT NOT NULL,
    cooldown_sec INTEGER NOT NULL DEFAULT 0,
    processing_ms INTEGER NOT NULL DEFAULT 0,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS posture_sessions (
    session_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    last_observed_at TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'NORMAL',
    current_state_started_at TEXT NOT NULL,
    first_warning_at TEXT,
    first_bad_at TEXT,
    time_to_first_warning_seconds REAL,
    time_to_first_bad_seconds REAL,
    normal_duration_seconds REAL NOT NULL DEFAULT 0,
    warning_duration_seconds REAL NOT NULL DEFAULT 0,
    bad_duration_seconds REAL NOT NULL DEFAULT 0,
    valid_duration_seconds REAL NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    bad_event_count INTEGER NOT NULL DEFAULT 0,
    recovery_count INTEGER NOT NULL DEFAULT 0,
    longest_bad_duration_seconds REAL NOT NULL DEFAULT 0,
    recovery_total_seconds REAL NOT NULL DEFAULT 0,
    avg_recovery_seconds REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS posture_state_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    previous_state TEXT NOT NULL,
    current_state TEXT NOT NULL,
    previous_state_duration_seconds REAL NOT NULL DEFAULT 0,
    posture_score REAL NOT NULL DEFAULT 0,
    trigger_type TEXT NOT NULL DEFAULT 'state_change',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (session_id) REFERENCES posture_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_posture_state_events_session_time ON posture_state_events(session_id, occurred_at);

CREATE TABLE IF NOT EXISTS posture_warning_recoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    warning_event_id INTEGER NOT NULL,
    warning_at TEXT NOT NULL,
    recovery_at TEXT,
    recovery_seconds REAL,
    recovery_success INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (warning_event_id),
    FOREIGN KEY (session_id) REFERENCES posture_sessions(session_id),
    FOREIGN KEY (warning_event_id) REFERENCES posture_warning_events(id)
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'mobile',
    command_text TEXT NOT NULL,
    task_type TEXT NOT NULL,
    search_query TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    device_label TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    result_summary TEXT,
    result_payload TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS agent_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_types TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '대기',
    processing TEXT NOT NULL DEFAULT '대기중',
    tone TEXT NOT NULL DEFAULT 'idle',
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS agent_news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    importance_score INTEGER NOT NULL DEFAULT 1,
    UNIQUE (agent_id, url)
);

CREATE TABLE IF NOT EXISTS agent_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    report_date TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    highlights_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (agent_id, report_date)
);

CREATE TABLE IF NOT EXISTS agent_status (
    agent_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'idle',
    last_run_at TEXT,
    last_success_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent_id INTEGER NOT NULL,
    to_agent_id INTEGER,
    topic TEXT NOT NULL DEFAULT 'general',
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'posted',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS agent_dev_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    stack TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS agent_dev_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    change_type TEXT NOT NULL DEFAULT 'modify',
    affected_files TEXT NOT NULL DEFAULT '[]',
    target_files TEXT NOT NULL DEFAULT '[]',
    risk_level TEXT NOT NULL DEFAULT 'low',
    code_preview TEXT NOT NULL DEFAULT '',
    diff_preview TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    approved_at TEXT,
    completed_at TEXT,
    codex_task_id INTEGER
);

CREATE TABLE IF NOT EXISTS agent_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'gyuos-core',
    observation_type TEXT NOT NULL DEFAULT 'status',
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS agent_autonomy_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    expected_action TEXT NOT NULL DEFAULT '',
    target_area TEXT NOT NULL DEFAULT '',
    target_files TEXT NOT NULL DEFAULT '[]',
    risk_level TEXT NOT NULL DEFAULT 'low',
    approval_required INTEGER NOT NULL DEFAULT 1,
    suggested_task_type TEXT NOT NULL DEFAULT 'autonomy_review',
    command_text TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    source_key TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    approved_at TEXT,
    queued_at TEXT,
    completed_at TEXT,
    task_id INTEGER,
    UNIQUE (source_key)
);

CREATE TABLE IF NOT EXISTS agent_blog_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL DEFAULT 2,
    source_agent_id INTEGER,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'naver_blog',
    status TEXT NOT NULL DEFAULT 'drafted',
    source_payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS income_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL UNIQUE,
    salary INTEGER NOT NULL DEFAULT 0,
    saving INTEGER NOT NULL DEFAULT 0,
    fixed_expense INTEGER NOT NULL DEFAULT 0,
    check_card INTEGER NOT NULL DEFAULT 0,
    credit_card INTEGER NOT NULL DEFAULT 0,
    remaining_cash INTEGER NOT NULL DEFAULT 0,
    card_limit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL,
    category TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS card_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_name TEXT NOT NULL,
    total_amount INTEGER NOT NULL DEFAULT 0,
    payment_amount INTEGER NOT NULL DEFAULT 0,
    billing_cycle_start TEXT,
    billing_cycle_end TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS installments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    total_month INTEGER NOT NULL DEFAULT 1,
    current_month INTEGER NOT NULL DEFAULT 1,
    monthly_amount INTEGER NOT NULL DEFAULT 0,
    card_name TEXT NOT NULL DEFAULT '',
    start_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS assets_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL UNIQUE,
    total_asset INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS auto_transfer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    transfer_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

MARIADB_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS quick_captures (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        capture_type VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        source VARCHAR(100) NOT NULL DEFAULT 'manual',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        details TEXT NOT NULL,
        due_date VARCHAR(20) NULL,
        priority INT NOT NULL DEFAULT 2,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schedules (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        details TEXT NOT NULL,
        scheduled_for VARCHAR(20) NOT NULL,
        start_time VARCHAR(10) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        asset_name VARCHAR(200) NOT NULL,
        category VARCHAR(100) NOT NULL,
        current_value BIGINT NOT NULL DEFAULT 0,
        as_of_date VARCHAR(20) NULL,
        notes TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_snapshots (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        asset_id BIGINT NOT NULL,
        asset_name VARCHAR(200) NOT NULL,
        category VARCHAR(100) NOT NULL,
        current_value BIGINT NOT NULL DEFAULT 0,
        snapshot_date VARCHAR(20) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_asset_snapshots_asset
            FOREIGN KEY (asset_id) REFERENCES assets(id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS routines (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(200) NOT NULL,
        description TEXT NOT NULL,
        frequency VARCHAR(50) NOT NULL DEFAULT 'daily',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS routine_checkins (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        routine_id BIGINT NOT NULL,
        checkin_date VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'done',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_routine_day (routine_id, checkin_date),
        CONSTRAINT fk_routine_checkins_routine
            FOREIGN KEY (routine_id) REFERENCES routines(id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profile_memories (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        category VARCHAR(100) NOT NULL,
        memory_key VARCHAR(255) NOT NULL,
        value_text TEXT NOT NULL,
        value_type VARCHAR(50) NOT NULL,
        confidence VARCHAR(20) NOT NULL DEFAULT 'medium',
        memory_kind VARCHAR(50) NOT NULL DEFAULT 'preference',
        source VARCHAR(50) NOT NULL DEFAULT 'imported',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_profile_memory (category, memory_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        details TEXT NOT NULL,
        remind_on VARCHAR(20) NOT NULL,
        remind_time VARCHAR(10) NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
        origin_type VARCHAR(50) NOT NULL DEFAULT 'manual',
        origin_id BIGINT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notified_at DATETIME NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assistant_conversations (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        role VARCHAR(20) NOT NULL,
        message TEXT NOT NULL,
        interpreted_as VARCHAR(30) NULL,
        created_type VARCHAR(30) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS home_arrival_events (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        source VARCHAR(100) NOT NULL,
        person VARCHAR(100) NOT NULL,
        confidence DOUBLE NOT NULL,
        sensor_timestamp VARCHAR(64) NOT NULL,
        processing_result VARCHAR(30) NOT NULL,
        wake_success BOOLEAN NOT NULL DEFAULT FALSE,
        tts_success BOOLEAN NOT NULL DEFAULT FALSE,
        payload_json LONGTEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS posture_warning_events (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        posture_type VARCHAR(30) NOT NULL,
        duration_seconds DOUBLE NOT NULL,
        score DOUBLE NOT NULL,
        sensor_timestamp VARCHAR(64) NOT NULL,
        processing_result VARCHAR(30) NOT NULL,
        tts_success BOOLEAN NOT NULL DEFAULT FALSE,
        payload_json LONGTEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS posture_sessions (
        session_id VARCHAR(64) PRIMARY KEY,
        source VARCHAR(100) NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'active',
        started_at VARCHAR(64) NOT NULL,
        ended_at VARCHAR(64) NULL,
        last_observed_at VARCHAR(64) NOT NULL,
        current_state VARCHAR(30) NOT NULL DEFAULT 'NORMAL',
        current_state_started_at VARCHAR(64) NOT NULL,
        first_warning_at VARCHAR(64) NULL,
        first_bad_at VARCHAR(64) NULL,
        time_to_first_warning_seconds DOUBLE NULL,
        time_to_first_bad_seconds DOUBLE NULL,
        normal_duration_seconds DOUBLE NOT NULL DEFAULT 0,
        warning_duration_seconds DOUBLE NOT NULL DEFAULT 0,
        bad_duration_seconds DOUBLE NOT NULL DEFAULT 0,
        valid_duration_seconds DOUBLE NOT NULL DEFAULT 0,
        warning_count INT NOT NULL DEFAULT 0,
        bad_event_count INT NOT NULL DEFAULT 0,
        recovery_count INT NOT NULL DEFAULT 0,
        longest_bad_duration_seconds DOUBLE NOT NULL DEFAULT 0,
        recovery_total_seconds DOUBLE NOT NULL DEFAULT 0,
        avg_recovery_seconds DOUBLE NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS posture_state_events (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        session_id VARCHAR(64) NOT NULL,
        occurred_at VARCHAR(64) NOT NULL,
        previous_state VARCHAR(30) NOT NULL,
        current_state VARCHAR(30) NOT NULL,
        previous_state_duration_seconds DOUBLE NOT NULL DEFAULT 0,
        posture_score DOUBLE NOT NULL DEFAULT 0,
        trigger_type VARCHAR(50) NOT NULL DEFAULT 'state_change',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_posture_state_events_session_time (session_id, occurred_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS posture_warning_recoveries (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        session_id VARCHAR(64) NOT NULL,
        warning_event_id BIGINT NOT NULL UNIQUE,
        warning_at VARCHAR(64) NOT NULL,
        recovery_at VARCHAR(64) NULL,
        recovery_seconds DOUBLE NULL,
        recovery_success BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS riding_events (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        ride_id VARCHAR(128) NOT NULL DEFAULT '__legacy__',
        event_id VARCHAR(128) NULL,
        event_type VARCHAR(40) NOT NULL,
        policy_key VARCHAR(40) NOT NULL,
        sensor_timestamp VARCHAR(64) NOT NULL,
        rule_result VARCHAR(100) NOT NULL,
        ai_called BOOLEAN NOT NULL DEFAULT FALSE,
        ai_result VARCHAR(100) NOT NULL DEFAULT '',
        speak BOOLEAN NOT NULL DEFAULT FALSE,
        message_text TEXT NULL,
        priority VARCHAR(20) NOT NULL,
        cooldown_sec INT NOT NULL DEFAULT 0,
        processing_ms INT NOT NULL DEFAULT 0,
        context_json LONGTEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_riding_events_cooldown (ride_id, policy_key, speak, created_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_tasks (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        source VARCHAR(30) NOT NULL DEFAULT 'mobile',
        command_text TEXT NOT NULL,
        task_type VARCHAR(50) NOT NULL,
        search_query VARCHAR(255) NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        device_label VARCHAR(100) NULL,
        claimed_at DATETIME NULL,
        completed_at DATETIME NULL,
        result_summary TEXT NULL,
        result_payload LONGTEXT NULL,
        error_message TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_definitions (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(255) NOT NULL,
        description TEXT NOT NULL,
        task_types VARCHAR(500) NOT NULL DEFAULT '',
        status VARCHAR(30) NOT NULL DEFAULT '대기',
        processing VARCHAR(255) NOT NULL DEFAULT '대기중',
        tone VARCHAR(30) NOT NULL DEFAULT 'idle',
        sort_order INT NOT NULL DEFAULT 100,
        is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_news_items (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        agent_id INT NOT NULL,
        topic VARCHAR(100) NOT NULL,
        title TEXT NOT NULL,
        url VARCHAR(1000) NOT NULL,
        source VARCHAR(200) NOT NULL DEFAULT '',
        published_at DATETIME NULL,
        collected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        importance_score INT NOT NULL DEFAULT 1,
        UNIQUE KEY uniq_agent_news_url (agent_id, url(500))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_reports (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        agent_id INT NOT NULL,
        report_date VARCHAR(20) NOT NULL,
        title VARCHAR(255) NOT NULL,
        summary TEXT NOT NULL,
        highlights_json LONGTEXT NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'completed',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_agent_report_day (agent_id, report_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_status (
        agent_id INT PRIMARY KEY,
        status VARCHAR(20) NOT NULL DEFAULT 'idle',
        last_run_at DATETIME NULL,
        last_success_at DATETIME NULL,
        last_error TEXT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_log (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        agent_id INT NOT NULL,
        message TEXT NOT NULL,
        level VARCHAR(20) NOT NULL DEFAULT 'info',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_messages (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        from_agent_id INT NOT NULL,
        to_agent_id INT NULL,
        topic VARCHAR(100) NOT NULL DEFAULT 'general',
        message TEXT NOT NULL,
        payload_json LONGTEXT NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'posted',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_dev_projects (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(255) NOT NULL,
        root_path VARCHAR(1000) NOT NULL UNIQUE,
        description TEXT NOT NULL,
        stack VARCHAR(500) NOT NULL DEFAULT '',
        status VARCHAR(30) NOT NULL DEFAULT 'active',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_dev_proposals (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        project_id BIGINT NOT NULL,
        title VARCHAR(255) NOT NULL,
        summary TEXT NOT NULL,
        reason TEXT NOT NULL,
        change_type VARCHAR(20) NOT NULL DEFAULT 'modify',
        affected_files LONGTEXT NULL,
        target_files LONGTEXT NOT NULL,
        risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
        code_preview LONGTEXT NULL,
        diff_preview LONGTEXT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        approved_at DATETIME NULL,
        completed_at DATETIME NULL,
        codex_task_id BIGINT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_observations (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        agent_id INT NOT NULL DEFAULT 0,
        source VARCHAR(100) NOT NULL DEFAULT 'gyuos-core',
        observation_type VARCHAR(50) NOT NULL DEFAULT 'status',
        title VARCHAR(255) NOT NULL,
        summary TEXT NOT NULL,
        payload_json LONGTEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_autonomy_proposals (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        agent_id INT NOT NULL DEFAULT 0,
        title VARCHAR(255) NOT NULL,
        summary TEXT NOT NULL,
        reason TEXT NOT NULL,
        expected_action TEXT NOT NULL,
        target_area VARCHAR(255) NOT NULL DEFAULT '',
        target_files LONGTEXT NOT NULL,
        risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
        approval_required BOOLEAN NOT NULL DEFAULT TRUE,
        suggested_task_type VARCHAR(80) NOT NULL DEFAULT 'autonomy_review',
        command_text TEXT NOT NULL,
        payload_json LONGTEXT NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        source_key VARCHAR(255) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        approved_at DATETIME NULL,
        queued_at DATETIME NULL,
        completed_at DATETIME NULL,
        task_id BIGINT NULL,
        UNIQUE KEY uniq_agent_autonomy_source (source_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_blog_drafts (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        agent_id INT NOT NULL DEFAULT 2,
        source_agent_id INT NULL,
        title VARCHAR(255) NOT NULL,
        body LONGTEXT NOT NULL,
        platform VARCHAR(50) NOT NULL DEFAULT 'naver_blog',
        status VARCHAR(30) NOT NULL DEFAULT 'drafted',
        source_payload LONGTEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS income_summary (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        month VARCHAR(7) NOT NULL UNIQUE,
        salary BIGINT NOT NULL DEFAULT 0,
        saving BIGINT NOT NULL DEFAULT 0,
        fixed_expense BIGINT NOT NULL DEFAULT 0,
        check_card BIGINT NOT NULL DEFAULT 0,
        credit_card BIGINT NOT NULL DEFAULT 0,
        remaining_cash BIGINT NOT NULL DEFAULT 0,
        card_limit BIGINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS expenses (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        month VARCHAR(7) NOT NULL,
        category VARCHAR(100) NOT NULL,
        amount BIGINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS card_usage (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        card_name VARCHAR(100) NOT NULL,
        total_amount BIGINT NOT NULL DEFAULT 0,
        payment_amount BIGINT NOT NULL DEFAULT 0,
        billing_cycle_start VARCHAR(20) NULL,
        billing_cycle_end VARCHAR(20) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS installments (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        total_month INT NOT NULL DEFAULT 1,
        current_month INT NOT NULL DEFAULT 1,
        monthly_amount BIGINT NOT NULL DEFAULT 0,
        card_name VARCHAR(100) NOT NULL DEFAULT '',
        start_date VARCHAR(20) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets_history (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        month VARCHAR(7) NOT NULL UNIQUE,
        total_asset BIGINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auto_transfer (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        amount BIGINT NOT NULL DEFAULT 0,
        transfer_date VARCHAR(20) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


def initialize_database() -> None:
    settings = get_settings()
    if settings.db_backend == "mariadb":
        initialize_mariadb()
    else:
        initialize_sqlite()


def initialize_sqlite() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SQLITE_DB_PATH) as connection:
        connection.executescript(SQLITE_SCHEMA)
        _ensure_sqlite_riding_event_columns(connection)
        _ensure_sqlite_dev_proposal_columns(connection)
        _ensure_sqlite_autonomy_tables(connection)
        connection.commit()


def initialize_mariadb() -> None:
    settings = get_settings()
    bootstrap = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    with bootstrap.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{settings.db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    bootstrap.close()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for statement in MARIADB_SCHEMA:
                cursor.execute(statement)
            _ensure_mariadb_dev_proposal_columns(cursor)
            _ensure_mariadb_riding_event_columns(cursor)
            _ensure_mariadb_autonomy_tables(cursor)
        connection.commit()


def get_connection() -> Any:
    settings = get_settings()
    if settings.db_backend == "mariadb":
        return pymysql.connect(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SQLITE_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _adapt_query(query: str) -> str:
    settings = get_settings()
    if settings.db_backend == "mariadb":
        return query.replace("?", "%s")
    return query


def execute(query: str, parameters: tuple[Any, ...] = ()) -> int:
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(adapted, parameters)
        connection.commit()
        return int(cursor.lastrowid or 0)


def execute_many(query: str, parameter_rows: list[tuple[Any, ...]]) -> None:
    if not parameter_rows:
        return
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.executemany(adapted, parameter_rows)
        connection.commit()


def fetch_one(query: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(adapted, parameters)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row) if not isinstance(row, dict) else row


def fetch_all(query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(adapted, parameters)
        rows = cursor.fetchall()
        return [dict(row) if not isinstance(row, dict) else row for row in rows]


def _ensure_sqlite_dev_proposal_columns(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_dev_proposals)").fetchall()}
    required = {
        "change_type": "TEXT NOT NULL DEFAULT 'modify'",
        "affected_files": "TEXT NOT NULL DEFAULT '[]'",
        "code_preview": "TEXT NOT NULL DEFAULT ''",
        "diff_preview": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in required.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE agent_dev_proposals ADD COLUMN {column} {definition}")


def _ensure_sqlite_riding_event_columns(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(riding_events)").fetchall()}
    required = {
        "ride_id": "TEXT NOT NULL DEFAULT '__legacy__'",
        "event_id": "TEXT",
    }
    for column, definition in required.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE riding_events ADD COLUMN {column} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_riding_events_cooldown ON riding_events (ride_id, policy_key, speak, created_at)"
    )


def _ensure_mariadb_dev_proposal_columns(cursor: Any) -> None:
    cursor.execute("SHOW COLUMNS FROM agent_dev_proposals")
    columns = {row["Field"] if isinstance(row, dict) else row[0] for row in cursor.fetchall()}
    required = {
        "change_type": "VARCHAR(20) NOT NULL DEFAULT 'modify'",
        "affected_files": "LONGTEXT NULL",
        "code_preview": "LONGTEXT NULL",
        "diff_preview": "LONGTEXT NULL",
    }
    for column, definition in required.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE agent_dev_proposals ADD COLUMN {column} {definition}")


def _ensure_mariadb_riding_event_columns(cursor: Any) -> None:
    cursor.execute("SHOW COLUMNS FROM riding_events")
    columns = {row["Field"] if isinstance(row, dict) else row[0] for row in cursor.fetchall()}
    required = {
        "ride_id": "VARCHAR(128) NOT NULL DEFAULT '__legacy__'",
        "event_id": "VARCHAR(128) NULL",
    }
    for column, definition in required.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE riding_events ADD COLUMN {column} {definition}")

    cursor.execute("SHOW INDEX FROM riding_events WHERE Key_name = 'idx_riding_events_cooldown'")
    index_rows = cursor.fetchall()
    indexed_columns = [row["Column_name"] if isinstance(row, dict) else row[4] for row in index_rows]
    if indexed_columns != ["ride_id", "policy_key", "speak", "created_at"]:
        if index_rows:
            cursor.execute("DROP INDEX idx_riding_events_cooldown ON riding_events")
        cursor.execute(
            "CREATE INDEX idx_riding_events_cooldown ON riding_events (ride_id, policy_key, speak, created_at)"
        )


def _ensure_sqlite_autonomy_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'gyuos-core',
            observation_type TEXT NOT NULL DEFAULT 'status',
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_autonomy_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            expected_action TEXT NOT NULL DEFAULT '',
            target_area TEXT NOT NULL DEFAULT '',
            target_files TEXT NOT NULL DEFAULT '[]',
            risk_level TEXT NOT NULL DEFAULT 'low',
            approval_required INTEGER NOT NULL DEFAULT 1,
            suggested_task_type TEXT NOT NULL DEFAULT 'autonomy_review',
            command_text TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            source_key TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            approved_at TEXT,
            queued_at TEXT,
            completed_at TEXT,
            task_id INTEGER,
            UNIQUE (source_key)
        )
        """
    )


def _ensure_mariadb_autonomy_tables(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_observations (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            agent_id INT NOT NULL DEFAULT 0,
            source VARCHAR(100) NOT NULL DEFAULT 'gyuos-core',
            observation_type VARCHAR(50) NOT NULL DEFAULT 'status',
            title VARCHAR(255) NOT NULL,
            summary TEXT NOT NULL,
            payload_json LONGTEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_autonomy_proposals (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            agent_id INT NOT NULL DEFAULT 0,
            title VARCHAR(255) NOT NULL,
            summary TEXT NOT NULL,
            reason TEXT NOT NULL,
            expected_action TEXT NOT NULL,
            target_area VARCHAR(255) NOT NULL DEFAULT '',
            target_files LONGTEXT NOT NULL,
            risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
            approval_required BOOLEAN NOT NULL DEFAULT TRUE,
            suggested_task_type VARCHAR(80) NOT NULL DEFAULT 'autonomy_review',
            command_text TEXT NOT NULL,
            payload_json LONGTEXT NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            source_key VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approved_at DATETIME NULL,
            queued_at DATETIME NULL,
            completed_at DATETIME NULL,
            task_id BIGINT NULL,
            UNIQUE KEY uniq_agent_autonomy_source (source_key)
        )
        """
    )
