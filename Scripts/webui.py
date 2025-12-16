"""
Bookshelf Traveller Web UI
A simple FastAPI-based management interface for the Discord bot
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from contextlib import asynccontextmanager
from abc import ABC, abstractmethod

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv, set_key

import bookshelfAPI as c

# Logger Config
logger = logging.getLogger("webui")

# Load environment variables
load_dotenv()

# Configuration file path
ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')
if not os.path.exists(ENV_FILE):
    ENV_FILE = '.env'

# Database configuration
DB_TYPE = os.getenv('DB_TYPE', 'sqlite').lower()
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'bookshelf')
DB_PATH = 'db/settings.db'

# Global state
startup_time = datetime.now()
db_instance = None


# ============== Database Abstract Interface ==============
class SettingsDBInterface(ABC):
    @abstractmethod
    async def connect(self):
        pass

    @abstractmethod
    async def close(self):
        pass

    @abstractmethod
    async def create_settings_table(self):
        pass

    @abstractmethod
    async def get_setting(self, key: str) -> Optional[str]:
        pass

    @abstractmethod
    async def set_setting(self, key: str, value: str) -> bool:
        pass

    @abstractmethod
    async def get_all_settings(self) -> Dict[str, str]:
        pass


# ============== SQLite Implementation ==============
class SQLiteSettingsDB(SettingsDBInterface):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    async def connect(self):
        import aiosqlite
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        await self.create_settings_table()
        logger.info(f"Connected to SQLite settings database: {self.db_path}")

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def create_settings_table(self):
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        await self.conn.commit()

    async def get_setting(self, key: str) -> Optional[str]:
        cursor = await self.conn.execute(
            'SELECT value FROM settings WHERE key = ?', (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> bool:
        try:
            await self.conn.execute(
                'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                (key, value)
            )
            await self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")
            return False

    async def get_all_settings(self) -> Dict[str, str]:
        cursor = await self.conn.execute('SELECT key, value FROM settings')
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}


# ============== MariaDB Implementation ==============
class MariaDBSettingsDB(SettingsDBInterface):
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.pool = None

    async def connect(self):
        import aiomysql
        self.pool = await aiomysql.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.database,
            autocommit=True
        )
        await self.create_settings_table()
        logger.info(f"Connected to MariaDB settings database: {self.database}")

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def create_settings_table(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        `key` VARCHAR(255) PRIMARY KEY,
                        `value` TEXT NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                ''')

    async def get_setting(self, key: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    'SELECT value FROM settings WHERE `key` = %s', (key,)
                )
                row = await cursor.fetchone()
                return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        'INSERT INTO settings (`key`, `value`) VALUES (%s, %s) '
                        'ON DUPLICATE KEY UPDATE `value` = %s',
                        (key, value, value)
                    )
            return True
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")
            return False

    async def get_all_settings(self) -> Dict[str, str]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('SELECT `key`, `value` FROM settings')
                rows = await cursor.fetchall()
                return {row[0]: row[1] for row in rows}


# ============== Database Factory ==============
def get_settings_db() -> SettingsDBInterface:
    if DB_TYPE == 'mariadb':
        return MariaDBSettingsDB(DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME)
    else:
        return SQLiteSettingsDB(DB_PATH)


# ============== Settings Helper Functions ==============
async def load_settings_to_env():
    """Load settings from database into environment variables"""
    global db_instance
    if db_instance:
        settings = await db_instance.get_all_settings()
        for key, value in settings.items():
            os.environ[key] = value
            logger.debug(f"Loaded setting {key} from database")


async def save_setting(key: str, value: str) -> bool:
    """Save a setting to database and environment"""
    global db_instance
    if db_instance:
        success = await db_instance.set_setting(key, value)
        if success:
            os.environ[key] = value
        return success
    return False


# ============== Pydantic Models ==============
class ServerConfig(BaseModel):
    bookshelfURL: str = Field(..., description="Audiobookshelf server URL")
    bookshelfToken: str = Field(..., description="Audiobookshelf API token")


class DiscordConfig(BaseModel):
    DISCORD_TOKEN: str = Field(..., description="Discord bot token")
    CLIENT_ID: Optional[str] = Field("", description="Discord client ID")


class SettingsConfig(BaseModel):
    DEBUG_MODE: bool = Field(False)
    MULTI_USER: bool = Field(True)
    AUDIO_ENABLED: bool = Field(True)
    FFMPEG_DEBUG: bool = Field(False)
    EXPERIMENTAL: bool = Field(False)
    INITIALIZED_MSG: bool = Field(True)
    OWNER_ONLY: bool = Field(True)
    EPHEMERAL_OUTPUT: bool = Field(True)


class DatabaseConfig(BaseModel):
    DB_TYPE: str = Field("sqlite")
    DB_HOST: str = Field("localhost")
    DB_PORT: int = Field(3306)
    DB_USER: str = Field("root")
    DB_PASSWORD: str = Field("")
    DB_NAME: str = Field("bookshelf")


class TestConnectionRequest(BaseModel):
    url: str
    token: str


def get_env_value(key: str, default: str = "") -> str:
    """Get environment variable value"""
    return os.getenv(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean environment variable"""
    value = os.getenv(key, str(default)).lower()
    return value in ("1", "true", "yes")


