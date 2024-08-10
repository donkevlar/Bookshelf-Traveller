import logging
import os
import sqlite3

from interactions import *

logger = logging.getLogger("bot")

# Create new relative path
db_path = 'db/user_info.db'
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Initialize sqlite3 connection

conn = sqlite3.connect(db_path)
cursor = conn.cursor()


def table_create():
    cursor.execute('''
CREATE TABLE IF NOT EXISTS wishlist (
id INTEGER PRIMARY KEY,
title TEXT NOT NULL,
author TEXT NOT NULL,
description TEXT NOT NULL,
cover TEXT,
provider TEXT NOT NULL,
provider_id TEXT NOT NULL, 
discord_id INTEGER NOT NULL)
                        ''')


class WishList(Extension):
    def __init__(self, bot):
        pass
