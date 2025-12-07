"""
Bookshelf Traveller Web UI
A FastAPI-based management interface for the Discord bot
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from dotenv import load_dotenv, set_key, dotenv_values

import bookshelfAPI as c

# Logger Config
logger = logging.getLogger("webui")

# Load environment variables
load_dotenv()

# Configuration file path
ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')
if not os.path.exists(ENV_FILE):
    ENV_FILE = '.env'

# Database paths
DB_DIR = 'db'


# Pydantic Models for API
class ServerConfig(BaseModel):
    bookshelfURL: str = Field(..., description="Audiobookshelf server URL")
    bookshelfToken: str = Field(..., description="Audiobookshelf API token")
    OPT_IMAGE_URL: Optional[str] = Field("", description="Optional image URL for covers")
    DEFAULT_PROVIDER: str = Field("audible", description="Default search provider")
    TIMEZONE: str = Field("America/Toronto", description="Timezone for timestamps")


class DiscordConfig(BaseModel):
    DISCORD_TOKEN: str = Field(..., description="Discord bot token")
    CLIENT_ID: Optional[str] = Field("", description="Discord client ID for invite link")
    OWNER_ONLY: bool = Field(True, description="Restrict commands to bot owner")
    PLAYBACK_ROLE: Optional[str] = Field("", description="Role ID for playback control")
    EPHEMERAL_OUTPUT: bool = Field(True, description="Make command outputs ephemeral")


class BotConfig(BaseModel):
    DEBUG_MODE: bool = Field(False, description="Enable debug mode")
    MULTI_USER: bool = Field(True, description="Enable multi-user support")
    AUDIO_ENABLED: bool = Field(True, description="Enable audio playback")
    FFMPEG_DEBUG: bool = Field(False, description="Enable FFmpeg debug logging")
    EXPERIMENTAL: bool = Field(False, description="Enable experimental features")
    INITIALIZED_MSG: bool = Field(True, description="Send initialization message")


class TaskConfig(BaseModel):
    TASK_FREQUENCY: int = Field(5, description="Task execution interval in minutes")
    UPDATES: int = Field(5, description="Session update frequency in seconds")


class DatabaseConfig(BaseModel):
    DB_TYPE: str = Field("sqlite", description="Database type: sqlite or mariadb")
    DB_HOST: str = Field("localhost", description="Database host (MariaDB only)")
    DB_PORT: int = Field(3306, description="Database port (MariaDB only)")
    DB_USER: str = Field("root", description="Database user (MariaDB only)")
    DB_PASSWORD: str = Field("", description="Database password (MariaDB only)")
    DB_NAME: str = Field("bookshelf", description="Database name (MariaDB only)")


class FullConfig(BaseModel):
    server: ServerConfig
    discord: DiscordConfig
    bot: BotConfig
    tasks: TaskConfig
    database: DatabaseConfig


class StatusResponse(BaseModel):
    status: str
    abs_connected: bool
    abs_user: Optional[str]
    abs_user_type: Optional[str]
    version: str
    uptime: Optional[str]


class TestConnectionRequest(BaseModel):
    url: str
    token: str


# Global state
startup_time = datetime.now()
bot_instance = None


def get_env_value(key: str, default: str = "") -> str:
    """Get environment variable value"""
    return os.getenv(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean environment variable"""
    value = os.getenv(key, str(default)).lower()
    return value in ("1", "true", "yes")


def save_env_value(key: str, value: str) -> bool:
    """Save a value to the .env file"""
    try:
        # Ensure the .env file exists
        if not os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'w') as f:
                f.write("")
        
        set_key(ENV_FILE, key, value)
        os.environ[key] = value
        return True
    except Exception as e:
        logger.error(f"Failed to save env value {key}: {e}")
        return False