def load_current_config() -> Dict[str, Any]:
    """Load current configuration from environment"""
    return {
        "server": {
            "bookshelfURL": get_env_value("bookshelfURL", ""),
            "bookshelfToken": get_env_value("bookshelfToken", ""),
        },
        "discord": {
            "DISCORD_TOKEN": get_env_value("DISCORD_TOKEN", ""),
            "CLIENT_ID": get_env_value("CLIENT_ID", ""),
        },
        "settings": {
            "DEBUG_MODE": get_env_bool("DEBUG_MODE", False),
            "MULTI_USER": get_env_bool("MULTI_USER", True),
            "AUDIO_ENABLED": get_env_bool("AUDIO_ENABLED", True),
            "FFMPEG_DEBUG": get_env_bool("FFMPEG_DEBUG", False),
            "EXPERIMENTAL": get_env_bool("EXPERIMENTAL", False),
            "INITIALIZED_MSG": get_env_bool("INITIALIZED_MSG", True),
            "OWNER_ONLY": get_env_bool("OWNER_ONLY", True),
            "EPHEMERAL_OUTPUT": get_env_bool("EPHEMERAL_OUTPUT", True),
        },
        "database": {
            "DB_TYPE": get_env_value("DB_TYPE", "sqlite"),
            "DB_HOST": get_env_value("DB_HOST", "localhost"),
            "DB_PORT": int(get_env_value("DB_PORT", "3306")),
            "DB_USER": get_env_value("DB_USER", "root"),
            "DB_PASSWORD": get_env_value("DB_PASSWORD", ""),
            "DB_NAME": get_env_value("DB_NAME", "bookshelf"),
        }
    }


# ============== FastAPI App ==============
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    global db_instance
    logger.info("Starting Bookshelf Traveller Web UI...")

    # Initialize database connection
    db_instance = get_settings_db()
    await db_instance.connect()
    await load_settings_to_env()

    yield

    # Cleanup
    if db_instance:
        await db_instance.close()
    logger.info("Shutting down Web UI...")


app = FastAPI(
    title="Bookshelf Traveller Admin",
    description="Web management interface for Bookshelf Traveller Discord Bot",
    version="1.0.0",
    lifespan=lifespan
)


