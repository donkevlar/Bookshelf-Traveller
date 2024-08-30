import sqlite3
from wishlist import wishlist_conn, wishlist_cursor
from subscription_task import conn as task_conn
from subscription_task import cursor as task_cursor


# Use this file if you want to add new columns down the line without breaking previous versions

def add_downloaded_column_wishlist():
    cursor = wishlist_conn.cursor()

    # Step 1: Add the new column
    cursor.execute('''
        ALTER TABLE wishlist
        ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0
    ''')

    # Step 2: Update all existing rows to set downloaded = 0
    cursor.execute('''
        UPDATE wishlist
        SET downloaded = 0
        WHERE downloaded IS NULL
    ''')

    wishlist_conn.commit()
