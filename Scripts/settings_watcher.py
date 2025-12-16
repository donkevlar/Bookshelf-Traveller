"""
Settings Watcher - Auto-reload configuration on .env changes
Monitors .env file and reloads settings after 30 seconds of inactivity
"""

import asyncio
import logging
import os
import importlib
import sys
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import dotenv_values

logger = logging.getLogger("settings_watcher")

# Sensitive keys to mask in logs
SENSITIVE_KEYS = {
    'DISCORD_TOKEN', 'bookshelfToken', 'DB_PASSWORD', 
    'CLIENT_ID', 'TEST_ENV1'
}


class EnvFileHandler(FileSystemEventHandler):
    """Handles .env file change events"""
    
    def __init__(self, env_path, reload_callback):
        self.env_path = Path(env_path)
        self.reload_callback = reload_callback
        self.last_modified = 0
        self.reload_task = None
        self.previous_values = {}
        
        # Load initial values
        if self.env_path.exists():
            self.previous_values = dotenv_values(self.env_path)
    
    def on_modified(self, event):
        """Called when .env file is modified"""
        if Path(event.src_path).name == self.env_path.name:
            current_time = asyncio.get_event_loop().time()
            
            # Cancel previous reload task if it exists
            if self.reload_task and not self.reload_task.done():
                self.reload_task.cancel()
            
            # Schedule new reload after 30 seconds
            self.reload_task = asyncio.create_task(self._delayed_reload())
    
    async def _delayed_reload(self):
        """Wait 30 seconds then reload settings"""
        try:
            await asyncio.sleep(30)
            await self._reload_settings()
        except asyncio.CancelledError:
            logger.debug("Reload cancelled, new change detected")
    
    async def _reload_settings(self):
        """Reload settings module and log changes"""
        try:
            logger.info("=" * 60)
            logger.info("Settings change detected, reloading configuration...")
            
            # Load new values
            if not self.env_path.exists():
                logger.warning(f".env file not found at {self.env_path}")
                return
            
            new_values = dotenv_values(self.env_path)
            
            # Update environment variables
            for key, value in new_values.items():
                if value is not None:
                    os.environ[key] = value
            
            # Detect and log changes
            changes = self._detect_changes(self.previous_values, new_values)
            
            if changes:
                logger.info("Configuration changes detected:")
                for change_type, key, old_val, new_val in changes:
                    masked_old = self._mask_value(key, old_val)
                    masked_new = self._mask_value(key, new_val)
                    
                    if change_type == "added":
                        logger.info(f"  + {key}: {masked_new}")
                    elif change_type == "removed":
                        logger.info(f"  - {key}: {masked_old}")
                    elif change_type == "changed":
                        logger.info(f"  ~ {key}: {masked_old} → {masked_new}")
            else:
                logger.info("No configuration changes detected")
            
            # Reload settings module
            import settings
            importlib.reload(settings)
            logger.info("Settings module reloaded successfully")
            
            # Update previous values
            self.previous_values = new_values
            
            # Call callback if provided
            if self.reload_callback:
                await self.reload_callback()
            
            logger.info("Configuration reload complete")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error reloading settings: {e}", exc_info=True)
    
    def _detect_changes(self, old_values, new_values):
        """Detect changes between old and new configuration"""
        changes = []
        
        all_keys = set(old_values.keys()) | set(new_values.keys())
        
        for key in sorted(all_keys):
            old_val = old_values.get(key)
            new_val = new_values.get(key)
            
            if old_val is None and new_val is not None:
                changes.append(("added", key, None, new_val))
            elif old_val is not None and new_val is None:
                changes.append(("removed", key, old_val, None))
            elif old_val != new_val:
                changes.append(("changed", key, old_val, new_val))
        
        return changes
    
    def _mask_value(self, key, value):
        """Mask sensitive values in logs"""
        if value is None:
            return "None"
        
        if key in SENSITIVE_KEYS:
            if len(value) > 8:
                return f"{value[:4]}...{value[-4:]}"
            else:
                return "••••••••"
        
        return value


class SettingsWatcher:
    """Manages the settings file watcher"""
    
    def __init__(self, env_path=".env", reload_callback=None):
        self.env_path = Path(env_path).resolve()
        self.reload_callback = reload_callback
        self.observer = None
        self.handler = None
    
    def start(self):
        """Start watching the .env file"""
        if not self.env_path.exists():
            logger.warning(f".env file not found at {self.env_path}, watcher disabled")
            return
        
        self.handler = EnvFileHandler(self.env_path, self.reload_callback)
        self.observer = Observer()
        self.observer.schedule(self.handler, str(self.env_path.parent), recursive=False)
        self.observer.start()
        
        logger.info(f"Settings watcher started, monitoring: {self.env_path}")
        logger.info("Changes will be applied 30 seconds after last modification")
    
    def stop(self):
        """Stop watching the .env file"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            logger.info("Settings watcher stopped")


async def reload_bot_components():
    """
    Callback function to reload bot components after settings change.
    Can be expanded to reload specific bot modules as needed.
    """
    logger.info("Reloading bot components...")
    # Add any bot-specific reload logic here
    # For example: reload extensions, update global variables, etc.