def get_dashboard_html() -> str:
    """Return the main dashboard HTML"""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bookshelf Traveller</title>
    <link href="https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700&family=Open+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #1a1410;
            --bg-secondary: #231c16;
            --bg-card: #2a211a;
            --bg-input: #1f1915;
            --accent-primary: #c9a227;
            --accent-secondary: #d4b74a;
            --accent-glow: rgba(201, 162, 39, 0.2);
            --text-primary: #f5ebe0;
            --text-secondary: #c4b8a9;
            --text-muted: #8a7e72;
            --border-color: #3d3228;
            --success: #7dad68;
            --error: #c45c4a;
            --warning: #d4a03a;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Open Sans', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }

        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem 1.5rem;
        }

        .header {
            text-align: center;
            margin-bottom: 2.5rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }

        .header h1 {
            font-family: 'Merriweather', serif;
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--accent-primary);
            margin-bottom: 0.5rem;
        }

        .header .version {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        .status-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .status-item {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            text-align: center;
        }

        .status-item .label {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }

        .status-item .value {
            font-size: 1.1rem;
            font-weight: 600;
        }

        .status-item .value.online { color: var(--success); }
        .status-item .value.offline { color: var(--error); }

        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }

        .card-title {
            font-family: 'Merriweather', serif;
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--accent-secondary);
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }

        .form-group {
            margin-bottom: 1.25rem;
        }

        .form-label {
            display: block;
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }

        .form-input {
            width: 100%;
            padding: 0.75rem 1rem;
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: var(--text-primary);
            font-family: monospace;
            font-size: 0.9rem;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        .form-input::placeholder { color: var(--text-muted); }

        .form-help {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 0.35rem;
        }

        /* Toggle Switch */
        .toggle-group {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.75rem 1rem;
            background: var(--bg-input);
            border-radius: 6px;
            margin-bottom: 0.75rem;
        }

        .toggle-info {
            display: flex;
            flex-direction: column;
        }

        .toggle-title {
            font-size: 0.9rem;
            font-weight: 500;
            color: var(--text-primary);
        }

        .toggle-desc {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .toggle {
            position: relative;
            width: 44px;
            height: 24px;
            flex-shrink: 0;
        }

        .toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0; left: 0; right: 0; bottom: 0;
            background: var(--border-color);
            border-radius: 24px;
            transition: 0.3s;
        }

        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 3px;
            bottom: 3px;
            background: var(--text-primary);
            border-radius: 50%;
            transition: 0.3s;
        }

        .toggle input:checked + .toggle-slider {
            background: var(--accent-primary);
        }

        .toggle input:checked + .toggle-slider:before {
            transform: translateX(20px);
        }

        .btn {
            display: inline-block;
            padding: 0.7rem 1.5rem;
            border: none;
            border-radius: 6px;
            font-family: 'Open Sans', sans-serif;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--accent-primary);
            color: var(--bg-primary);
        }

        .btn-primary:hover { background: var(--accent-secondary); }

        .btn-secondary {
            background: var(--bg-secondary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }

        .btn-secondary:hover { background: var(--border-color); }

        .btn-group {
            display: flex;
            gap: 0.75rem;
            margin-top: 1rem;
            flex-wrap: wrap;
        }

        .toast-container {
            position: fixed;
            bottom: 1.5rem;
            right: 1.5rem;
            z-index: 1000;
        }

        .toast {
            padding: 0.875rem 1.25rem;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            margin-top: 0.5rem;
            animation: slideIn 0.3s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        .toast.success { border-left: 3px solid var(--success); }
        .toast.error { border-left: 3px solid var(--error); }
        .toast.warning { border-left: 3px solid var(--warning); }
        .toast.info { border-left: 3px solid var(--accent-primary); }

        @keyframes slideIn {
            from { opacity: 0; transform: translateX(50px); }
            to { opacity: 1; transform: translateX(0); }
        }

        @media (max-width: 600px) {
            .container { padding: 1rem; }
            .header h1 { font-size: 1.5rem; }
            .btn-group { flex-direction: column; }
            .btn { width: 100%; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>Bookshelf Traveller</h1>
            <span class="version" id="version">Loading...</span>
        </header>

        <!-- Status -->
        <section class="status-section">
            <div class="status-item">
                <div class="label">Connection</div>
                <div class="value" id="abs-status">--</div>
            </div>
            <div class="status-item">
                <div class="label">User</div>
                <div class="value" id="abs-user">--</div>
            </div>
            <div class="status-item">
                <div class="label">Type</div>
                <div class="value" id="abs-type">--</div>
            </div>
            <div class="status-item">
                <div class="label">Uptime</div>
                <div class="value" id="uptime">--</div>
            </div>
        </section>

        <!-- Server Config -->
        <div class="card">
            <h2 class="card-title">Audiobookshelf Server</h2>
            <form id="server-form">
                <div class="form-group">
                    <label class="form-label">Server URL</label>
                    <input type="url" class="form-input" name="bookshelfURL" 
                           placeholder="https://abs.example.com" required>
                    <span class="form-help">Your Audiobookshelf server address</span>
                </div>
                <div class="form-group">
                    <label class="form-label">API Token</label>
                    <input type="password" class="form-input" name="bookshelfToken" 
                           placeholder="Your API token" required>
                    <span class="form-help">Found in ABS Settings > Users > Your User</span>
                </div>
                <div class="btn-group">
                    <button type="submit" class="btn btn-primary">Save</button>
                    <button type="button" class="btn btn-secondary" id="test-abs-btn">Test Connection</button>
                </div>
            </form>
        </div>

        <!-- Discord Config -->
        <div class="card">
            <h2 class="card-title">Discord Bot</h2>
            <form id="discord-form">
                <div class="form-group">
                    <label class="form-label">Bot Token</label>
                    <input type="password" class="form-input" name="DISCORD_TOKEN" 
                           placeholder="Your Discord bot token" required>
                    <span class="form-help">From Discord Developer Portal</span>
                </div>
                <div class="form-group">
                    <label class="form-label">Client ID</label>
                    <input type="text" class="form-input" name="CLIENT_ID" 
                           placeholder="Bot client ID (for invite link)">
                </div>
                <div class="btn-group">
                    <button type="submit" class="btn btn-primary">Save</button>
                    <button type="button" class="btn btn-secondary" id="copy-invite-btn">Copy Invite Link</button>
                </div>
            </form>
        </div>

        <!-- Bot Settings -->
        <div class="card">
            <h2 class="card-title">Bot Settings</h2>
            <form id="settings-form">
                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">Debug Mode</span>
                        <span class="toggle-desc">Enable verbose logging</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="DEBUG_MODE">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">Multi-User Mode</span>
                        <span class="toggle-desc">Allow multiple ABS users via Discord</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="MULTI_USER">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">Audio Enabled</span>
                        <span class="toggle-desc">Enable voice channel playback</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="AUDIO_ENABLED">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">Owner Only</span>
                        <span class="toggle-desc">Restrict commands to bot owner</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="OWNER_ONLY">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">Ephemeral Output</span>
                        <span class="toggle-desc">Make responses visible only to user</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="EPHEMERAL_OUTPUT">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">FFmpeg Debug</span>
                        <span class="toggle-desc">Enable FFmpeg debug logging</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="FFMPEG_DEBUG">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">Experimental Features</span>
                        <span class="toggle-desc">Enable beta features</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="EXPERIMENTAL">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="toggle-group">
                    <div class="toggle-info">
                        <span class="toggle-title">Initialization Message</span>
                        <span class="toggle-desc">DM owner when bot starts</span>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" name="INITIALIZED_MSG">
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="btn-group">
                    <button type="submit" class="btn btn-primary">Save Settings</button>
                </div>
            </form>
        </div>

        <!-- Database Config -->
        <div class="card">
            <h2 class="card-title">Database</h2>
            <form id="database-form">
                <div class="form-group">
                    <label class="form-label">Database Type</label>
                    <select class="form-input" name="DB_TYPE" id="db-type-select">
                        <option value="sqlite">SQLite (Recommended)</option>
                        <option value="mariadb">MariaDB / MySQL</option>
                    </select>
                    <span class="form-help">SQLite is recommended for single-instance deployments</span>
                </div>

                <div id="mariadb-fields" style="display: none;">
                    <div class="form-group">
                        <label class="form-label">Host</label>
                        <input type="text" class="form-input" name="DB_HOST" placeholder="localhost">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Port</label>
                        <input type="number" class="form-input" name="DB_PORT" placeholder="3306">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Username</label>
                        <input type="text" class="form-input" name="DB_USER" placeholder="root">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Password</label>
                        <input type="password" class="form-input" name="DB_PASSWORD" placeholder="Database password">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Database Name</label>
                        <input type="text" class="form-input" name="DB_NAME" placeholder="bookshelf">
                    </div>
                </div>

                <div class="btn-group">
                    <button type="submit" class="btn btn-primary">Save Database Settings</button>
                </div>
            </form>
        </div>

        <!-- Actions -->
        <div class="card">
            <h2 class="card-title">Actions</h2>
            <div class="btn-group">
                <button class="btn btn-secondary" id="refresh-btn">Refresh Status</button>
            </div>
        </div>
    </div>

    <div class="toast-container" id="toast-container"></div>

    <script>
        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;
            toast.textContent = message;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 4000);
        }

        async function fetchStatus() {
            try {
                const response = await fetch('/api/status');
                const status = await response.json();
                
                document.getElementById('version').textContent = status.version || '?';
                document.getElementById('abs-user').textContent = status.abs_user || '--';
                document.getElementById('abs-type').textContent = status.abs_user_type || '--';
                document.getElementById('uptime').textContent = status.uptime || '--';
                
                const statusEl = document.getElementById('abs-status');
                if (status.abs_connected) {
                    statusEl.textContent = 'Online';
                    statusEl.className = 'value online';
                } else {
                    statusEl.textContent = 'Offline';
                    statusEl.className = 'value offline';
                }
            } catch (e) {
                console.error('Failed to fetch status:', e);
            }
        }

        async function fetchConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                
                const serverForm = document.getElementById('server-form');
                serverForm.bookshelfURL.value = config.server?.bookshelfURL || '';
                serverForm.bookshelfToken.value = config.server?.bookshelfToken || '';
                
                const discordForm = document.getElementById('discord-form');
                discordForm.DISCORD_TOKEN.value = config.discord?.DISCORD_TOKEN || '';
                discordForm.CLIENT_ID.value = config.discord?.CLIENT_ID || '';

                const settingsForm = document.getElementById('settings-form');
                settingsForm.DEBUG_MODE.checked = config.settings?.DEBUG_MODE ?? false;
                settingsForm.MULTI_USER.checked = config.settings?.MULTI_USER ?? true;
                settingsForm.AUDIO_ENABLED.checked = config.settings?.AUDIO_ENABLED ?? true;
                settingsForm.OWNER_ONLY.checked = config.settings?.OWNER_ONLY ?? true;
                settingsForm.EPHEMERAL_OUTPUT.checked = config.settings?.EPHEMERAL_OUTPUT ?? true;
                settingsForm.FFMPEG_DEBUG.checked = config.settings?.FFMPEG_DEBUG ?? false;
                settingsForm.EXPERIMENTAL.checked = config.settings?.EXPERIMENTAL ?? false;
                settingsForm.INITIALIZED_MSG.checked = config.settings?.INITIALIZED_MSG ?? true;

                const dbForm = document.getElementById('database-form');
                dbForm.DB_TYPE.value = config.database?.DB_TYPE || 'sqlite';
                dbForm.DB_HOST.value = config.database?.DB_HOST || 'localhost';
                dbForm.DB_PORT.value = config.database?.DB_PORT || 3306;
                dbForm.DB_USER.value = config.database?.DB_USER || 'root';
                dbForm.DB_PASSWORD.value = config.database?.DB_PASSWORD || '';
                dbForm.DB_NAME.value = config.database?.DB_NAME || 'bookshelf';
                toggleMariaDBFields();
            } catch (e) {
                showToast('Failed to load config', 'error');
            }
        }

        // Save server config
        document.getElementById('server-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            try {
                const response = await fetch('/api/config/server', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bookshelfURL: form.bookshelfURL.value,
                        bookshelfToken: form.bookshelfToken.value
                    })
                });
                if (response.ok) showToast('Server settings saved', 'success');
                else throw new Error();
            } catch (e) {
                showToast('Failed to save', 'error');
            }
        });

        // Save discord config
        document.getElementById('discord-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            try {
                const response = await fetch('/api/config/discord', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        DISCORD_TOKEN: form.DISCORD_TOKEN.value,
                        CLIENT_ID: form.CLIENT_ID.value
                    })
                });
                if (response.ok) showToast('Discord settings saved', 'success');
                else throw new Error();
            } catch (e) {
                showToast('Failed to save', 'error');
            }
        });

        // Save bot settings
        document.getElementById('settings-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            try {
                const response = await fetch('/api/config/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        DEBUG_MODE: form.DEBUG_MODE.checked,
                        MULTI_USER: form.MULTI_USER.checked,
                        AUDIO_ENABLED: form.AUDIO_ENABLED.checked,
                        OWNER_ONLY: form.OWNER_ONLY.checked,
                        EPHEMERAL_OUTPUT: form.EPHEMERAL_OUTPUT.checked,
                        FFMPEG_DEBUG: form.FFMPEG_DEBUG.checked,
                        EXPERIMENTAL: form.EXPERIMENTAL.checked,
                        INITIALIZED_MSG: form.INITIALIZED_MSG.checked
                    })
                });
                if (response.ok) showToast('Bot settings saved', 'success');
                else throw new Error();
            } catch (e) {
                showToast('Failed to save settings', 'error');
            }
        });

        // Save database settings
        document.getElementById('database-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            try {
                const response = await fetch('/api/config/database', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        DB_TYPE: form.DB_TYPE.value,
                        DB_HOST: form.DB_HOST.value,
                        DB_PORT: parseInt(form.DB_PORT.value) || 3306,
                        DB_USER: form.DB_USER.value,
                        DB_PASSWORD: form.DB_PASSWORD.value,
                        DB_NAME: form.DB_NAME.value
                    })
                });
                if (response.ok) showToast('Database settings saved (restart required)', 'success');
                else throw new Error();
            } catch (e) {
                showToast('Failed to save database settings', 'error');
            }
        });

        // Toggle MariaDB fields visibility
        function toggleMariaDBFields() {
            const dbType = document.getElementById('db-type-select').value;
            const mariaFields = document.getElementById('mariadb-fields');
            mariaFields.style.display = dbType === 'mariadb' ? 'block' : 'none';
        }

        document.getElementById('db-type-select').addEventListener('change', toggleMariaDBFields);

        // Test ABS connection
        document.getElementById('test-abs-btn').addEventListener('click', async () => {
            const form = document.getElementById('server-form');
            const url = form.bookshelfURL.value;
            const token = form.bookshelfToken.value;
            
            if (!url || !token) {
                showToast('Enter URL and token first', 'warning');
                return;
            }
            
            showToast('Testing...', 'info');
            try {
                const response = await fetch('/api/test-abs-connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, token })
                });
                const result = await response.json();
                if (result.success) showToast('Connected as ' + result.user, 'success');
                else showToast('Failed: ' + result.error, 'error');
            } catch (e) {
                showToast('Connection failed', 'error');
            }
        });

        // Copy invite link
        document.getElementById('copy-invite-btn').addEventListener('click', () => {
            const clientId = document.getElementById('discord-form').CLIENT_ID.value;
            if (!clientId) {
                showToast('Enter Client ID first', 'warning');
                return;
            }
            const link = 'https://discord.com/oauth2/authorize?client_id=' + clientId + '&permissions=277062405120&integration_type=0&scope=bot';
            navigator.clipboard.writeText(link);
            showToast('Invite link copied', 'success');
        });

        // Refresh status
        document.getElementById('refresh-btn').addEventListener('click', () => {
            fetchStatus();
            showToast('Status refreshed', 'info');
        });

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            fetchConfig();
            fetchStatus();
            setInterval(fetchStatus, 30000);
        });
    </script>
