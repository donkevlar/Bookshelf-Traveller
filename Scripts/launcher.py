#!/usr/bin/env python3
"""
Bookshelf Traveller Combined Launcher
Runs both the Discord bot and the Web UI concurrently
"""

import asyncio
import logging
import os
import sys
import signal
import threading
from multiprocessing import Process

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)-5s - %(asctime)s - %(name)s : %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("launcher")


def run_webui():
    """Run the FastAPI web UI server"""
    import uvicorn
    from webui import app
    
    host = os.getenv("WEBUI_HOST", "0.0.0.0")
    port = int(os.getenv("WEBUI_PORT", "8080"))
    
    logger.info(f"Starting Web UI on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def run_bot():
    """Run the Discord bot"""
    import runpy
    # Run main.py as a script (executes __main__ block)
    runpy.run_path('main.py', run_name='__main__')


def main_launcher():
    """Main launcher that coordinates both services"""
    webui_enabled = os.getenv("WEBUI_ENABLED", "true").lower() in ("1", "true", "yes")
    bot_enabled = os.getenv("BOT_ENABLED", "true").lower() in ("1", "true", "yes")
    
    processes = []
    
    logger.info("=" * 60)
    logger.info("   BOOKSHELF TRAVELLER LAUNCHER")
    logger.info("=" * 60)
    
    if webui_enabled:
        logger.info("🌐 Web UI: ENABLED")
        webui_process = Process(target=run_webui, name="WebUI")
        webui_process.start()
        processes.append(webui_process)
    else:
        logger.info("🌐 Web UI: DISABLED")
    
    if bot_enabled:
        logger.info("🤖 Discord Bot: ENABLED")
        # Run bot in main process for better signal handling
        if webui_enabled:
            bot_process = Process(target=run_bot, name="Bot")
            bot_process.start()
            processes.append(bot_process)
        else:
            run_bot()
    else:
        logger.info("🤖 Discord Bot: DISABLED")
    
    logger.info("=" * 60)
    
    # Handle graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Received shutdown signal, stopping services...")
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # Wait for processes
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        shutdown_handler(None, None)


if __name__ == "__main__":
    main_launcher()
    
