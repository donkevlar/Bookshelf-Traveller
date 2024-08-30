import sqlite3
from wishlist import wishlist_conn
from subscription_task import conn as task_conn
from subscription_task import cursor as task_cursor


# Use this file if you want to add new columns down the line without breaking previous versions

def add_column_to_db(db_connection, table_name, column_name, column_type="INTEGER", column_argument="NOT NULL", default_value=0, secondary_execute=''):
    cursor = db_connection.cursor()

    # Step 1: Add the new column
    cursor.execute(f'''
        ALTER TABLE {table_name}
        ADD COLUMN {column_name} {column_type} {column_argument} DEFAULT {default_value}
    ''')

    # Step 2: Update all existing rows to set downloaded = 0
    if secondary_execute != '':
        cursor.execute(f'''
            {secondary_execute}
        ''')

    db_connection.commit()