</body>
</html>'''


# ============== API Routes ==============
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main dashboard"""
    return HTMLResponse(content=get_dashboard_html())


@app.get("/api/status")
async def get_status():
    """Get current bot status"""
    import settings

    abs_connected = False
    abs_user = None
    abs_user_type = None

    try:
        username, user_type, user_locked = await c.bookshelf_auth_test()
        abs_connected = True
        abs_user = username
        abs_user_type = user_type
    except Exception as e:
        logger.warning(f"Failed to get ABS status: {e}")

    uptime_delta = datetime.now() - startup_time
    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"

    return {
        "status": "running",
        "abs_connected": abs_connected,
        "abs_user": abs_user,
        "abs_user_type": abs_user_type,
        "version": settings.versionNumber,
        "uptime": uptime_str
    }


@app.get("/api/config")
async def get_config():
    """Get current configuration"""
    return load_current_config()


@app.post("/api/config/server")
async def save_server_config(config: ServerConfig):
    """Save server configuration to database"""
    try:
        await save_setting("bookshelfURL", config.bookshelfURL)
        await save_setting("bookshelfToken", config.bookshelfToken)
        return {"success": True, "message": "Server configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/discord")
async def save_discord_config(config: DiscordConfig):
    """Save Discord configuration to database"""
    try:
        await save_setting("DISCORD_TOKEN", config.DISCORD_TOKEN)
        await save_setting("CLIENT_ID", config.CLIENT_ID or "")
        return {"success": True, "message": "Discord configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/settings")
async def save_settings_config(config: SettingsConfig):
    """Save bot settings to database"""
    try:
        await save_setting("DEBUG_MODE", str(config.DEBUG_MODE))
        await save_setting("MULTI_USER", str(config.MULTI_USER))
        await save_setting("AUDIO_ENABLED", str(config.AUDIO_ENABLED))
        await save_setting("FFMPEG_DEBUG", str(config.FFMPEG_DEBUG))
        await save_setting("EXPERIMENTAL", str(config.EXPERIMENTAL))
        await save_setting("INITIALIZED_MSG", str(config.INITIALIZED_MSG))
        await save_setting("OWNER_ONLY", str(config.OWNER_ONLY))
        await save_setting("EPHEMERAL_OUTPUT", str(config.EPHEMERAL_OUTPUT))
        return {"success": True, "message": "Bot settings saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/database")
async def save_database_config(config: DatabaseConfig):
    """Save database configuration to database"""
    try:
        await save_setting("DB_TYPE", config.DB_TYPE)
        await save_setting("DB_HOST", config.DB_HOST)
        await save_setting("DB_PORT", str(config.DB_PORT))
        await save_setting("DB_USER", config.DB_USER)
        await save_setting("DB_PASSWORD", config.DB_PASSWORD)
        await save_setting("DB_NAME", config.DB_NAME)
        return {"success": True, "message": "Database configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/test-abs-connection")
async def test_abs_connection(request: TestConnectionRequest):
    """Test connection with custom URL and token"""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{request.url}/api/me?token={request.token}"
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "user": data.get("username", "Unknown"),
                    "user_type": data.get("type", "Unknown")
                }
            else:
                return {
                    "success": False,
                    "error": f"Server returned status {response.status_code}"
                }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def run_webui(host: str = "0.0.0.0", port: int = 8080):
    """Run the web UI server"""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_webui()