def load_current_config() -> Dict[str, Any]:
    """Load current configuration from environment"""
    return {
        "server": {
            "bookshelfURL": get_env_value("bookshelfURL", ""),
            "bookshelfToken": get_env_value("bookshelfToken", ""),
            "OPT_IMAGE_URL": get_env_value("OPT_IMAGE_URL", ""),
            "DEFAULT_PROVIDER": get_env_value("DEFAULT_PROVIDER", "audible"),
            "TIMEZONE": get_env_value("TIMEZONE", "America/Toronto"),
        },
        "discord": {
            "DISCORD_TOKEN": get_env_value("DISCORD_TOKEN", ""),
            "CLIENT_ID": get_env_value("CLIENT_ID", ""),
            "OWNER_ONLY": get_env_bool("OWNER_ONLY", True),
            "PLAYBACK_ROLE": get_env_value("PLAYBACK_ROLE", ""),
            "EPHEMERAL_OUTPUT": get_env_bool("EPHEMERAL_OUTPUT", True),
        },
        "bot": {
            "DEBUG_MODE": get_env_bool("DEBUG_MODE", False),
            "MULTI_USER": get_env_bool("MULTI_USER", True),
            "AUDIO_ENABLED": get_env_bool("AUDIO_ENABLED", True),
            "FFMPEG_DEBUG": get_env_bool("FFMPEG_DEBUG", False),
            "EXPERIMENTAL": get_env_bool("EXPERIMENTAL", False),
            "INITIALIZED_MSG": get_env_bool("INITIALIZED_MSG", True),
        },
        "tasks": {
            "TASK_FREQUENCY": int(get_env_value("TASK_FREQUENCY", "5")),
            "UPDATES": int(get_env_value("UPDATES", "5")),
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


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    logger.info("Starting Bookshelf Traveller Web UI...")
    yield
    logger.info("Shutting down Web UI...")


# Create FastAPI app
app = FastAPI(
    title="Bookshelf Traveller Admin",
    description="Web management interface for Bookshelf Traveller Discord Bot",
    version="1.0.0",
    lifespan=lifespan
)


# HTML Template (embedded for simplicity)
def get_dashboard_html() -> str:
    """Return the main dashboard HTML"""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bookshelf Traveller Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-tertiary: #1a1a25;
            --bg-card: #15151f;
            --accent-primary: #7c3aed;
            --accent-secondary: #a855f7;
            --accent-glow: rgba(124, 58, 237, 0.3);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --border-color: #2d2d3a;
            --success: #22c55e;
            --warning: #f59e0b;
            --error: #ef4444;
            --info: #3b82f6;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* Animated background */
        .bg-pattern {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(ellipse at 20% 20%, rgba(124, 58, 237, 0.1) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 80%, rgba(168, 85, 247, 0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 50% 50%, rgba(59, 130, 246, 0.05) 0%, transparent 70%);
            pointer-events: none;
            z-index: 0;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
            position: relative;
            z-index: 1;
        }

        /* Header */
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 3rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .logo-icon {
            width: 48px;
            height: 48px;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            box-shadow: 0 4px 20px var(--accent-glow);
        }

        .logo-text h1 {
            font-size: 1.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--text-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .logo-text span {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }

        .header-actions {
            display: flex;
            gap: 1rem;
        }

        /* Status Badge */
        .status-badge {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: var(--bg-tertiary);
            border-radius: 9999px;
            font-size: 0.875rem;
            border: 1px solid var(--border-color);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }

        .status-dot.online { background: var(--success); }
        .status-dot.offline { background: var(--error); }
        .status-dot.warning { background: var(--warning); }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* Navigation Tabs */
        .nav-tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            background: var(--bg-secondary);
            padding: 0.5rem;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            overflow-x: auto;
        }

        .nav-tab {
            padding: 0.75rem 1.5rem;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-family: 'Outfit', sans-serif;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            border-radius: 8px;
            transition: all 0.2s ease;
            white-space: nowrap;
        }

        .nav-tab:hover {
            color: var(--text-primary);
            background: var(--bg-tertiary);
        }

        .nav-tab.active {
            background: var(--accent-primary);
            color: white;
            box-shadow: 0 2px 10px var(--accent-glow);
        }

        /* Content Sections */
        .tab-content {
            display: none;
            animation: fadeIn 0.3s ease;
        }

        .tab-content.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Cards */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            transition: all 0.3s ease;
        }

        .card:hover {
            border-color: var(--accent-primary);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }

        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border-color);
        }

        .card-title {
            font-size: 1.1rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .card-title .icon {
            width: 32px;
            height: 32px;
            background: var(--bg-tertiary);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
        }

        /* Form Elements */
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .form-label {
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .form-label .required {
            color: var(--error);
        }

        .form-input {
            padding: 0.75rem 1rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
            transition: all 0.2s ease;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        .form-input::placeholder {
            color: var(--text-muted);
        }

        .form-input[type="password"] {
            letter-spacing: 0.1em;
        }

        .form-select {
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 0.75rem center;
            background-size: 1rem;
            padding-right: 2.5rem;
        }

        .form-help {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 0.25rem;
        }

        /* Toggle Switch */
        .toggle-group {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem;
            background: var(--bg-tertiary);
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }

        .toggle-label {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }

        .toggle-label .title {
            font-weight: 500;
            font-size: 0.9rem;
        }

        .toggle-label .desc {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .toggle {
            position: relative;
            width: 48px;
            height: 26px;
        }

        .toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: var(--border-color);
            border-radius: 9999px;
            transition: all 0.3s ease;
        }

        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 20px;
            width: 20px;
            left: 3px;
            bottom: 3px;
            background: white;
            border-radius: 50%;
            transition: all 0.3s ease;
        }

        .toggle input:checked + .toggle-slider {
            background: var(--accent-primary);
        }

        .toggle input:checked + .toggle-slider:before {
            transform: translateX(22px);
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-family: 'Outfit', sans-serif;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            color: white;
            box-shadow: 0 2px 10px var(--accent-glow);
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 20px var(--accent-glow);
        }

        .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }

        .btn-secondary:hover {
            background: var(--border-color);
        }

        .btn-danger {
            background: var(--error);
            color: white;
        }

        .btn-danger:hover {
            background: #dc2626;
        }

        .btn-success {
            background: var(--success);
            color: white;
        }

        .btn-group {
            display: flex;
            gap: 1rem;
            margin-top: 1.5rem;
        }

        /* Status Overview Cards */
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .status-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .status-card .label {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .status-card .value {
            font-size: 1.5rem;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }

        .status-card .value.success { color: var(--success); }
        .status-card .value.warning { color: var(--warning); }
        .status-card .value.error { color: var(--error); }

        /* Toast Notifications */
        .toast-container {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            z-index: 1000;
        }

        .toast {
            padding: 1rem 1.5rem;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            animation: slideIn 0.3s ease;
            min-width: 300px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4);
        }

        .toast.success { border-left: 4px solid var(--success); }
        .toast.error { border-left: 4px solid var(--error); }
        .toast.warning { border-left: 4px solid var(--warning); }
        .toast.info { border-left: 4px solid var(--info); }

        @keyframes slideIn {
            from { opacity: 0; transform: translateX(100px); }
            to { opacity: 1; transform: translateX(0); }
        }

        /* Loading Spinner */
        .spinner {
            width: 20px;
            height: 20px;
            border: 2px solid var(--border-color);
            border-top-color: var(--accent-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Tables */
        .table-container {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            padding: 1rem;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }

        th {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            font-weight: 600;
        }

        td {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
        }

        tr:hover {
            background: var(--bg-tertiary);
        }

        /* Responsive */
        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }

            .header {
                flex-direction: column;
                gap: 1rem;
                text-align: center;
            }

            .form-grid {
                grid-template-columns: 1fr;
            }

            .btn-group {
                flex-direction: column;
            }

            .nav-tabs {
                justify-content: flex-start;
            }
        }

        /* Code/Mono text */
        code {
            font-family: 'JetBrains Mono', monospace;
            background: var(--bg-tertiary);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.85em;
        }

        /* Info Box */
        .info-box {
            display: flex;
            gap: 0.75rem;
            padding: 1rem;
            background: rgba(59, 130, 246, 0.1);
            border: 1px solid rgba(59, 130, 246, 0.3);
            border-radius: 8px;
            margin-bottom: 1.5rem;
        }

        .info-box.warning {
            background: rgba(245, 158, 11, 0.1);
            border-color: rgba(245, 158, 11, 0.3);
        }

        .info-box .icon {
            font-size: 1.25rem;
        }

        .info-box .text {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="bg-pattern"></div>
    
    <div class="container">
        <header class="header">
            <div class="logo">
                <div class="logo-icon">📚</div>
                <div class="logo-text">
                    <h1>Bookshelf Traveller</h1>
                    <span id="version">Loading...</span>
                </div>
            </div>
            <div class="header-actions">
                <div class="status-badge" id="connection-status">
                    <span class="status-dot offline"></span>
                    <span>Checking...</span>
                </div>
            </div>
        </header>

        <nav class="nav-tabs">
            <button class="nav-tab active" data-tab="overview">📊 Overview</button>
            <button class="nav-tab" data-tab="server">🖥️ Server</button>
            <button class="nav-tab" data-tab="discord">🤖 Discord</button>
            <button class="nav-tab" data-tab="bot">⚙️ Bot Settings</button>
            <button class="nav-tab" data-tab="tasks">📋 Tasks</button>
            <button class="nav-tab" data-tab="database">💾 Database</button>
            <button class="nav-tab" data-tab="logs">📜 Logs</button>
        </nav>

        <!-- Overview Tab -->
        <section class="tab-content active" id="tab-overview">
            <div class="status-grid">
                <div class="status-card">
                    <span class="label">ABS Connection</span>
                    <span class="value" id="abs-status">--</span>
                </div>
                <div class="status-card">
                    <span class="label">ABS User</span>
                    <span class="value" id="abs-user">--</span>
                </div>
                <div class="status-card">
                    <span class="label">User Type</span>
                    <span class="value" id="abs-type">--</span>
                </div>
                <div class="status-card">
                    <span class="label">Uptime</span>
                    <span class="value" id="uptime">--</span>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">🔗</span>
                        Quick Actions
                    </h2>
                </div>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick="testConnection()">
                        🔄 Test ABS Connection
                    </button>
                    <button class="btn btn-secondary" onclick="refreshStatus()">
                        📊 Refresh Status
                    </button>
                    <button class="btn btn-secondary" onclick="copyInviteLink()">
                        📋 Copy Bot Invite Link
                    </button>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">📖</span>
                        Current Configuration Summary
                    </h2>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Setting</th>
                                <th>Value</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody id="config-summary">
                            <tr>
                                <td colspan="3">Loading...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- Server Tab -->
        <section class="tab-content" id="tab-server">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">🖥️</span>
                        Audiobookshelf Server Configuration
                    </h2>
                </div>
                
                <div class="info-box">
                    <span class="icon">ℹ️</span>
                    <span class="text">Configure your Audiobookshelf server connection. Changes require a bot restart to take effect.</span>
                </div>

                <form id="server-form" onsubmit="saveServerConfig(event)">
                    <div class="form-grid">
                        <div class="form-group">
                            <label class="form-label">
                                Server URL <span class="required">*</span>
                            </label>
                            <input type="url" class="form-input" name="bookshelfURL" 
                                   placeholder="https://abs.example.com" required>
                            <span class="form-help">Your Audiobookshelf server URL (include https://)</span>
                        </div>
                        
                        <div class="form-group">
                            <label class="form-label">
                                API Token <span class="required">*</span>
                            </label>
                            <input type="password" class="form-input" name="bookshelfToken" 
                                   placeholder="Your API token" required>
                            <span class="form-help">Get this from ABS Settings → Users → API Token</span>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Optional Image URL</label>
                            <input type="url" class="form-input" name="OPT_IMAGE_URL" 
                                   placeholder="https://images.example.com">
                            <span class="form-help">Alternative URL for cover images (leave empty to use server URL)</span>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Default Search Provider</label>
                            <select class="form-input form-select" name="DEFAULT_PROVIDER">
                                <option value="audible">Audible (US)</option>
                                <option value="audible.uk">Audible UK</option>
                                <option value="audible.ca">Audible Canada</option>
                                <option value="audible.au">Audible Australia</option>
                                <option value="audible.fr">Audible France</option>
                                <option value="audible.de">Audible Germany</option>
                                <option value="audible.it">Audible Italy</option>
                                <option value="audible.es">Audible Spain</option>
                                <option value="audible.in">Audible India</option>
                                <option value="google">Google Books</option>
                                <option value="openlibrary">Open Library</option>
                                <option value="itunes">iTunes</option>
                                <option value="fantlab">FantLab</option>
                            </select>
                            <span class="form-help">Provider used for book searches in wishlist</span>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Timezone</label>
                            <input type="text" class="form-input" name="TIMEZONE" 
                                   placeholder="America/Toronto">
                            <span class="form-help">Timezone for timestamps (e.g., America/New_York, Europe/London)</span>
                        </div>
                    </div>

                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Save Server Settings</button>
                        <button type="button" class="btn btn-secondary" onclick="testABSConnection()">🔗 Test Connection</button>
                    </div>
                </form>
            </div>
        </section>

        <!-- Discord Tab -->
        <section class="tab-content" id="tab-discord">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">🤖</span>
                        Discord Bot Configuration
                    </h2>
                </div>

                <div class="info-box warning">
                    <span class="icon">⚠️</span>
                    <span class="text">Be careful with the Discord token - never share it publicly!</span>
                </div>

                <form id="discord-form" onsubmit="saveDiscordConfig(event)">
                    <div class="form-grid">
                        <div class="form-group">
                            <label class="form-label">
                                Discord Bot Token <span class="required">*</span>
                            </label>
                            <input type="password" class="form-input" name="DISCORD_TOKEN" 
                                   placeholder="Your Discord bot token" required>
                            <span class="form-help">Get this from Discord Developer Portal</span>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Client ID</label>
                            <input type="text" class="form-input" name="CLIENT_ID" 
                                   placeholder="Bot client ID">
                            <span class="form-help">Used to generate bot invite link</span>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Playback Role ID</label>
                            <input type="text" class="form-input" name="PLAYBACK_ROLE" 
                                   placeholder="Role ID for playback control">
                            <span class="form-help">Users with this role can control playback sessions</span>
                        </div>
                    </div>

                    <div style="margin-top: 1.5rem;">
                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">Owner Only Mode</span>
                                <span class="desc">Restrict most commands to bot owner</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="OWNER_ONLY">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    </div>

                    <div style="margin-top: 1rem;">
                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">Ephemeral Output</span>
                                <span class="desc">Make command responses visible only to the user</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="EPHEMERAL_OUTPUT">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    </div>

                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Save Discord Settings</button>
                    </div>
                </form>
            </div>
        </section>

        <!-- Bot Settings Tab -->
        <section class="tab-content" id="tab-bot">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">⚙️</span>
                        Bot Behavior Settings
                    </h2>
                </div>

                <form id="bot-form" onsubmit="saveBotConfig(event)">
                    <div style="display: flex; flex-direction: column; gap: 1rem;">
                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">Debug Mode</span>
                                <span class="desc">Enable verbose logging for troubleshooting</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="DEBUG_MODE">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">Multi-User Mode</span>
                                <span class="desc">Allow multiple ABS users to log in via Discord</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="MULTI_USER">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">Audio Enabled</span>
                                <span class="desc">Enable voice channel audio playback</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="AUDIO_ENABLED">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">FFmpeg Debug</span>
                                <span class="desc">Enable FFmpeg debug logging (creates log files)</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="FFMPEG_DEBUG">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">Experimental Features</span>
                                <span class="desc">Enable experimental/beta features</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="EXPERIMENTAL">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-group">
                            <div class="toggle-label">
                                <span class="title">Initialization Message</span>
                                <span class="desc">Send DM to owner when bot starts</span>
                            </div>
                            <label class="toggle">
                                <input type="checkbox" name="INITIALIZED_MSG">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    </div>

                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Save Bot Settings</button>
                    </div>
                </form>
            </div>
        </section>

        <!-- Tasks Tab -->
        <section class="tab-content" id="tab-tasks">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">📋</span>
                        Task Configuration
                    </h2>
                </div>

                <form id="tasks-form" onsubmit="saveTasksConfig(event)">
                    <div class="form-grid">
                        <div class="form-group">
                            <label class="form-label">Task Frequency (minutes)</label>
                            <input type="number" class="form-input" name="TASK_FREQUENCY" 
                                   min="1" max="60" placeholder="5">
                            <span class="form-help">How often subscription tasks run (new book check, etc.)</span>
                        </div>

                        <div class="form-group">
                            <label class="form-label">Session Update Frequency (seconds)</label>
                            <input type="number" class="form-input" name="UPDATES" 
                                   min="1" max="30" placeholder="5">
                            <span class="form-help">How often playback sessions sync with ABS server</span>
                        </div>
                    </div>

                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Save Task Settings</button>
                    </div>
                </form>
            </div>

            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">📊</span>
                        Active Tasks
                    </h2>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Task Name</th>
                                <th>Channel</th>
                                <th>Server</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="active-tasks">
                            <tr>
                                <td colspan="4">Loading tasks...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- Database Tab -->
        <section class="tab-content" id="tab-database">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">💾</span>
                        Database Configuration
                    </h2>
                </div>

                <div class="info-box">
                    <span class="icon">ℹ️</span>
                    <span class="text">Choose between SQLite (simple, file-based) or MariaDB (for multi-instance deployments).</span>
                </div>

                <form id="database-form" onsubmit="saveDatabaseConfig(event)">
                    <div class="form-grid">
                        <div class="form-group">
                            <label class="form-label">Database Type</label>
                            <select class="form-input form-select" name="DB_TYPE" onchange="toggleMariaDBFields()">
                                <option value="sqlite">SQLite (Recommended)</option>
                                <option value="mariadb">MariaDB / MySQL</option>
                            </select>
                            <span class="form-help">SQLite is recommended for single-instance deployments</span>
                        </div>
                    </div>

                    <div id="mariadb-fields" style="display: none; margin-top: 1.5rem;">
                        <h3 style="margin-bottom: 1rem; color: var(--text-secondary);">MariaDB Settings</h3>
                        <div class="form-grid">
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
                    </div>

                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Save Database Settings</button>
                        <button type="button" class="btn btn-secondary" onclick="testDatabaseConnection()">🔗 Test Connection</button>
                    </div>
                </form>
            </div>
        </section>

        <!-- Logs Tab -->
        <section class="tab-content" id="tab-logs">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <span class="icon">📜</span>
                        Recent Logs
                    </h2>
                    <button class="btn btn-secondary" onclick="refreshLogs()">🔄 Refresh</button>
                </div>
                <div id="log-container" style="
                    background: var(--bg-primary);
                    border: 1px solid var(--border-color);
                    border-radius: 8px;
                    padding: 1rem;
                    height: 400px;
                    overflow-y: auto;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 0.8rem;
                    line-height: 1.6;
                ">
                    <p style="color: var(--text-muted);">Log viewing is available in the console output.</p>
                    <p style="color: var(--text-muted);">Check your Docker logs or terminal for real-time logging.</p>
                </div>
            </div>
        </section>
    </div>

    <div class="toast-container" id="toast-container"></div>

    <script>
        // Tab Navigation
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                tab.classList.add('active');
                document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
            });
        });

        // Toast Notifications
        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;
            toast.innerHTML = `
                <span>${type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️'}</span>
                <span>${message}</span>
            `;
            container.appendChild(toast);
            
            setTimeout(() => {
                toast.style.animation = 'slideIn 0.3s ease reverse';
                setTimeout(() => toast.remove(), 300);
            }, 4000);
        }

        // API Functions
        async function fetchConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                populateForms(config);
                updateConfigSummary(config);
            } catch (error) {
                showToast('Failed to load configuration', 'error');
            }
        }

        async function fetchStatus() {
            try {
                const response = await fetch('/api/status');
                const status = await response.json();
                updateStatus(status);
            } catch (error) {
                console.error('Failed to fetch status:', error);
            }
        }

        function updateStatus(status) {
            document.getElementById('version').textContent = status.version || 'Unknown';
            
            const statusBadge = document.getElementById('connection-status');
            const statusDot = statusBadge.querySelector('.status-dot');
            const statusText = statusBadge.querySelector('span:last-child');
            
            if (status.abs_connected) {
                statusDot.className = 'status-dot online';
                statusText.textContent = 'Connected';
                document.getElementById('abs-status').textContent = 'Online';
                document.getElementById('abs-status').className = 'value success';
            } else {
                statusDot.className = 'status-dot offline';
                statusText.textContent = 'Disconnected';
                document.getElementById('abs-status').textContent = 'Offline';
                document.getElementById('abs-status').className = 'value error';
            }
            
            document.getElementById('abs-user').textContent = status.abs_user || '--';
            document.getElementById('abs-type').textContent = status.abs_user_type || '--';
            document.getElementById('uptime').textContent = status.uptime || '--';
        }

        function populateForms(config) {
            // Server form
            const serverForm = document.getElementById('server-form');
            if (serverForm) {
                serverForm.bookshelfURL.value = config.server?.bookshelfURL || '';
                serverForm.bookshelfToken.value = config.server?.bookshelfToken || '';
                serverForm.OPT_IMAGE_URL.value = config.server?.OPT_IMAGE_URL || '';
                serverForm.DEFAULT_PROVIDER.value = config.server?.DEFAULT_PROVIDER || 'audible';
                serverForm.TIMEZONE.value = config.server?.TIMEZONE || 'America/Toronto';
            }

            // Discord form
            const discordForm = document.getElementById('discord-form');
            if (discordForm) {
                discordForm.DISCORD_TOKEN.value = config.discord?.DISCORD_TOKEN || '';
                discordForm.CLIENT_ID.value = config.discord?.CLIENT_ID || '';
                discordForm.PLAYBACK_ROLE.value = config.discord?.PLAYBACK_ROLE || '';
                discordForm.OWNER_ONLY.checked = config.discord?.OWNER_ONLY ?? true;
                discordForm.EPHEMERAL_OUTPUT.checked = config.discord?.EPHEMERAL_OUTPUT ?? true;
            }

            // Bot form
            const botForm = document.getElementById('bot-form');
            if (botForm) {
                botForm.DEBUG_MODE.checked = config.bot?.DEBUG_MODE ?? false;
                botForm.MULTI_USER.checked = config.bot?.MULTI_USER ?? true;
                botForm.AUDIO_ENABLED.checked = config.bot?.AUDIO_ENABLED ?? true;
                botForm.FFMPEG_DEBUG.checked = config.bot?.FFMPEG_DEBUG ?? false;
                botForm.EXPERIMENTAL.checked = config.bot?.EXPERIMENTAL ?? false;
                botForm.INITIALIZED_MSG.checked = config.bot?.INITIALIZED_MSG ?? true;
            }

            // Tasks form
            const tasksForm = document.getElementById('tasks-form');
            if (tasksForm) {
                tasksForm.TASK_FREQUENCY.value = config.tasks?.TASK_FREQUENCY || 5;
                tasksForm.UPDATES.value = config.tasks?.UPDATES || 5;
            }

            // Database form
            const dbForm = document.getElementById('database-form');
            if (dbForm) {
                dbForm.DB_TYPE.value = config.database?.DB_TYPE || 'sqlite';
                dbForm.DB_HOST.value = config.database?.DB_HOST || 'localhost';
                dbForm.DB_PORT.value = config.database?.DB_PORT || 3306;
                dbForm.DB_USER.value = config.database?.DB_USER || 'root';
                dbForm.DB_PASSWORD.value = config.database?.DB_PASSWORD || '';
                dbForm.DB_NAME.value = config.database?.DB_NAME || 'bookshelf';
                toggleMariaDBFields();
            }
        }

        function updateConfigSummary(config) {
            const tbody = document.getElementById('config-summary');
            const rows = [
                ['ABS Server', config.server?.bookshelfURL || 'Not configured', config.server?.bookshelfURL ? '✅' : '⚠️'],
                ['ABS Token', config.server?.bookshelfToken ? '••••••••' : 'Not set', config.server?.bookshelfToken ? '✅' : '❌'],
                ['Discord Token', config.discord?.DISCORD_TOKEN ? '••••••••' : 'Not set', config.discord?.DISCORD_TOKEN ? '✅' : '❌'],
                ['Multi-User Mode', config.bot?.MULTI_USER ? 'Enabled' : 'Disabled', config.bot?.MULTI_USER ? '✅' : 'ℹ️'],
                ['Audio Enabled', config.bot?.AUDIO_ENABLED ? 'Yes' : 'No', config.bot?.AUDIO_ENABLED ? '✅' : 'ℹ️'],
                ['Database Type', config.database?.DB_TYPE?.toUpperCase() || 'SQLite', '✅'],
                ['Task Frequency', (config.tasks?.TASK_FREQUENCY || 5) + ' minutes', '✅'],
            ];
            
            tbody.innerHTML = rows.map(([setting, value, status]) => `
                <tr>
                    <td>${setting}</td>
                    <td><code>${value}</code></td>
                    <td>${status}</td>
                </tr>
            `).join('');
        }

        function toggleMariaDBFields() {
            const dbType = document.querySelector('[name="DB_TYPE"]').value;
            const mariaFields = document.getElementById('mariadb-fields');
            mariaFields.style.display = dbType === 'mariadb' ? 'block' : 'none';
        }

        // Form Submission Functions
        async function saveServerConfig(event) {
            event.preventDefault();
            const form = event.target;
            const data = {
                bookshelfURL: form.bookshelfURL.value,
                bookshelfToken: form.bookshelfToken.value,
                OPT_IMAGE_URL: form.OPT_IMAGE_URL.value,
                DEFAULT_PROVIDER: form.DEFAULT_PROVIDER.value,
                TIMEZONE: form.TIMEZONE.value,
            };
            
            try {
                const response = await fetch('/api/config/server', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    showToast('Server settings saved! Restart bot to apply.', 'success');
                } else {
                    throw new Error('Failed to save');
                }
            } catch (error) {
                showToast('Failed to save server settings', 'error');
            }
        }

        async function saveDiscordConfig(event) {
            event.preventDefault();
            const form = event.target;
            const data = {
                DISCORD_TOKEN: form.DISCORD_TOKEN.value,
                CLIENT_ID: form.CLIENT_ID.value,
                PLAYBACK_ROLE: form.PLAYBACK_ROLE.value,
                OWNER_ONLY: form.OWNER_ONLY.checked,
                EPHEMERAL_OUTPUT: form.EPHEMERAL_OUTPUT.checked,
            };
            
            try {
                const response = await fetch('/api/config/discord', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    showToast('Discord settings saved! Restart bot to apply.', 'success');
                } else {
                    throw new Error('Failed to save');
                }
            } catch (error) {
                showToast('Failed to save Discord settings', 'error');
            }
        }

        async function saveBotConfig(event) {
            event.preventDefault();
            const form = event.target;
            const data = {
                DEBUG_MODE: form.DEBUG_MODE.checked,
                MULTI_USER: form.MULTI_USER.checked,
                AUDIO_ENABLED: form.AUDIO_ENABLED.checked,
                FFMPEG_DEBUG: form.FFMPEG_DEBUG.checked,
                EXPERIMENTAL: form.EXPERIMENTAL.checked,
                INITIALIZED_MSG: form.INITIALIZED_MSG.checked,
            };
            
            try {
                const response = await fetch('/api/config/bot', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    showToast('Bot settings saved! Restart bot to apply.', 'success');
                } else {
                    throw new Error('Failed to save');
                }
            } catch (error) {
                showToast('Failed to save bot settings', 'error');
            }
        }

        async function saveTasksConfig(event) {
            event.preventDefault();
            const form = event.target;
            const data = {
                TASK_FREQUENCY: parseInt(form.TASK_FREQUENCY.value),
                UPDATES: parseInt(form.UPDATES.value),
            };
            
            try {
                const response = await fetch('/api/config/tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    showToast('Task settings saved! Restart bot to apply.', 'success');
                } else {
                    throw new Error('Failed to save');
                }
            } catch (error) {
                showToast('Failed to save task settings', 'error');
            }
        }

        async function saveDatabaseConfig(event) {
            event.preventDefault();
            const form = event.target;
            const data = {
                DB_TYPE: form.DB_TYPE.value,
                DB_HOST: form.DB_HOST.value,
                DB_PORT: parseInt(form.DB_PORT.value),
                DB_USER: form.DB_USER.value,
                DB_PASSWORD: form.DB_PASSWORD.value,
                DB_NAME: form.DB_NAME.value,
            };
            
            try {
                const response = await fetch('/api/config/database', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    showToast('Database settings saved! Restart bot to apply.', 'success');
                } else {
                    throw new Error('Failed to save');
                }
            } catch (error) {
                showToast('Failed to save database settings', 'error');
            }
        }

        // Action Functions
        async function testConnection() {
            showToast('Testing connection...', 'info');
            try {
                const response = await fetch('/api/test-connection');
                const result = await response.json();
                
                if (result.success) {
                    showToast('Connection successful! User: ' + result.user, 'success');
                } else {
                    showToast('Connection failed: ' + result.error, 'error');
                }
            } catch (error) {
                showToast('Connection test failed', 'error');
            }
        }

        async function testABSConnection() {
            const form = document.getElementById('server-form');
            const url = form.bookshelfURL.value;
            const token = form.bookshelfToken.value;
            
            if (!url || !token) {
                showToast('Please enter URL and token first', 'warning');
                return;
            }
            
            showToast('Testing connection...', 'info');
            try {
                const response = await fetch('/api/test-abs-connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, token })
                });
                const result = await response.json();
                
                if (result.success) {
                    showToast('Connection successful! User: ' + result.user, 'success');
                } else {
                    showToast('Connection failed: ' + result.error, 'error');
                }
            } catch (error) {
                showToast('Connection test failed', 'error');
            }
        }

        function refreshStatus() {
            fetchStatus();
            showToast('Status refreshed', 'info');
        }

        function copyInviteLink() {
            const clientId = document.querySelector('[name="CLIENT_ID"]').value;
            if (!clientId) {
                showToast('Client ID not configured', 'warning');
                return;
            }
            
            const link = `https://discord.com/oauth2/authorize?client_id=${clientId}&permissions=277062405120&integration_type=0&scope=bot`;
            navigator.clipboard.writeText(link);
            showToast('Invite link copied to clipboard!', 'success');
        }

        function refreshLogs() {
            showToast('Logs are available in console/Docker output', 'info');
        }

        async function testDatabaseConnection() {
            showToast('Testing database connection...', 'info');
            try {
                const response = await fetch('/api/test-database');
                const result = await response.json();
                
                if (result.success) {
                    showToast('Database connection successful!', 'success');
                } else {
                    showToast('Database connection failed: ' + result.error, 'error');
                }
            } catch (error) {
                showToast('Database test failed', 'error');
            }
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            fetchConfig();
            fetchStatus();
            
            // Refresh status every 30 seconds
            setInterval(fetchStatus, 30000);
        });
    </script>
