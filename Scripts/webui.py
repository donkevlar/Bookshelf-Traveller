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
DB_PATH = 'db/settings.db'

# Global state
startup_time = datetime.now()
db_instance = None


# ============== SQLite Implementation ==============
class SQLiteSettingsDB:
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


# ============== Database Factory ==============
def get_settings_db() -> SQLiteSettingsDB:
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
            "DB_TYPE": "sqlite",
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
    """Return the main dashboard HTML with tabbed settings and dynamic canvas recap"""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bookshelf Traveller</title>
    <link href="https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700;900&family=Open+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #161311;
            --bg-secondary: #211a15;
            --bg-card: #2a221b;
            --bg-input: #1c1713;
            --accent-primary: #c9a227;
            --accent-secondary: #e6be44;
            --accent-glow: rgba(201, 162, 39, 0.25);
            --text-primary: #f8f1ea;
            --text-secondary: #c9bdae;
            --text-muted: #8c7e70;
            --border-color: #3d3126;
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
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem 1.5rem;
        }

        .header {
            text-align: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }

        .header h1 {
            font-family: 'Merriweather', serif;
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent-primary);
            margin-bottom: 0.35rem;
            letter-spacing: -0.5px;
        }

        .header .version {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        /* Navigation Tabs */
        .tabs-nav {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1.75rem;
            background: var(--bg-secondary);
            padding: 0.4rem;
            border-radius: 10px;
            border: 1px solid var(--border-color);
        }

        .tab-btn {
            flex: 1;
            padding: 0.75rem 1rem;
            background: transparent;
            border: none;
            border-radius: 7px;
            color: var(--text-secondary);
            font-family: 'Open Sans', sans-serif;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            text-align: center;
        }

        .tab-btn:hover {
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.04);
        }

        .tab-btn.active {
            background: var(--accent-primary);
            color: var(--bg-primary);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
            animation: fadeIn 0.25s ease-in-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Status Grid */
        .status-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
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
            margin-bottom: 0.4rem;
        }

        .status-item .value {
            font-size: 1.15rem;
            font-weight: 600;
        }

        .status-item .value.online { color: var(--success); }
        .status-item .value.offline { color: var(--error); }

        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }

        .card-title {
            font-family: 'Merriweather', serif;
            font-size: 1.2rem;
            font-weight: 700;
            color: var(--accent-secondary);
            margin-bottom: 1.25rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
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
            font-family: inherit;
            font-size: 0.9rem;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        .form-help {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 0.35rem;
        }

        /* Presets and Date Controls */
        .preset-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 1.25rem;
        }

        .chip-btn {
            padding: 0.45rem 0.85rem;
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            color: var(--text-secondary);
            font-size: 0.8rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }

        .chip-btn:hover {
            border-color: var(--accent-primary);
            color: var(--text-primary);
        }

        .chip-btn.active {
            background: var(--accent-primary);
            color: var(--bg-primary);
            border-color: var(--accent-primary);
            font-weight: 600;
        }

        .date-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 1.25rem;
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.75rem 1.5rem;
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

        .btn-primary:hover:not(:disabled) {
            background: var(--accent-secondary);
            transform: translateY(-1px);
        }

        .btn-secondary {
            background: var(--bg-secondary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }

        .btn-secondary:hover:not(:disabled) {
            background: var(--border-color);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-group {
            display: flex;
            gap: 0.75rem;
            flex-wrap: wrap;
            margin-top: 1rem;
        }

        /* Summary Stats Cards */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }

        .summary-card {
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem 1.25rem;
            border-left: 3px solid var(--accent-primary);
        }

        .summary-card .summary-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.35rem;
        }

        .summary-card .summary-val {
            font-size: 1.35rem;
            font-weight: 700;
            color: var(--text-primary);
        }

        .summary-card .summary-sub {
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }

        /* Canvas Preview Container */
        .canvas-wrapper {
            display: flex;
            flex-direction: column;
            align-items: center;
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            margin-top: 1.5rem;
            position: relative;
        }

        #recap-canvas {
            max-width: 100%;
            height: auto;
            border-radius: 10px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
            display: block;
        }

        .canvas-toolbar {
            display: flex;
            gap: 0.75rem;
            margin-top: 1.5rem;
            flex-wrap: wrap;
            justify-content: center;
            width: 100%;
        }

        /* Toggle switch */
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

        @media (max-width: 650px) {
            .container { padding: 1rem; }
            .header h1 { font-size: 1.5rem; }
            .tabs-nav { flex-direction: column; }
            .btn-group, .canvas-toolbar { flex-direction: column; width: 100%; }
            .btn { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>Bookshelf Traveller</h1>
            <span class="version" id="version">Loading...</span>
        </header>

        <!-- Navigation Tabs -->
        <nav class="tabs-nav">
            <button class="tab-btn active" id="tab-btn-recap" onclick="switchTab('recap')">📊 Dynamic Listening Recap</button>
            <button class="tab-btn" id="tab-btn-settings" onclick="switchTab('settings')">⚙️ Server & Bot Settings</button>
        </nav>

        <!-- TAB 1: Dynamic Listening Recap -->
        <main id="tab-recap" class="tab-content active">
            <div class="card">
                <div class="card-title">
                    <span>Recap Timeframe</span>
                    <span style="font-size: 0.8rem; font-weight: normal; color: var(--text-muted);">Dynamic Canvas Generator</span>
                </div>

                <!-- Quick Presets -->
                <div class="preset-chips">
                    <button class="chip-btn" onclick="setPreset('7d', this)">Last 7 Days</button>
                    <button class="chip-btn active" onclick="setPreset('30d', this)">Last 30 Days</button>
                    <button class="chip-btn" onclick="setPreset('month', this)">This Month</button>
                    <button class="chip-btn" onclick="setPreset('90d', this)">Last 90 Days</button>
                    <button class="chip-btn" onclick="setPreset('ytd', this)">Year to Date</button>
                    <button class="chip-btn" onclick="setPreset('2025', this)">2025</button>
                    <button class="chip-btn" onclick="setPreset('2024', this)">2024</button>
                </div>

                <!-- Date Inputs -->
                <div class="date-row">
                    <div class="form-group" style="margin-bottom:0;">
                        <label class="form-label">Start Date</label>
                        <input type="date" class="form-input" id="recap-start">
                    </div>
                    <div class="form-group" style="margin-bottom:0;">
                        <label class="form-label">End Date</label>
                        <input type="date" class="form-input" id="recap-end">
                    </div>
                    <div class="form-group" style="margin-bottom:0;">
                        <label class="form-label">Recap Format</label>
                        <select class="form-input" id="recap-format" onchange="renderRecapCanvas()">
                            <option value="story">Story Poster (9:16)</option>
                            <option value="square">Square Card (1:1)</option>
                        </select>
                    </div>
                </div>

                <div class="btn-group">
                    <button type="button" class="btn btn-primary" id="btn-generate-recap" onclick="loadRecapData()">
                        ✨ Generate Dynamic Recap
                    </button>
                </div>
            </div>

            <!-- Summary Metrics Cards -->
            <section class="summary-grid" id="summary-section" style="display: none;">
                <div class="summary-card">
                    <div class="summary-label">Total Listening Time</div>
                    <div class="summary-val" id="metric-total-time">0h 0m</div>
                    <div class="summary-sub" id="metric-sessions">0 sessions recorded</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Days & Streak</div>
                    <div class="summary-val" id="metric-streak">0 days</div>
                    <div class="summary-sub" id="metric-active-days">0 active listening days</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Top Listening Day</div>
                    <div class="summary-val" id="metric-top-day">--</div>
                    <div class="summary-sub" id="metric-top-day-time">0h 0m</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Unique Titles</div>
                    <div class="summary-val" id="metric-books-count">0</div>
                    <div class="summary-sub" id="metric-top-author">--</div>
                </div>
            </section>

            <!-- HTML5 Canvas Preview -->
            <div class="card" id="recap-preview-card" style="display: none;">
                <div class="card-title">
                    <span>Generated Canvas Preview</span>
                    <span id="canvas-dim-label" style="font-size: 0.8rem; font-weight: normal; color: var(--text-muted);">1080 x 1920</span>
                </div>

                <div class="canvas-wrapper">
                    <canvas id="recap-canvas" width="1080" height="1920" style="max-width: 380px;"></canvas>
                    <div class="canvas-toolbar">
                        <button class="btn btn-primary" id="btn-download-canvas" onclick="downloadRecapPNG()">
                            💾 Download Image (PNG)
                        </button>
                        <button class="btn btn-secondary" id="btn-copy-canvas" onclick="copyRecapCanvasImage()">
                            📋 Copy Image to Clipboard
                        </button>
                    </div>
                </div>
            </div>
        </main>

        <!-- TAB 2: Settings & Status -->
        <main id="tab-settings" class="tab-content">
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
                            <span class="toggle-title">Audio Playback</span>
                            <span class="toggle-desc">Enable Discord voice channel playback</span>
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
                            <span class="toggle-desc">Only show bot responses to the user</span>
                        </div>
                        <label class="toggle">
                            <input type="checkbox" name="EPHEMERAL_OUTPUT">
                            <span class="toggle-slider"></span>
                        </label>
                    </div>

                    <div class="toggle-group">
                        <div class="toggle-info">
                            <span class="toggle-title">FFmpeg Debug</span>
                            <span class="toggle-desc">Log FFmpeg output to file</span>
                        </div>
                        <label class="toggle">
                            <input type="checkbox" name="FFMPEG_DEBUG">
                            <span class="toggle-slider"></span>
                        </label>
                    </div>

                    <div class="toggle-group">
                        <div class="toggle-info">
                            <span class="toggle-title">Experimental Features</span>
                            <span class="toggle-desc">Enable beta functionality</span>
                        </div>
                        <label class="toggle">
                            <input type="checkbox" name="EXPERIMENTAL">
                            <span class="toggle-slider"></span>
                        </label>
                    </div>

                    <div class="toggle-group">
                        <div class="toggle-info">
                            <span class="toggle-title">Startup DM</span>
                            <span class="toggle-desc">Send notification on bot start</span>
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
        </main>
    </div>

    <!-- Toast Notifications -->
    <div class="toast-container" id="toast-container"></div>

    <script>
        // Global state
        let currentRecapData = null;
        let coverImageCache = new Map();

        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;
            toast.textContent = message;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 4000);
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

            const targetTab = document.getElementById('tab-' + tabId);
            const targetBtn = document.getElementById('tab-btn-' + tabId);
            if (targetTab) targetTab.classList.add('active');
            if (targetBtn) targetBtn.classList.add('active');
        }

        // Format dates as YYYY-MM-DD
        function formatDateISO(d) {
            return d.toISOString().split('T')[0];
        }

        // Preset ranges
        function setPreset(type, buttonEl) {
            if (buttonEl) {
                document.querySelectorAll('.chip-btn').forEach(btn => btn.classList.remove('active'));
                buttonEl.classList.add('active');
            }

            const now = new Date();
            let start = new Date();
            let end = new Date();

            if (type === '7d') {
                start.setDate(now.getDate() - 7);
            } else if (type === '30d') {
                start.setDate(now.getDate() - 30);
            } else if (type === 'month') {
                start = new Date(now.getFullYear(), now.getMonth(), 1);
            } else if (type === '90d') {
                start.setDate(now.getDate() - 90);
            } else if (type === 'ytd') {
                start = new Date(now.getFullYear(), 0, 1);
            } else if (type === '2025') {
                start = new Date(2025, 0, 1);
                end = new Date(2025, 11, 31);
            } else if (type === '2024') {
                start = new Date(2024, 0, 1);
                end = new Date(2024, 11, 31);
            }

            document.getElementById('recap-start').value = formatDateISO(start);
            document.getElementById('recap-end').value = formatDateISO(end);
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
            } catch (e) {
                showToast('Failed to load config', 'error');
            }
        }

        // Load Listening Recap Data from API
        async function loadRecapData() {
            const startDate = document.getElementById('recap-start').value;
            const endDate = document.getElementById('recap-end').value;
            const btn = document.getElementById('btn-generate-recap');

            if (!startDate || !endDate) {
                showToast('Please select both start and end dates', 'warning');
                return;
            }

            btn.disabled = true;
            btn.textContent = '⏳ Fetching Sessions...';
            showToast('Fetching listening data from Audiobookshelf...', 'info');

            try {
                const query = new URLSearchParams({ start_date: startDate, end_date: endDate });
                const res = await fetch('/api/recap?' + query.toString());
                if (!res.ok) throw new Error('API returned ' + res.status);
                
                const data = await res.json();
                currentRecapData = data;

                // Update summary cards
                document.getElementById('metric-total-time').textContent = data.timeFormatted?.display || '0h 0m';
                document.getElementById('metric-sessions').textContent = `${data.totalSessions} sessions recorded`;
                document.getElementById('metric-streak').textContent = `${data.streak} day streak`;
                document.getElementById('metric-active-days').textContent = `${data.daysListened} active listening days`;
                document.getElementById('metric-top-day').textContent = data.topDay?.date || '--';
                document.getElementById('metric-top-day-time').textContent = data.topDay?.formattedTime || '0h 0m';
                document.getElementById('metric-books-count').textContent = data.uniqueBooksCount || 0;
                document.getElementById('metric-top-author').textContent = data.topAuthors?.[0]?.name ? `Top Author: ${data.topAuthors[0].name}` : 'No authors recorded';

                document.getElementById('summary-section').style.display = 'grid';
                document.getElementById('recap-preview-card').style.display = 'block';

                // Preload covers and render canvas
                await preloadBookCovers(data.topBooks || []);
                renderRecapCanvas();
                showToast('Recap generated successfully!', 'success');
            } catch (err) {
                console.error(err);
                showToast('Failed to fetch recap stats: ' + err.message, 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = '✨ Generate Dynamic Recap';
            }
        }

        async function preloadBookCovers(topBooks) {
            for (const book of topBooks) {
                if (book.id && !coverImageCache.has(book.id)) {
                    const img = new Image();
                    img.crossOrigin = "anonymous";
                    const loadPromise = new Promise((resolve) => {
                        img.onload = () => resolve(img);
                        img.onerror = () => resolve(null);
                    });
                    img.src = `/api/cover-proxy?item_id=${encodeURIComponent(book.id)}`;
                    const loaded = await loadPromise;
                    if (loaded) coverImageCache.set(book.id, loaded);
                }
            }
        }

        // Helper to draw rounded rect with cross-browser fallback
        function drawRoundedRect(ctx, x, y, width, height, radius) {
            if (ctx.roundRect) {
                ctx.beginPath();
                ctx.roundRect(x, y, width, height, radius);
                return;
            }
            ctx.beginPath();
            ctx.moveTo(x + radius, y);
            ctx.lineTo(x + width - radius, y);
            ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
            ctx.lineTo(x + width, y + height - radius);
            ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
            ctx.lineTo(x + radius, y + height);
            ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
            ctx.lineTo(x, y + radius);
            ctx.quadraticCurveTo(x, y, x + radius, y);
            ctx.closePath();
        }

        // HTML5 Canvas Rendering Engine
        function renderRecapCanvas() {
            if (!currentRecapData) return;
            const data = currentRecapData;
            const canvas = document.getElementById('recap-canvas');
            const ctx = canvas.getContext('2d');
            const format = document.getElementById('recap-format').value;

            if (format === 'square') {
                canvas.width = 1080;
                canvas.height = 1080;
                document.getElementById('canvas-dim-label').textContent = '1080 x 1080 (Square)';
                canvas.style.maxWidth = '420px';
            } else {
                canvas.width = 1080;
                canvas.height = 1920;
                document.getElementById('canvas-dim-label').textContent = '1080 x 1920 (Story Poster)';
                canvas.style.maxWidth = '360px';
            }

            const W = canvas.width;
            const H = canvas.height;

            // 1. Background Gradient
            const bgGrad = ctx.createLinearGradient(0, 0, W, H);
            bgGrad.addColorStop(0, '#161311');
            bgGrad.addColorStop(0.5, '#231b14');
            bgGrad.addColorStop(1, '#0e0c0b');
            ctx.fillStyle = bgGrad;
            ctx.fillRect(0, 0, W, H);

            // Ambient Gold Orbs
            const glow1 = ctx.createRadialGradient(W * 0.85, H * 0.15, 20, W * 0.85, H * 0.15, 450);
            glow1.addColorStop(0, 'rgba(201, 162, 39, 0.22)');
            glow1.addColorStop(1, 'rgba(201, 162, 39, 0)');
            ctx.fillStyle = glow1;
            ctx.fillRect(0, 0, W, H);

            const glow2 = ctx.createRadialGradient(W * 0.15, H * 0.85, 30, W * 0.15, H * 0.85, 500);
            glow2.addColorStop(0, 'rgba(230, 190, 68, 0.12)');
            glow2.addColorStop(1, 'rgba(230, 190, 68, 0)');
            ctx.fillStyle = glow2;
            ctx.fillRect(0, 0, W, H);

            // Decorative top border
            const barGrad = ctx.createLinearGradient(60, 0, W - 60, 0);
            barGrad.addColorStop(0, '#c9a227');
            barGrad.addColorStop(0.5, '#f5e49b');
            barGrad.addColorStop(1, '#c9a227');
            ctx.fillStyle = barGrad;
            ctx.fillRect(70, 60, W - 140, 6);

            // 2. Header
            ctx.fillStyle = '#c9a227';
            ctx.font = '700 32px "Open Sans", sans-serif';
            ctx.fillText('BOOKSHELF TRAVELLER', 70, 120);

            // Timeframe badge
            const startStr = data.timeframe?.startDate || '';
            const endStr = data.timeframe?.endDate || '';
            const dateBadge = `${startStr}  →  ${endStr}`;

            ctx.font = '600 24px "Open Sans", sans-serif';
            const badgeW = ctx.measureText(dateBadge).width + 36;
            drawRoundedRect(ctx, W - 70 - badgeW, 90, badgeW, 44, 22);
            ctx.fillStyle = 'rgba(201, 162, 39, 0.15)';
            ctx.fill();
            ctx.strokeStyle = 'rgba(201, 162, 39, 0.4)';
            ctx.lineWidth = 1.5;
            ctx.stroke();

            ctx.fillStyle = '#f8f1ea';
            ctx.fillText(dateBadge, W - 70 - badgeW + 18, 120);

            // Main Title
            ctx.font = '900 68px "Merriweather", serif';
            ctx.fillStyle = '#ffffff';
            ctx.fillText('Listening Recap', 70, 210);

            // 3. Hero Listening Time Card
            const heroY = 250;
            const heroH = format === 'square' ? 170 : 200;
            drawRoundedRect(ctx, 70, heroY, W - 140, heroH, 20);
            ctx.fillStyle = 'rgba(42, 34, 27, 0.85)';
            ctx.fill();
            ctx.strokeStyle = 'rgba(61, 49, 38, 0.9)';
            ctx.lineWidth = 2;
            ctx.stroke();

            ctx.fillStyle = '#c9bdae';
            ctx.font = '600 24px "Open Sans", sans-serif';
            ctx.fillText('TOTAL LISTENING TIME', 110, heroY + 50);

            ctx.fillStyle = '#c9a227';
            ctx.font = '900 78px "Merriweather", serif';
            const timeStr = data.timeFormatted?.display || '0h 0m';
            ctx.fillText(timeStr, 110, heroY + 130);

            // Total Sessions Subtext
            ctx.fillStyle = '#8c7e70';
            ctx.font = '500 22px "Open Sans", sans-serif';
            ctx.fillText(`Across ${data.totalSessions} sessions · ${data.daysListened} active days · ${data.streak}d streak`, 110, heroY + 170);

            if (format === 'story') {
                // 4. Top Books Section
                let bookY = heroY + heroH + 50;
                ctx.fillStyle = '#f8f1ea';
                ctx.font = '700 36px "Merriweather", serif';
                ctx.fillText('Top Audiobooks', 70, bookY);

                bookY += 25;
                const topBooks = (data.topBooks || []).slice(0, 3);
                const bookCardH = 175;

                if (topBooks.length === 0) {
                    drawRoundedRect(ctx, 70, bookY + 10, W - 140, 100, 14);
                    ctx.fillStyle = 'rgba(42, 34, 27, 0.6)';
                    ctx.fill();
                    ctx.fillStyle = '#8c7e70';
                    ctx.font = '500 24px "Open Sans", sans-serif';
                    ctx.fillText('No sessions recorded in this timeframe.', 110, bookY + 70);
                    bookY += 130;
                } else {
                    topBooks.forEach((book, idx) => {
                        const curY = bookY + (idx * (bookCardH + 20)) + 15;

                        // Card background
                        drawRoundedRect(ctx, 70, curY, W - 140, bookCardH, 16);
                        ctx.fillStyle = 'rgba(33, 26, 21, 0.85)';
                        ctx.fill();
                        ctx.strokeStyle = 'rgba(61, 49, 38, 0.8)';
                        ctx.lineWidth = 1.5;
                        ctx.stroke();

                        // Cover Art
                        const coverImg = coverImageCache.get(book.id);
                        const coverX = 90;
                        const coverY = curY + 15;
                        const coverW = 100;
                        const coverH = 145;

                        if (coverImg) {
                            ctx.save();
                            drawRoundedRect(ctx, coverX, coverY, coverW, coverH, 8);
                            ctx.clip();
                            ctx.drawImage(coverImg, coverX, coverY, coverW, coverH);
                            ctx.restore();
                        } else {
                            drawRoundedRect(ctx, coverX, coverY, coverW, coverH, 8);
                            ctx.fillStyle = '#2a221b';
                            ctx.fill();
                            ctx.fillStyle = '#c9a227';
                            ctx.font = '700 32px "Open Sans", sans-serif';
                            ctx.fillText('📖', coverX + 32, coverY + 80);
                        }

                        // Rank number badge
                        drawRoundedRect(ctx, coverX - 8, coverY - 8, 30, 30, 15);
                        ctx.fillStyle = '#c9a227';
                        ctx.fill();
                        ctx.fillStyle = '#161311';
                        ctx.font = '700 18px "Open Sans", sans-serif';
                        ctx.fillText(`${idx + 1}`, coverX + 2, coverY + 14);

                        // Book Title & Author
                        const textX = coverX + coverW + 30;
                        ctx.fillStyle = '#ffffff';
                        ctx.font = '700 28px "Open Sans", sans-serif';
                        const titleText = book.title?.length > 34 ? book.title.substring(0, 32) + '...' : (book.title || 'Unknown');
                        ctx.fillText(titleText, textX, curY + 55);

                        ctx.fillStyle = '#c9bdae';
                        ctx.font = '500 22px "Open Sans", sans-serif';
                        const authorText = book.author?.length > 38 ? book.author.substring(0, 36) + '...' : (book.author || 'Unknown');
                        ctx.fillText(authorText, textX, curY + 92);

                        // Time listened pill
                        const pillText = `⏱️ ${book.formattedTime || '00:00:00'}`;
                        ctx.font = '600 20px "Open Sans", sans-serif';
                        const pillW = ctx.measureText(pillText).width + 28;
                        drawRoundedRect(ctx, textX, curY + 112, pillW, 36, 18);
                        ctx.fillStyle = 'rgba(201, 162, 39, 0.2)';
                        ctx.fill();
                        ctx.fillStyle = '#e6be44';
                        ctx.fillText(pillText, textX + 14, curY + 137);
                    });

                    bookY += (topBooks.length * (bookCardH + 20)) + 20;
                }

                // 5. Highlights Grid (Streak, Authors, Genres)
                const gridY = bookY + 10;
                const halfW = (W - 160) / 2;

                // Left: Top Authors
                drawRoundedRect(ctx, 70, gridY, halfW, 260, 16);
                ctx.fillStyle = 'rgba(33, 26, 21, 0.85)';
                ctx.fill();
                ctx.strokeStyle = 'rgba(61, 49, 38, 0.8)';
                ctx.stroke();

                ctx.fillStyle = '#c9a227';
                ctx.font = '700 24px "Open Sans", sans-serif';
                ctx.fillText('TOP AUTHORS', 95, gridY + 45);

                const authors = (data.topAuthors || []).slice(0, 3);
                if (authors.length === 0) {
                    ctx.fillStyle = '#8c7e70';
                    ctx.font = '500 20px "Open Sans", sans-serif';
                    ctx.fillText('No authors recorded', 95, gridY + 100);
                } else {
                    authors.forEach((a, i) => {
                        ctx.fillStyle = '#ffffff';
                        ctx.font = '600 22px "Open Sans", sans-serif';
                        const aName = a.name.length > 20 ? a.name.substring(0, 18) + '...' : a.name;
                        ctx.fillText(`${i + 1}. ${aName}`, 95, gridY + 95 + (i * 50));
                        ctx.fillStyle = '#8c7e70';
                        ctx.font = '500 18px "Open Sans", sans-serif';
                        ctx.fillText(a.formattedTime, 95, gridY + 118 + (i * 50));
                    });
                }

                // Right: Milestones & Streaks
                drawRoundedRect(ctx, 70 + halfW + 20, gridY, halfW, 260, 16);
                ctx.fillStyle = 'rgba(33, 26, 21, 0.85)';
                ctx.fill();
                ctx.strokeStyle = 'rgba(61, 49, 38, 0.8)';
                ctx.stroke();

                ctx.fillStyle = '#c9a227';
                ctx.font = '700 24px "Open Sans", sans-serif';
                ctx.fillText('HIGHLIGHTS', 95 + halfW + 20, gridY + 45);

                ctx.fillStyle = '#ffffff';
                ctx.font = '600 22px "Open Sans", sans-serif';
                ctx.fillText(`🔥 ${data.streak} Day Streak`, 95 + halfW + 20, gridY + 95);
                ctx.fillStyle = '#8c7e70';
                ctx.font = '500 18px "Open Sans", sans-serif';
                ctx.fillText(`Consecutive listening record`, 95 + halfW + 20, gridY + 118);

                ctx.fillStyle = '#ffffff';
                ctx.font = '600 22px "Open Sans", sans-serif';
                ctx.fillText(`🌟 Peak Day: ${data.topDay?.date || '--'}`, 95 + halfW + 20, gridY + 165);
                ctx.fillStyle = '#8c7e70';
                ctx.font = '500 18px "Open Sans", sans-serif';
                ctx.fillText(`${data.topDay?.formattedTime || '0h 0m'} listened`, 95 + halfW + 20, gridY + 188);

                // Watermark footer
                ctx.fillStyle = '#6e6153';
                ctx.font = '500 20px "Open Sans", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('Generated by Bookshelf Traveller · Connected to Audiobookshelf', W / 2, H - 45);
                ctx.textAlign = 'left';

            } else {
                // Square format (1:1)
                const bookY = heroY + heroH + 35;
                const topBooks = (data.topBooks || []).slice(0, 2);

                drawRoundedRect(ctx, 70, bookY, W - 140, 360, 16);
                ctx.fillStyle = 'rgba(33, 26, 21, 0.85)';
                ctx.fill();
                ctx.strokeStyle = 'rgba(61, 49, 38, 0.8)';
                ctx.stroke();

                ctx.fillStyle = '#c9a227';
                ctx.font = '700 28px "Open Sans", sans-serif';
                ctx.fillText('TOP AUDIOBOOKS & AUTHORS', 100, bookY + 45);

                topBooks.forEach((book, idx) => {
                    const rowY = bookY + 70 + (idx * 115);
                    const coverImg = coverImageCache.get(book.id);
                    const coverW = 65;
                    const coverH = 95;

                    if (coverImg) {
                        ctx.save();
                        drawRoundedRect(ctx, 100, rowY, coverW, coverH, 6);
                        ctx.clip();
                        ctx.drawImage(coverImg, 100, rowY, coverW, coverH);
                        ctx.restore();
                    } else {
                        drawRoundedRect(ctx, 100, rowY, coverW, coverH, 6);
                        ctx.fillStyle = '#2a221b';
                        ctx.fill();
                    }

                    ctx.fillStyle = '#ffffff';
                    ctx.font = '700 24px "Open Sans", sans-serif';
                    const t = book.title?.length > 40 ? book.title.substring(0, 38) + '...' : book.title;
                    ctx.fillText(`${idx + 1}. ${t}`, 185, rowY + 35);

                    ctx.fillStyle = '#c9bdae';
                    ctx.font = '500 20px "Open Sans", sans-serif';
                    ctx.fillText(`${book.author} · ${book.formattedTime}`, 185, rowY + 68);
                });

                // Streak banner
                const streakY = bookY + 390;
                drawRoundedRect(ctx, 70, streakY, W - 140, 100, 16);
                ctx.fillStyle = 'rgba(201, 162, 39, 0.15)';
                ctx.fill();
                ctx.strokeStyle = 'rgba(201, 162, 39, 0.4)';
                ctx.stroke();

                ctx.fillStyle = '#e6be44';
                ctx.font = '700 26px "Open Sans", sans-serif';
                ctx.fillText(`🔥 ${data.streak} Day Streak · 🌟 Peak Day: ${data.topDay?.date || '--'} (${data.topDay?.formattedTime || '0h 0m'})`, 105, streakY + 60);

                ctx.fillStyle = '#6e6153';
                ctx.font = '500 18px "Open Sans", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('Generated by Bookshelf Traveller', W / 2, H - 30);
                ctx.textAlign = 'left';
            }
        }

        // Download Canvas as PNG
        function downloadRecapPNG() {
            const canvas = document.getElementById('recap-canvas');
            const link = document.createElement('a');
            const start = document.getElementById('recap-start').value || 'start';
            const end = document.getElementById('recap-end').value || 'end';
            link.download = `listening-recap-${start}-to-${end}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
            showToast('Recap image saved to downloads!', 'success');
        }

        // Copy Canvas to Clipboard
        async function copyRecapCanvasImage() {
            const canvas = document.getElementById('recap-canvas');
            try {
                canvas.toBlob(async (blob) => {
                    if (!blob) throw new Error('Blob conversion failed');
                    await navigator.clipboard.write([
                        new ClipboardItem({ 'image/png': blob })
                    ]);
                    showToast('Recap image copied to clipboard!', 'success');
                });
            } catch (err) {
                console.error(err);
                showToast('Clipboard copy not supported by your browser', 'warning');
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

        async function copyToClipboard(text) {
            if (navigator.clipboard && window.isSecureContext) {
                try {
                    await navigator.clipboard.writeText(text);
                    return true;
                } catch (err) {
                    console.warn('navigator.clipboard.writeText failed', err);
                }
            }
            try {
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'fixed';
                textArea.style.top = '0';
                textArea.style.left = '0';
                textArea.style.width = '2em';
                textArea.style.height = '2em';
                textArea.style.padding = '0';
                textArea.style.border = 'none';
                textArea.style.outline = 'none';
                textArea.style.boxShadow = 'none';
                textArea.style.background = 'transparent';
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                const successful = document.execCommand('copy');
                document.body.removeChild(textArea);
                return successful;
            } catch (err) {
                console.error('Fallback copy failed', err);
                return false;
            }
        }

        // Copy invite link
        document.getElementById('copy-invite-btn').addEventListener('click', async () => {
            const clientId = document.getElementById('discord-form').CLIENT_ID.value.trim();
            if (!clientId) {
                showToast('Enter Client ID first', 'warning');
                return;
            }
            const link = 'https://discord.com/oauth2/authorize?client_id=' + encodeURIComponent(clientId) + '&permissions=277062405120&integration_type=0&scope=bot';
            const copied = await copyToClipboard(link);
            if (copied) {
                showToast('Invite link copied', 'success');
            } else {
                prompt('Copy this invite link:', link);
            }
        });

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            setPreset('30d');
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
        await save_setting("DB_TYPE", "sqlite")
        return {"success": True, "message": "Database configuration saved (SQLite active)"}
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


def _parse_date_to_ms(val: Optional[str], is_end: bool = False) -> Optional[int]:
    """Helper to convert YYYY-MM-DD or ms string to epoch milliseconds."""
    if not val:
        return None
    val = val.strip()
    if val.isdigit():
        ival = int(val)
        return ival * 1000 if ival < 10000000000 else ival
    try:
        dt = datetime.strptime(val, "%Y-%m-%d")
        if is_end:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999000)
        return int(dt.timestamp() * 1000)
    except Exception:
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return None


@app.get("/api/recap")
async def get_recap(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """
    Get aggregated listening stats and recap metrics for an arbitrary date range.
    """
    start_ms = _parse_date_to_ms(start_date, is_end=False)
    end_ms = _parse_date_to_ms(end_date, is_end=True)

    try:
        stats = await c.get_custom_listening_stats(start_time_ms=start_ms, end_time_ms=end_ms)
        return stats
    except Exception as e:
        logger.error(f"Failed to generate recap stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cover-proxy")
async def cover_proxy(item_id: str):
    """
    Proxy Audiobookshelf cover images to allow client-side canvas rendering without CORS issues.
    """
    import httpx
    from fastapi.responses import Response

    server_url = os.getenv("bookshelfURL", "").rstrip("/")
    token = os.getenv("bookshelfToken", "")
    if not server_url or not item_id:
        raise HTTPException(status_code=400, detail="Missing server URL or item ID")

    url = f"{server_url}/api/items/{item_id}/cover?token={token}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            if r.status_code == 200:
                content_type = r.headers.get("content-type", "image/jpeg")
                return Response(
                    content=r.content,
                    media_type=content_type,
                    headers={"Cache-Control": "public, max-age=86400"}
                )
            else:
                raise HTTPException(status_code=r.status_code, detail="Cover not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to proxy cover for {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def run_webui(host: str = "0.0.0.0", port: int = 8080):
    """Run the web UI server"""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_webui()