</body>
</html>'''


# API Routes
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
    
    # Calculate uptime
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
    """Save server configuration"""
    try:
        save_env_value("bookshelfURL", config.bookshelfURL)
        save_env_value("bookshelfToken", config.bookshelfToken)
        save_env_value("OPT_IMAGE_URL", config.OPT_IMAGE_URL or "")
        save_env_value("DEFAULT_PROVIDER", config.DEFAULT_PROVIDER)
        save_env_value("TIMEZONE", config.TIMEZONE)
        return {"success": True, "message": "Server configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/discord")
async def save_discord_config(config: DiscordConfig):
    """Save Discord configuration"""
    try:
        save_env_value("DISCORD_TOKEN", config.DISCORD_TOKEN)
        save_env_value("CLIENT_ID", config.CLIENT_ID or "")
        save_env_value("OWNER_ONLY", str(config.OWNER_ONLY))
        save_env_value("PLAYBACK_ROLE", config.PLAYBACK_ROLE or "")
        save_env_value("EPHEMERAL_OUTPUT", str(config.EPHEMERAL_OUTPUT))
        return {"success": True, "message": "Discord configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/bot")
async def save_bot_config(config: BotConfig):
    """Save bot configuration"""
    try:
        save_env_value("DEBUG_MODE", str(config.DEBUG_MODE))
        save_env_value("MULTI_USER", str(config.MULTI_USER))
        save_env_value("AUDIO_ENABLED", str(config.AUDIO_ENABLED))
        save_env_value("FFMPEG_DEBUG", str(config.FFMPEG_DEBUG))
        save_env_value("EXPERIMENTAL", str(config.EXPERIMENTAL))
        save_env_value("INITIALIZED_MSG", str(config.INITIALIZED_MSG))
        return {"success": True, "message": "Bot configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/tasks")
async def save_tasks_config(config: TaskConfig):
    """Save tasks configuration"""
    try:
        save_env_value("TASK_FREQUENCY", str(config.TASK_FREQUENCY))
        save_env_value("UPDATES", str(config.UPDATES))
        return {"success": True, "message": "Tasks configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/database")
async def save_database_config(config: DatabaseConfig):
    """Save database configuration"""
    try:
        save_env_value("DB_TYPE", config.DB_TYPE)
        save_env_value("DB_HOST", config.DB_HOST)
        save_env_value("DB_PORT", str(config.DB_PORT))
        save_env_value("DB_USER", config.DB_USER)
        save_env_value("DB_PASSWORD", config.DB_PASSWORD)
        save_env_value("DB_NAME", config.DB_NAME)
        return {"success": True, "message": "Database configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/test-connection")
async def test_connection():
    """Test connection to Audiobookshelf server"""
    try:
        username, user_type, user_locked = await c.bookshelf_auth_test()
        return {
            "success": True,
            "user": username,
            "user_type": user_type,
            "locked": user_locked
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


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


@app.get("/api/test-database")
async def test_database():
    """Test database connection"""
    db_type = get_env_value("DB_TYPE", "sqlite")
    
    try:
        if db_type == "mariadb":
            import aiomysql
            conn = await aiomysql.connect(
                host=get_env_value("DB_HOST", "localhost"),
                port=int(get_env_value("DB_PORT", "3306")),
                user=get_env_value("DB_USER", "root"),
                password=get_env_value("DB_PASSWORD", ""),
                db=get_env_value("DB_NAME", "bookshelf")
            )
            await conn.ensure_closed()
        else:
            import aiosqlite
            db_path = os.path.join(DB_DIR, "wishlist.db")
            os.makedirs(DB_DIR, exist_ok=True)
            conn = await aiosqlite.connect(db_path)
            await conn.close()
        
        return {"success": True, "type": db_type}
    except Exception as e:
        return {"success": False, "error": str(e), "type": db_type}


@app.get("/api/tasks")
async def get_tasks():
    """Get list of active tasks"""
    try:
        from subscription_task import search_task_db
        tasks = await search_task_db()
        return {"tasks": tasks or []}
    except Exception as e:
        return {"tasks": [], "error": str(e)}


# Run the server
def run_webui(host: str = "0.0.0.0", port: int = 8080):
    """Run the web UI server"""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_webui()
