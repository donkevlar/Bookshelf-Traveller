import os
import time
import logging
import sys
import asyncio
import uuid
from typing import Optional, List, Tuple
from abc import ABC, abstractmethod

import bookshelfAPI as c
import settings as s
from multi_user import search_user_db
from wishlist import search_wishlist_db, mark_book_as_downloaded

from interactions import *
from interactions.api.events import Startup
from datetime import datetime, timedelta
from interactions.ext.paginators import Paginator
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logger configuration
logger = logging.getLogger("bot")

# Task configuration
TASK_FREQUENCY = 5  # Task execution interval in minutes

# Generate unique instance ID for distributed locking
INSTANCE_ID = str(uuid.uuid4())

# Database configuration from environment variables
DB_TYPE = os.getenv('DB_TYPE', 'sqlite').lower()  # Options: 'sqlite' or 'mariadb'
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'bookshelf')


# Abstract Database Interface for Tasks
class TaskDatabaseInterface(ABC):
    @abstractmethod
    async def connect(self):
        pass

    @abstractmethod
    async def close(self):
        pass

    @abstractmethod
    async def create_tasks_table(self):
        pass

    @abstractmethod
    async def create_version_table(self):
        pass

    @abstractmethod
    async def create_task_locks_table(self):
        pass

    @abstractmethod
    async def create_message_tracking_table(self):
        pass

    @abstractmethod
    async def insert_data(self, discord_id: int, channel_id: int, task: str, server_name: str, token: str) -> bool:
        pass

    @abstractmethod
    async def insert_version(self, version: str) -> bool:
        pass

    @abstractmethod
    async def has_message_been_sent(self, channel_id: int, book_id: str, message_type: str) -> bool:
        pass

    @abstractmethod
    async def mark_message_as_sent(self, channel_id: int, book_id: str, message_type: str):
        pass

    @abstractmethod
    async def search_version_db(self) -> List[Tuple]:
        pass

    @abstractmethod
    async def remove_task_db(self, task: str = '', discord_id: int = 0, db_id: int = 0) -> bool:
        pass

    @abstractmethod
    async def search_task_db(self, discord_id: int = 0, task: str = '', channel_id: int = 0,
                             override_response: str = '') -> Optional[List[Tuple]]:
        pass

    @abstractmethod
    async def acquire_lock(self, task_name: str, lock_duration_seconds: int = 300) -> bool:
        pass

    @abstractmethod
    async def release_lock(self, task_name: str):
        pass

    @abstractmethod
    async def check_lock_owner(self, task_name: str) -> bool:
        pass


# SQLite Implementation for Tasks
class SQLiteTaskDatabase(TaskDatabaseInterface):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self.cursor = None

    async def connect(self):
        import aiosqlite
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.cursor = await self.conn.cursor()
        logger.info(f"Connected to SQLite task database: {self.db_path}")

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def create_tasks_table(self):
        await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                server_name TEXT NOT NULL,
                token TEXT,
                UNIQUE(channel_id, task)
            )
        ''')

        # Check if 'token' column exists
        await self.cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in await self.cursor.fetchall()]
        if 'token' not in columns:
            await self.cursor.execute("ALTER TABLE tasks ADD COLUMN token TEXT")

        await self.conn.commit()

    async def create_version_table(self):
        await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS version_control (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT,
                UNIQUE(version)
            )
        ''')
        await self.conn.commit()

    async def create_task_locks_table(self):
        """Create table for distributed task locking"""
        await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_locks (
                task_name TEXT PRIMARY KEY,
                instance_id TEXT NOT NULL,
                locked_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        ''')
        await self.conn.commit()

    async def create_message_tracking_table(self):
        """Create table to track sent messages and prevent duplicates"""
        await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                book_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                sent_at INTEGER NOT NULL,
                UNIQUE(channel_id, book_id, message_type)
            )
        ''')
        # Create index for faster lookups
        await self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_message_tracking_lookup 
            ON message_tracking(channel_id, book_id, message_type)
        ''')
        await self.conn.commit()

    async def has_message_been_sent(self, channel_id: int, book_id: str, message_type: str) -> bool:
        """Check if a message has already been sent for this book in this channel"""
        # Clean up old tracking records (older than 7 days)
        seven_days_ago = int((datetime.now() - timedelta(days=7)).timestamp())
        await self.cursor.execute('DELETE FROM message_tracking WHERE sent_at < ?', (seven_days_ago,))
        await self.conn.commit()

        # Check if message exists
        await self.cursor.execute('''
            SELECT 1 FROM message_tracking 
            WHERE channel_id = ? AND book_id = ? AND message_type = ?
        ''', (channel_id, book_id, message_type))
        result = await self.cursor.fetchone()
        return result is not None

    async def mark_message_as_sent(self, channel_id: int, book_id: str, message_type: str):
        """Mark a message as sent to prevent duplicates"""
        now = int(datetime.now().timestamp())
        try:
            await self.cursor.execute('''
                INSERT INTO message_tracking (channel_id, book_id, message_type, sent_at)
                VALUES (?, ?, ?, ?)
            ''', (channel_id, book_id, message_type, now))
            await self.conn.commit()
        except Exception as e:
            # Already exists, that's fine
            logger.debug(f"Message already tracked: {e}")

    async def acquire_lock(self, task_name: str, lock_duration_seconds: int = 30) -> bool:
        """Attempt to acquire a lock for a task"""
        now = int(datetime.now().timestamp())
        expires_at = now + lock_duration_seconds

        try:
            # Clean up expired locks first
            await self.cursor.execute(
                'DELETE FROM task_locks WHERE expires_at < ?', (now,)
            )
            await self.conn.commit()

            # Try to insert lock
            await self.cursor.execute(
                '''INSERT INTO task_locks (task_name, instance_id, locked_at, expires_at)
                   VALUES (?, ?, ?, ?)''',
                (task_name, INSTANCE_ID, now, expires_at)
            )
            await self.conn.commit()
            return True
        except Exception as e:
            # Lock already exists or other error
            logger.debug(f"Could not acquire lock for {task_name}: {e}")
            return False

    async def release_lock(self, task_name: str):
        """Release a lock held by this instance"""
        await self.cursor.execute(
            'DELETE FROM task_locks WHERE task_name = ? AND instance_id = ?',
            (task_name, INSTANCE_ID)
        )
        await self.conn.commit()

    async def check_lock_owner(self, task_name: str) -> bool:
        """Check if this instance owns the lock"""
        now = int(datetime.now().timestamp())
        await self.cursor.execute(
            '''SELECT instance_id FROM task_locks 
               WHERE task_name = ? AND expires_at > ?''',
            (task_name, now)
        )
        result = await self.cursor.fetchone()
        return result and result[0] == INSTANCE_ID

    async def insert_data(self, discord_id: int, channel_id: int, task: str, server_name: str, token: str) -> bool:
        try:
            await self.cursor.execute('''
                INSERT INTO tasks (discord_id, channel_id, task, server_name, token) VALUES (?, ?, ?, ?, ?)''',
                                      (int(discord_id), int(channel_id), task, server_name, token))
            await self.conn.commit()
            logger.info(f"Inserted: {discord_id} into tasks table!")
            return True
        except Exception as e:
            logger.warning(f"Failed to insert: {discord_id} with task {task}. Error: {e}")
            return False

    async def insert_version(self, version: str) -> bool:
        try:
            await self.cursor.execute('''INSERT INTO version_control (version) VALUES (?)''', (version,))
            await self.conn.commit()
            return True
        except Exception as e:
            logger.warning(f"Failed to insert version: {version}. Error: {e}")
            return False

    async def search_version_db(self) -> List[Tuple]:
        await self.cursor.execute('''SELECT id, version FROM version_control''')
        rows = await self.cursor.fetchall()
        return rows

    async def remove_task_db(self, task: str = '', discord_id: int = 0, db_id: int = 0) -> bool:
        logger.warning(f'Attempting to delete task {task} with discord id {discord_id} from db!')
        try:
            if task != '' and discord_id != 0:
                await self.cursor.execute("DELETE FROM tasks WHERE task = ? AND discord_id = ?",
                                          (task, int(discord_id)))
                await self.conn.commit()
                logger.info(f"Successfully deleted task {task} with discord id {discord_id} from db!")
                return True
            elif db_id != 0:
                await self.cursor.execute("DELETE FROM tasks WHERE id = ?", (int(db_id),))
                await self.conn.commit()
                logger.info(f"Successfully deleted task with id {db_id}")
                return True
        except Exception as e:
            logger.error(f"Error while attempting to delete {task}: {e}")
            return False

    async def search_task_db(self, discord_id: int = 0, task: str = '', channel_id: int = 0,
                             override_response: str = '') -> Optional[List[Tuple]]:
        override = False

        if override_response != '':
            response = override_response
            logger.warning(response)
            override = True
        else:
            logger.info('Initializing sqlite db search for subscription task module.')

        if channel_id != 0 and task == '' and discord_id == 0:
            option = 1
            if not override:
                logger.info(f'OPTION {option}: Searching db using channel ID in tasks table.')
            await self.cursor.execute('''
                SELECT discord_id, task FROM tasks WHERE channel_id = ?
            ''', (channel_id,))
            rows = await self.cursor.fetchall()

        elif discord_id != 0 and task != '' and channel_id == 0:
            option = 2
            if not override:
                logger.info(f'OPTION {option}: Searching db using discord ID and task name in tasks table.')
            await self.cursor.execute('''
                SELECT channel_id, server_name FROM tasks WHERE discord_id = ? AND task = ?
            ''', (discord_id, task))
            row = await self.cursor.fetchone()
            rows = [row] if row else []

        elif discord_id != 0 and task == '' and channel_id == 0:
            option = 3
            if not override:
                logger.info(f'OPTION {option}: Searching db using discord ID in tasks table.')
            await self.cursor.execute('''
                SELECT task, channel_id, id, token FROM tasks WHERE discord_id = ?
            ''', (discord_id,))
            rows = await self.cursor.fetchall()

        elif task != '':
            option = 4
            if not override:
                logger.info(f'OPTION {option}: Searching db using task name in tasks table.')
            await self.cursor.execute('''
                SELECT task, channel_id, id, token FROM tasks WHERE task = ?
            ''', (task,))
            rows = await self.cursor.fetchall()

        else:
            option = 5
            if not override:
                logger.info(f'OPTION {option}: Searching db using no arguments in tasks table.')
            await self.cursor.execute('''SELECT discord_id, task, channel_id, server_name FROM tasks''')
            rows = await self.cursor.fetchall()

        if rows:
            if not override:
                logger.info(
                    f'Successfully found query using option: {option} using table tasks in subscription task module.')
        else:
            if not override:
                logger.warning('Query returned null using table tasks, an error may follow.')

        return rows


# MariaDB Implementation for Tasks
class MariaDBTaskDatabase(TaskDatabaseInterface):
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
        logger.info(f"Connected to MariaDB task database: {self.database}")

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def create_tasks_table(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        discord_id BIGINT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        task TEXT NOT NULL,
                        server_name TEXT NOT NULL,
                        token TEXT,
                        UNIQUE KEY unique_channel_task (channel_id, task(255))
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

    async def create_version_table(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS version_control (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        version TEXT,
                        UNIQUE KEY unique_version (version(255))
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

    async def create_task_locks_table(self):
        """Create table for distributed task locking"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS task_locks (
                        task_name VARCHAR(255) PRIMARY KEY,
                        instance_id VARCHAR(36) NOT NULL,
                        locked_at BIGINT NOT NULL,
                        expires_at BIGINT NOT NULL,
                        INDEX idx_expires (expires_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

    async def create_message_tracking_table(self):
        """Create table to track sent messages and prevent duplicates"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS message_tracking (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        channel_id BIGINT NOT NULL,
                        book_id VARCHAR(255) NOT NULL,
                        message_type VARCHAR(50) NOT NULL,
                        sent_at BIGINT NOT NULL,
                        UNIQUE KEY unique_message (channel_id, book_id, message_type),
                        INDEX idx_sent_at (sent_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

    async def has_message_been_sent(self, channel_id: int, book_id: str, message_type: str) -> bool:
        """Check if a message has already been sent for this book in this channel"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Clean up old tracking records (older than 7 days)
                seven_days_ago = int((datetime.now() - timedelta(days=7)).timestamp())
                await cursor.execute('DELETE FROM message_tracking WHERE sent_at < %s', (seven_days_ago,))

                # Check if message exists
                await cursor.execute('''
                    SELECT 1 FROM message_tracking 
                    WHERE channel_id = %s AND book_id = %s AND message_type = %s
                ''', (channel_id, book_id, message_type))
                result = await cursor.fetchone()
                return result is not None

    async def mark_message_as_sent(self, channel_id: int, book_id: str, message_type: str):
        """Mark a message as sent to prevent duplicates"""
        now = int(datetime.now().timestamp())
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute('''
                        INSERT INTO message_tracking (channel_id, book_id, message_type, sent_at)
                        VALUES (%s, %s, %s, %s)
                    ''', (channel_id, book_id, message_type, now))
        except Exception as e:
            # Already exists, that's fine
            logger.debug(f"Message already tracked: {e}")

    async def acquire_lock(self, task_name: str, lock_duration_seconds: int = 30) -> bool:
        """Attempt to acquire a lock for a task"""
        now = int(datetime.now().timestamp())
        expires_at = now + lock_duration_seconds

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Clean up expired locks first
                    await cursor.execute(
                        'DELETE FROM task_locks WHERE expires_at < %s', (now,)
                    )

                    # Try to insert lock
                    await cursor.execute(
                        '''INSERT INTO task_locks (task_name, instance_id, locked_at, expires_at)
                           VALUES (%s, %s, %s, %s)''',
                        (task_name, INSTANCE_ID, now, expires_at)
                    )
            return True
        except Exception as e:
            # Lock already exists or other error
            logger.debug(f"Could not acquire lock for {task_name}: {e}")
            return False

    async def release_lock(self, task_name: str):
        """Release a lock held by this instance"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    'DELETE FROM task_locks WHERE task_name = %s AND instance_id = %s',
                    (task_name, INSTANCE_ID)
                )

    async def check_lock_owner(self, task_name: str) -> bool:
        """Check if this instance owns the lock"""
        now = int(datetime.now().timestamp())
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    '''SELECT instance_id FROM task_locks 
                       WHERE task_name = %s AND expires_at > %s''',
                    (task_name, now)
                )
                result = await cursor.fetchone()
                return result and result[0] == INSTANCE_ID

    async def insert_data(self, discord_id: int, channel_id: int, task: str, server_name: str, token: str) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute('''
                        INSERT INTO tasks (discord_id, channel_id, task, server_name, token) 
                        VALUES (%s, %s, %s, %s, %s)''',
                                         (int(discord_id), int(channel_id), task, server_name, token))
            logger.info(f"Inserted: {discord_id} into tasks table!")
            return True
        except Exception as e:
            logger.warning(f"Failed to insert: {discord_id} with task {task}. Error: {e}")
            return False

    async def insert_version(self, version: str) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute('''INSERT INTO version_control (version) VALUES (%s)''', (version,))
            return True
        except Exception as e:
            logger.warning(f"Failed to insert version: {version}. Error: {e}")
            return False

    async def search_version_db(self) -> List[Tuple]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''SELECT id, version FROM version_control''')
                rows = await cursor.fetchall()
                return rows

    async def remove_task_db(self, task: str = '', discord_id: int = 0, db_id: int = 0) -> bool:
        logger.warning(f'Attempting to delete task {task} with discord id {discord_id} from db!')
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    if task != '' and discord_id != 0:
                        await cursor.execute("DELETE FROM tasks WHERE task = %s AND discord_id = %s",
                                             (task, int(discord_id)))
                        logger.info(f"Successfully deleted task {task} with discord id {discord_id} from db!")
                        return True
                    elif db_id != 0:
                        await cursor.execute("DELETE FROM tasks WHERE id = %s", (int(db_id),))
                        logger.info(f"Successfully deleted task with id {db_id}")
                        return True
        except Exception as e:
            logger.error(f"Error while attempting to delete {task}: {e}")
            return False

    async def search_task_db(self, discord_id: int = 0, task: str = '', channel_id: int = 0,
                             override_response: str = '') -> Optional[List[Tuple]]:
        override = False

        if override_response != '':
            response = override_response
            logger.warning(response)
            override = True
        else:
            logger.info('Initializing MariaDB search for subscription task module.')

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if channel_id != 0 and task == '' and discord_id == 0:
                    option = 1
                    if not override:
                        logger.info(f'OPTION {option}: Searching db using channel ID in tasks table.')
                    await cursor.execute('''
                        SELECT discord_id, task FROM tasks WHERE channel_id = %s
                    ''', (channel_id,))
                    rows = await cursor.fetchall()

                elif discord_id != 0 and task != '' and channel_id == 0:
                    option = 2
                    if not override:
                        logger.info(f'OPTION {option}: Searching db using discord ID and task name in tasks table.')
                    await cursor.execute('''
                        SELECT channel_id, server_name FROM tasks WHERE discord_id = %s AND task = %s
                    ''', (discord_id, task))
                    row = await cursor.fetchone()
                    rows = [row] if row else []

                elif discord_id != 0 and task == '' and channel_id == 0:
                    option = 3
                    if not override:
                        logger.info(f'OPTION {option}: Searching db using discord ID in tasks table.')
                    await cursor.execute('''
                        SELECT task, channel_id, id, token FROM tasks WHERE discord_id = %s
                    ''', (discord_id,))
                    rows = await cursor.fetchall()

                elif task != '':
                    option = 4
                    if not override:
                        logger.info(f'OPTION {option}: Searching db using task name in tasks table.')
                    await cursor.execute('''
                        SELECT task, channel_id, id, token FROM tasks WHERE task = %s
                    ''', (task,))
                    rows = await cursor.fetchall()

                else:
                    option = 5
                    if not override:
                        logger.info(f'OPTION {option}: Searching db using no arguments in tasks table.')
                    await cursor.execute('''SELECT discord_id, task, channel_id, server_name FROM tasks''')
                    rows = await cursor.fetchall()

                if rows:
                    if not override:
                        logger.info(
                            f'Successfully found query using option: {option} using table tasks in subscription task module.')
                else:
                    if not override:
                        logger.warning('Query returned null using table tasks, an error may follow.')

                return rows


# Database Factory for Tasks
def create_task_database() -> TaskDatabaseInterface:
    if DB_TYPE == 'mariadb':
        return MariaDBTaskDatabase(DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME)
    else:
        db_path = 'db/tasks.db'
        return SQLiteTaskDatabase(db_path)


# Global database instance
task_db: Optional[TaskDatabaseInterface] = None


async def initialize_task_database():
    global task_db
    task_db = create_task_database()
    await task_db.connect()
    await task_db.create_tasks_table()
    await task_db.create_version_table()
    await task_db.create_task_locks_table()
    await task_db.create_message_tracking_table()
    logger.info(f"Initialized tasks database using {DB_TYPE}")
    logger.info(f"Instance ID: {INSTANCE_ID}")


async def close_task_database():
    global task_db
    if task_db:
        await task_db.close()


# Wrapper functions for backward compatibility
async def insert_data(discord_id: int, channel_id: int, task: str, server_name: str, token: str) -> bool:
    return await task_db.insert_data(discord_id, channel_id, task, server_name, token)


async def insert_version(version: str) -> bool:
    return await task_db.insert_version(version)


async def search_version_db() -> List[Tuple]:
    return await task_db.search_version_db()


async def remove_task_db(task: str = '', discord_id: int = 0, db_id: int = 0) -> bool:
    return await task_db.remove_task_db(task, discord_id, db_id)


async def search_task_db(discord_id: int = 0, task: str = '', channel_id: int = 0,
                         override_response: str = '') -> Optional[List[Tuple]]:
    return await task_db.search_task_db(discord_id, task, channel_id, override_response)


async def acquire_task_lock(task_name: str, lock_duration_seconds: int = 30) -> bool:
    """Acquire a distributed lock for a task"""
    return await task_db.acquire_lock(task_name, lock_duration_seconds)


async def release_task_lock(task_name: str):
    """Release a distributed lock for a task"""
    await task_db.release_lock(task_name)


async def check_task_lock_owner(task_name: str) -> bool:
    """Check if this instance owns the task lock"""
    return await task_db.check_lock_owner(task_name)


async def has_message_been_sent(channel_id: int, book_id: str, message_type: str) -> bool:
    """Check if a message has already been sent"""
    return await task_db.has_message_been_sent(channel_id, book_id, message_type)


async def mark_message_as_sent(channel_id: int, book_id: str, message_type: str):
    """Mark a message as sent"""
    await task_db.mark_message_as_sent(channel_id, book_id, message_type)


async def conn_test():
    """
    Test Audiobookshelf connection and verify user permissions.

    Returns:
        bool: True if user is admin/root, False otherwise
    """
    auth_test, user_type, user_locked = await c.bookshelf_auth_test()
    logger.info(f"Logging user in and verifying role.")

    # Exit if user account is locked
    if user_locked:
        logger.warning("User locked from logging in, please unlock via web GUI.")
        sys.exit("User locked from logging in, please unlock via web GUI.")

    # Verify admin privileges
    ADMIN_USER = False
    if user_type == "root" or user_type == "admin":
        ADMIN_USER = True
        logger.info(f"ABS user logged in as ADMIN with type: {user_type}")
    else:
        logger.info(f"ABS user logged in as NON-ADMIN with type: {user_type}")
    return ADMIN_USER


async def newBookList(task_frequency=TASK_FREQUENCY) -> list:
    """
    Retrieve books added within the specified time period.

    Args:
        task_frequency: Lookback period in minutes (default: TASK_FREQUENCY)

    Returns:
        list: Books added within the time period with metadata
    """
    logger.debug("Initializing NewBookList function")
    items_added = []
    current_time = datetime.now()

    libraries = await c.bookshelf_libraries()
    library_count = len(libraries)
    logger.debug(f'Found {library_count} libraries')

    time_minus_delta = current_time - timedelta(minutes=task_frequency)
    timestamp_minus_delta = int(time.mktime(time_minus_delta.timetuple()) * 1000)

    for name, (library_id, audiobooks_only) in libraries.items():
        library_items = await c.bookshelf_all_library_items(library_id, params="sort=addedAt&desc=1")

        for item in library_items:
            latest_item_time_added = int(item.get('addedTime'))
            latest_item_title = item.get('title')
            latest_item_type = item.get('mediaType')
            latest_item_author = item.get('author')
            latest_item_bookID = item.get('id')
            try:
                latest_item_provider_id = item.get('asin')
            except Exception as e:
                latest_item_provider_id = ''
                logger.debug("Couldn't fetch asin from item. Likely was not set with metadata.")
                logger.debug(f"Error: {e}")

            if "(Abridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Abridged)", '').strip()
            if "(Unabridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Unabridged)", '').strip()

            formatted_time = latest_item_time_added / 1000
            formatted_time = datetime.fromtimestamp(formatted_time)
            formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

            if latest_item_time_added >= timestamp_minus_delta and latest_item_type == 'book':
                items_added.append({"title": latest_item_title, "addedTime": formatted_time,
                                    "author": latest_item_author, "id": latest_item_bookID,
                                    "provider_id": latest_item_provider_id})

        return items_added


class SubscriptionTask(Extension):
    def __init__(self, bot):
        """Initialize the subscription task extension."""
        self.TaskChannel = None
        self.TaskChannelID = None
        self.ServerNickName = ''
        self.embedColor = None
        self.admin_token = None
        self.previous_token = None
        self.bot.admin_token = None

    async def get_server_name_db(self, discord_id: int = 0, task: str = 'new-book-check'):
        """
        Retrieve server nickname from database.

        Args:
            discord_id: Discord user ID
            task: Task name to search for

        Returns:
            str: Server nickname (defaults to "Audiobookshelf" if not found)
        """
        # Set default first to ensure consistent state
        server_name = os.getenv("DEFAULT_SERVER_NAME", "Audiobookshelf")

        try:
            result = await search_task_db(discord_id=discord_id, task=task)

            if result:
                server_name = self._extract_server_name(result)

        except Exception as e:
            logger.error(f"Error retrieving server name: {e}")

        logger.debug(f'Setting server nickname to {server_name}')
        self.ServerNickName = server_name
        return server_name

    def _extract_server_name(self, result) -> str:
        """Extract server name from various result formats."""
        try:
            if isinstance(result, tuple) and len(result) > 1:
                return result[3]
            elif isinstance(result, list) and len(result) > 0:
                return result[0][1] if len(result[0]) > 1 else result[0][0]
            return "Audiobookshelf"
        except (IndexError, TypeError) as e:
            logger.warning(f"Unexpected result format: {e}")
            return "Audiobookshelf"

    async def send_user_wishlist(self, discord_id: int, title: str, author: str, embed: list):
        """
        Send wishlist notification to user when their requested book becomes available.

        Args:
            discord_id: Discord user ID to notify
            title: Book title
            author: Book author
            embed: Discord embed message
        """
        user = await self.bot.fetch_user(discord_id)
        result = await search_task_db(discord_id=discord_id, task='new-book-check')
        name = ''

        if result:
            try:
                name = result[1]
            except (TypeError, IndexError) as error:
                logger.error(f"Couldn't assign server name, {error}")
                name = "Audiobookshelf"

        # Compose wishlist notification message
        msg = f"Hello **{user.display_name}**, one of your wishlisted books has become available! **{title}** by author **{author}** is now available on your Audiobookshelf server: **{name}**!"
        if len(embed) > 10:
            for emb in embed:
                await user.send(content=msg, embed=emb)
        else:
            await user.send(content=msg, embeds=embed)

    async def NewBookCheckEmbed(self, task_frequency=TASK_FREQUENCY, enable_notifications=False):
        """
        Create embed messages for newly added books.

        Args:
            task_frequency: Lookback period in minutes
            enable_notifications: Whether to send wishlist notifications

        Returns:
            list: Discord embed messages for new books
        """
        bookshelfURL = os.getenv("bookshelfURL", "http://127.0.0.1")
        img_url = os.getenv('OPT_IMAGE_URL')

        if not self.ServerNickName:
            self.ServerNickName = "Audiobookshelf"

        items_added = await newBookList(task_frequency) or []

        if items_added:
            count = 0
            total_item_count = len(items_added)
            embeds = []
            wishlist_titles = []
            logger.info(f'{total_item_count} New books found, executing Task!')

            for item in items_added:
                count += 1
                title = item.get('title', 'Unknown Title')
                author = item.get('author', 'Unknown Author')
                addedTime = item.get('addedTime', 'Unknown Time')
                bookID = item.get('id', 'Unknown ID')

                logger.debug(f"Processing book: {title}")

                wishlisted = False
                cover_link = await c.bookshelf_cover_image(bookID) or "https://your-default-cover-url.com"

                wl_search = await search_wishlist_db(title=title)
                if wl_search:
                    wishlisted = True
                    wishlist_titles.append(title)

                embed_message = Embed(
                    title=f"{title}",
                    description=f"Recently added book for [{self.ServerNickName}]({bookshelfURL})",
                    color=self.embedColor or FlatUIColors.ORANGE
                )

                embed_message.add_field(name="Title", value=title, inline=False)
                embed_message.add_field(name="Author", value=author)
                embed_message.add_field(name="Added Time", value=addedTime)
                embed_message.add_field(name="Additional Information", value=f"Wishlisted: **{wishlisted}**",
                                        inline=False)

                # Ensure URL is properly assigned
                if img_url and "https" in img_url:
                    bookshelfURL = img_url
                embed_message.url = f"{bookshelfURL}/item/{bookID}"

                embed_message.add_image(cover_link)
                embed_message.footer = f"{s.bookshelf_traveller_footer} | {self.ServerNickName}"

                embeds.append(embed_message)

                if wl_search:
                    for user in wl_search:
                        discord_id = user[0]
                        search_title = user[2]
                        if enable_notifications:
                            # Send notification and update database
                            await self.send_user_wishlist(discord_id=discord_id, title=title, author=author,
                                                          embed=embeds)
                            await mark_book_as_downloaded(discord_id=discord_id, title=search_title)

            return embeds

    @staticmethod
    async def getFinishedBooks():
        """
        Retrieve books that users have finished within the task frequency period.

        Returns:
            list: Finished books with user and completion information
        """
        current_time = datetime.now()
        book_list = []
        try:
            books = await c.bookshelf_get_valid_books()
            users = await c.get_users()

            time_minus_delta = current_time - timedelta(minutes=TASK_FREQUENCY)
            timestamp_minus_delta = int(time.mktime(time_minus_delta.timetuple()) * 1000)

            count = 0
            if users and books:

                for user in users['users']:
                    user_id = user.get('id')
                    username = user.get('username')

                    endpoint = f'/users/{user_id}'
                    r = await c.bookshelf_conn(endpoint=endpoint, GET=True)
                    if r.status_code == 200:
                        user_data = r.json()

                        for media in user_data['mediaProgress']:

                            media_type = media['mediaItemType']
                            libraryItemId = media['libraryItemId']
                            displayTitle = media.get('displayTitle')
                            finished = bool(media.get('isFinished'))

                            # Only process finished books (not podcasts)
                            if media_type == 'book' and finished:

                                finishedAtTime = int(media.get('finishedAt'))

                                # Format timestamp for display
                                formatted_time = finishedAtTime / 1000
                                formatted_time = datetime.fromtimestamp(formatted_time)
                                formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

                                if finishedAtTime >= timestamp_minus_delta:
                                    count += 1
                                    media['username'] = username
                                    book_list.append(media)
                                    logger.info(
                                        f'User {username}, finished Book: {displayTitle} with  ID: {libraryItemId} at {formatted_time}')

                logger.info(f"Total Found Books: {count}")

        except Exception as e:
            logger.error(f"Error occurred while attempting to get finished book: {e}")

        return book_list

    async def FinishedBookEmbeds(self, book_list: list):
        """
        Create embed messages for finished books.

        Args:
            book_list: List of finished books with metadata

        Returns:
            list: Discord embed messages for finished books
        """
        count = 0
        embeds = []
        serverURL = os.getenv("bookshelfURL", "http://127.0.0.1")
        img_url = os.getenv('OPT_IMAGE_URL')
        for book in book_list:
            count += 1
            title = book.get('displayTitle', 'No Title Provided')
            bookID = book.get('libraryItemId')
            finishedAtTime = int(book.get('finishedAt'))
            username = book.get('username')

            # Get cover link
            cover_link = await c.bookshelf_cover_image(bookID)

            # Convert time to regular format
            formatted_time = finishedAtTime / 1000
            formatted_time = datetime.fromtimestamp(formatted_time)
            formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

            # Construct embed message
            embed_message = Embed(
                title=f"{count}. Recently Finished Book | {title}",
                description=f"Recently finished books for [{self.ServerNickName}]({serverURL})",
                color=self.embedColor or FlatUIColors.ORANGE
            )

            embed_message.add_field(name="Title", value=title, inline=False)
            embed_message.add_field(name="Finished Time", value=formatted_time)
            embed_message.add_field(name="Finished by User", value=username,
                                    inline=False)

            # Ensure URL is properly assigned
            if img_url and "https" in img_url:
                serverURL = img_url
            embed_message.url = f"{serverURL}/item/{bookID}"

            embed_message.add_image(cover_link)
            embed_message.footer = f"{s.bookshelf_traveller_footer} | {self.ServerNickName}"

            embeds.append(embed_message)

        return embeds

    @staticmethod
    async def embed_color_selector(color: int = 0):
        color = int(color)
        selected_color = FlatUIColors.CARROT
        # Yellow
        if color == 1:
            selected_color = FlatUIColors.SUNFLOWER
        # Orange
        elif color == 2:
            selected_color = FlatUIColors.CARROT
        # Purple
        elif color == 3:
            selected_color = FlatUIColors.AMETHYST
        # Turquoise
        elif color == 4:
            selected_color = FlatUIColors.TURQUOISE
        # Red
        elif color == 5:
            selected_color = FlatUIColors.ALIZARIN
        # Green
        elif color == 6:
            selected_color = FlatUIColors.EMERLAND

        return selected_color

    @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    async def newBookTask(self):
        task_name = "new-book-check-execution"

        # Acquire lock
        lock_acquired = await acquire_task_lock(task_name, lock_duration_seconds=30)
        if not lock_acquired:
            logger.debug(f"Another instance is already running {task_name}, skipping...")
            return

        try:
            logger.info("Initializing new-book-check task!")

            search_result = await search_task_db(task="new-book-check")
            if not search_result:
                logger.warning("Task 'new-book-check' is active but setup returned no results. Stopping task.")
                self.newBookTask.stop()
                return

            # Load server nickname
            if not self.ServerNickName:
                await self.get_server_name_db()

            logger.debug(f"Search result: {search_result}")

            previous_token = os.getenv("bookshelfToken")

            for result in search_result:
                channel_id = int(result[1])
                self.admin_token = result[3]

                logger.info(f"Applying active admin token ({len(self.admin_token)} chars)")
                os.environ["bookshelfToken"] = self.admin_token

                # --- Fetch list of new books
                new_titles = await newBookList()
                if not new_titles:
                    logger.info(f"No new books found for channel {channel_id}")
                    continue

                if len(new_titles) > 10:
                    logger.warning("Found more than 10 titles")

                # --- Generate embeds (must match titles)
                embeds = await self.NewBookCheckEmbed(enable_notifications=True)
                if not embeds:
                    logger.warning("New books exist but no embeds were generated.")
                    continue

                # Assert correct alignment
                if len(new_titles) != len(embeds):
                    logger.error("Mismatch between new_titles and embeds. Duplicate prevention disabled for this run.")
                    continue

                # --- Fetch the channel
                channel_query = await self.bot.fetch_channel(channel_id=channel_id, force=True)
                if not channel_query:
                    logger.warning(f"Could not fetch channel {channel_id}")
                    continue

                logger.debug(f"Found Channel: {channel_id}")
                logger.debug(f"Attempting to send messages to channel: {channel_id}")

                # ==========================
                #   DEDUP FIX STARTS HERE
                # ==========================

                books_to_send = []
                embeds_to_send = []

                for idx, item in enumerate(new_titles):
                    book_id = item.get("id")

                    already_sent = await has_message_been_sent(channel_id, book_id, "new-book")

                    if not already_sent:
                        books_to_send.append(book_id)
                        embeds_to_send.append(embeds[idx])
                    else:
                        logger.debug(f"Skipping duplicate for book {book_id} in channel {channel_id}")

                if not books_to_send:
                    logger.info(f"All new books already sent for channel {channel_id}")
                    continue

                # --- Send notifications
                if len(embeds_to_send) < 10:
                    msg = await channel_query.send(content="New books have been added to your library!")
                    await msg.edit(embeds=embeds_to_send)
                else:
                    await channel_query.send(content="New books have been added to your library!")
                    for embed in embeds_to_send:
                        await channel_query.send(embed=embed)

                logger.info(f"Sent {len(embeds_to_send)} new book notifications to channel {channel_id}")

                # Mark books as sent **after** successful send
                for book_id in books_to_send:
                    await mark_message_as_sent(channel_id, book_id, "new-book")

            # Restore token
            os.environ["bookshelfToken"] = previous_token or ""
            self.previous_token = None
            self.admin_token = None

            logger.info("Successfully completed new-book-check task!")

        except Exception as e:
            logger.error(f"Error in newBookTask: {e}", exc_info=True)

        finally:
            await release_task_lock(task_name)
            logger.debug(f"Released lock for {task_name}")

    @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    async def finishedBookTask(self):
        task_name = 'finished-book-check-execution'

        # Try to acquire lock
        lock_acquired = await acquire_task_lock(task_name, lock_duration_seconds=30)

        if not lock_acquired:
            logger.debug(f"Another instance is already running {task_name}, skipping...")
            return

        try:
            logger.info('Initializing Finished Book Task!')
            search_result = await search_task_db(task='finished-book-check')

            if search_result:
                self.previous_token = os.getenv('bookshelfToken')

                for result in search_result:
                    channel_id = int(result[1])
                    logger.info(f'Channel ID: {channel_id}')
                    self.admin_token = result[3]
                    masked = len(self.admin_token)
                    logger.info(f"Appending Active Token! {masked}")
                    os.environ['bookshelfToken'] = self.admin_token

                    # Fetch finished books
                    book_list = await self.getFinishedBooks()
                    if not book_list:
                        logger.info('No finished books found for this channel.')
                        continue

                    embeds = await self.FinishedBookEmbeds(book_list)
                    if not embeds:
                        logger.warning("No embeds created despite having finished books")
                        continue

                    channel_query = await self.bot.fetch_channel(channel_id=channel_id, force=True)
                    if not channel_query:
                        logger.warning(f"Could not fetch channel {channel_id}")
                        continue

                    logger.debug(f"Found Channel: {channel_id}")
                    logger.debug(f"Bot will now attempt to send a message to channel id: {channel_id}")

                    # Check message tracking to prevent duplicate notifications
                    books_to_send = []
                    for idx, item in enumerate(book_list):
                        book_id = item.get('libraryItemId')
                        already_sent = await has_message_been_sent(channel_id, book_id, 'finished-book')

                        if not already_sent:
                            books_to_send.append(idx)
                            await mark_message_as_sent(channel_id, book_id, 'finished-book')
                        else:
                            logger.debug(
                                f"Skipping duplicate message for finished book {book_id} in channel {channel_id}")

                    # Send only unsent finished book notifications
                    if books_to_send:
                        embeds_to_send = [embeds[i] for i in books_to_send if i < len(embeds)]

                        if len(embeds_to_send) < 10:
                            msg = await channel_query.send(
                                content="These books have been recently finished in your library!")
                            await msg.edit(embeds=embeds_to_send)
                        else:
                            await channel_query.send(
                                content="These books have been recently finished in your library!")
                            for embed in embeds_to_send:
                                await channel_query.send(embed=embed)

                        logger.info(f"Sent {len(embeds_to_send)} finished book notifications to channel {channel_id}")
                    else:
                        logger.info(f"All finished books already sent to channel {channel_id}, skipping message")

                # Reset Vars - moved outside the loop with None check
                if self.previous_token is not None:
                    os.environ['bookshelfToken'] = self.previous_token
                    logger.info(f'Returned Active Token to: {self.previous_token}')
                else:
                    logger.warning("Previous token was None, skipping token restoration")

                self.previous_token = None
                self.admin_token = None
                logger.info("Successfully completed finished-book-check task!")

            else:
                logger.warning("Task 'finished-book-check' was active, but setup check failed.")
                self.finishedBookTask.stop()

        except Exception as e:
            logger.error(f"Error in finishedBookTask: {e}", exc_info=True)

        finally:
            # Always release the lock
            await release_task_lock(task_name)
            logger.debug(f"Released lock for {task_name}")

    # Slash Commands ----------------------------------------------------

    @slash_command(name="new-book-check",
                   description="Verify if a new book has been added to your library. Can be setup as a task.",
                   dm_permission=True)
    @slash_option(name="minutes", description=f"Lookback period, in minutes. "
                                              f"Defaults to {TASK_FREQUENCY} minutes. DOES NOT AFFECT TASK.",
                  opt_type=OptionType.INTEGER)
    @slash_option(name="color", description="Will override the new book check embed color.", opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="enable_task", description="If set to true will enable recurring task.",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="disable_task", description="If set to true, this will disable the task.",
                  opt_type=OptionType.BOOLEAN)
    async def newBookCheck(self, ctx: InteractionContext, minutes=TASK_FREQUENCY, enable_task=False,
                           disable_task=False, color=None):
        if color and minutes == TASK_FREQUENCY:
            self.embedColor = await self.embed_color_selector(color)
            await ctx.send("Successfully updated color!", ephemeral=True)
            return
        if enable_task and not disable_task:
            logger.info('Activating New Book Task! A message will follow.')
            if not self.newBookTask.running:
                operationSuccess = False
                search_result = await search_task_db(ctx.author_id, task='new-book-check')
                if search_result:
                    print(search_result)
                    operationSuccess = True

                if operationSuccess:
                    if color:
                        self.embedColor = await self.embed_color_selector(color)

                    await ctx.send(
                        f"Activating New Book Task! This task will automatically refresh every *{TASK_FREQUENCY} minutes*!",
                        ephemeral=True)

                    self.newBookTask.start()
                    return
                else:
                    await ctx.send("Error activating new book task. Please visit logs for more information. "
                                   "Please make sure to setup the task prior to activation by using command **/setup-tasks**",
                                   ephemeral=True)
                    return
            else:
                logger.warning('New book check task was already running, ignoring...')
                await ctx.send('New book check task is already running, ignoring...', ephemeral=True)
                return
        elif disable_task and not enable_task:
            if self.newBookTask.running:
                if color:
                    self.embedColor = await self.embed_color_selector(color)
                await ctx.send("Disabled Task: *Recently Added Books*", ephemeral=True)
                self.newBookTask.stop()
                return
            else:
                pass
        elif disable_task and enable_task:
            await ctx.send(
                "Invalid option entered, please ensure only one option is entered from this command at a time.")
            return
        # Set server nickname
        await self.get_server_name_db(discord_id=ctx.author_id)

        await ctx.send(f'Searching for recently added books in given period of {minutes} minutes.', ephemeral=True)
        if color:
            self.embedColor = await self.embed_color_selector(color)
        embeds = await self.NewBookCheckEmbed(task_frequency=minutes, enable_notifications=False)
        if embeds:
            logger.info(f'Recent books found in given search period of {minutes} minutes!')
            paginator = Paginator.create_from_embeds(self.bot, *embeds)
            await paginator.send(ctx, ephemeral=True)
        else:
            await ctx.send(f"No recent books found in given search period of {minutes} minutes.",
                           ephemeral=True)
            logger.info(f'No recent books found.')

    @check(is_owner())
    @slash_command(name='setup-tasks', description="Setup a task", dm_permission=False)
    @slash_option(name='task', description='The task you wish to setup', required=True, autocomplete=True,
                  opt_type=OptionType.STRING)
    @slash_option(opt_type=OptionType.CHANNEL, name="channel", description="select a channel",
                  channel_types=[ChannelType.GUILD_TEXT], required=True)
    @slash_option(name='user', description="Select a stored user for the task to be executed by.",
                  opt_type=OptionType.STRING, autocomplete=True, required=True)
    @slash_option(name="server_name",
                  description="Give your Audiobookshelf server a nickname. This will overwrite the previous name.",
                  opt_type=OptionType.STRING, required=True)
    @slash_option(name='color', description='Embed message optional accent color, overrides default author color.',
                  opt_type=OptionType.STRING)
    async def task_setup(self, ctx: SlashContext, task, channel, user, server_name, color=None):
        task_name = ""
        success = False
        task_instruction = ''
        task_num = int(task)

        # Check if search_user_db is async or sync
        try:
            import inspect
            if inspect.iscoroutinefunction(search_user_db):
                user_result = await search_user_db(user=user)
            else:
                user_result = search_user_db(user=user)
        except Exception as e:
            logger.error(f"Error searching user db: {e}")
            await ctx.send("Failed to retrieve user information. Please check logs.", ephemeral=True)
            return

        token = user_result[0]

        match task_num:
            # New book check task
            case 1:
                task_name = 'new-book-check'
                task_command = '`/new-book-check disable_task: True`'
                task_instruction = f'Task is now active. To disable, use **{task_command}**'
                result = await insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name,
                                           server_name=server_name, token=token)

                if result:
                    success = True
                    if not self.newBookTask.running:
                        self.newBookTask.start()
                        logger.info('Successfully subscribed to new-book-check!')

            # Finished book check task
            case 2:
                task_name = 'finished-book-check'
                task_command = '`/remove-task task:finished-book-check`'
                task_instruction = f'Task is now active. To disable, use **{task_command}**'
                result = await insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name,
                                           server_name=server_name, token=token)

                if result:
                    success = True
                    if not self.finishedBookTask.running:
                        self.finishedBookTask.start()
                        logger.info('Successfully subscribed to finished-book-task!')

        if success:
            if color:
                self.embedColor = await self.embed_color_selector(int(color))
            await ctx.send(
                f"Successfully setup task **{task_name}** with channel **{channel.name}**. \nInstructions: {task_instruction}",
                ephemeral=True)

            await self.get_server_name_db(discord_id=ctx.author_id)
        else:
            await ctx.send(
                f"An error occurred while attempting to setup the task **{task_name}**. Most likely due to the task already being setup. "
                f"Please visit the logs for more information.", ephemeral=True)

    @check(is_owner())
    @slash_command(name='remove-task', description="Remove an active task from the task db.")
    @slash_option(name='task', description="Active tasks pulled from db. Autofill format: c1: task | c2: channel name.",
                  autocomplete=True, required=True,
                  opt_type=OptionType.STRING)
    async def remove_task_command(self, ctx: SlashContext, task):
        result = await remove_task_db(db_id=task)
        if result:
            await ctx.send("Successfully removed task!", ephemeral=True)
        else:
            await ctx.send("Failed to remove task, please visit logs for additional details.", ephemeral=True)

    @slash_command(name="active-tasks", description="View active tasks related to you.")
    async def active_tasks_command(self, ctx: SlashContext):
        embeds = []
        success = False
        result = await search_task_db()
        if result:
            for discord_id, task, channel_id, server_name in result:
                channel = await self.bot.fetch_channel(channel_id)
                discord_user = await self.bot.fetch_user(discord_id)
                if channel and discord_user:
                    success = True
                    response = f"Channel: **{channel.name}**\nDiscord User: **{discord_user}**"
                    embed_message = Embed(
                        title="Task",
                        description="All Currently Active Tasks. *Note: this will pull for all channels and users.*",
                        color=ctx.author.accent_color
                    )
                    embed_message.add_field(name="Name", value=task)
                    embed_message.add_field(name="Discord Related Information", value=response)
                    embed_message.footer = s.bookshelf_traveller_footer

                    embeds.append(embed_message)

            if success:
                paginator = Paginator.create_from_embeds(self.client, *embeds)
                await paginator.send(ctx, ephemeral=True)

        else:
            await ctx.send("No currently active tasks found.", ephemeral=True)

    # Autocomplete Functions ---------------------------------------------
    @task_setup.autocomplete('task')
    async def auto_com_task(self, ctx: AutocompleteContext):
        """Provide task options for autocomplete."""
        choices = [
            {"name": "new-book-check", "value": "1"},
            {"name": "finished-book-check", "value": "2"}
        ]
        await ctx.send(choices=choices)

    @remove_task_command.autocomplete('task')
    async def remove_task_auto_comp(self, ctx: AutocompleteContext):
        """Provide user's active tasks for autocomplete."""
        choices = []
        result = await search_task_db(discord_id=ctx.author_id)
        if result:
            for task, channel_id, db_id, token in result:
                channel = await self.bot.fetch_channel(channel_id)
                if channel:
                    response = f"{task} | {channel.name}"
                    choices.append({"name": response, "value": db_id})
        await ctx.send(choices=choices)

    @task_setup.autocomplete('color')
    @newBookCheck.autocomplete('color')
    async def color_embed_bookcheck(self, ctx: AutocompleteContext):
        """Provide color options for embed customization."""
        choices = []
        count = 0
        colors = ['Default', 'Yellow', 'Orange', 'Purple', 'Turquoise', 'Red', 'Green']

        for color in colors:
            choices.append({"name": color, "value": str(count)})
            count += 1

        await ctx.send(choices=choices)

    @task_setup.autocomplete('user')
    async def user_search_task(self, ctx: AutocompleteContext):
        """Provide stored users for task assignment autocomplete."""
        choices = []
        users_ = []
        # Check if search_user_db is async or sync for compatibility
        try:
            import inspect
            if inspect.iscoroutinefunction(search_user_db):
                user_result = await search_user_db()
            else:
                user_result = search_user_db()
        except Exception as e:
            logger.error(f"Error searching user db: {e}")
            user_result = None

        if user_result:
            for user in user_result:
                username = user[0]

                if username not in users_:
                    users_.append(username)
                    choices.append({'name': username, 'value': username})

        await ctx.send(choices=choices)

    # Auto-start tasks on bot startup ---------------------------------

    @listen()
    async def tasks_startup(self, event: Startup):
        """
        Initialize tasks on bot startup if configured in database.
        Waits for database initialization before proceeding.
        """
        # Wait for database initialization
        max_attempts = 10
        for attempt in range(max_attempts):
            if task_db is not None:
                break
            logger.debug(f"Waiting for database initialization... attempt {attempt + 1}/{max_attempts}")
            await asyncio.sleep(0.5)

        if task_db is None:
            logger.error("Database not initialized after waiting. Tasks will not start.")
            return

        init_msg = bool(os.getenv('INITIALIZED_MSG', False))

        # Check for version updates
        version_result = await search_version_db()
        version_list = [v[1] for v in version_result]
        print("Saved Versions: ", version_result)
        print("Current Version: ", s.versionNumber)
        if s.versionNumber not in version_list:
            logger.warning("New version detected! To ensure this module functions properly remove any existing tasks!")
            await event.bot.owner.send(
                f'New version detected! To ensure the task subscription module functions properly remove any existing tasks with command `/remove-task`! Current Version: **{s.versionNumber}**')
            await insert_version(s.versionNumber)

        # Check for configured tasks and auto-start
        result = await search_task_db(
            override_response="Initialized subscription task module, verifying if any tasks are enabled...")
        task_name = "new-book-check"
        task_list = []
        if result:
            logger.info('Subscription Task db was populated, initializing tasks...')
            for item in result:
                task = item[1]
                task_list.append(task)

                logger.debug(f"Tasks db search result: {task}")

            # Auto-start new book check task if configured
            if not self.newBookTask.running and task_name in task_list:
                self.newBookTask.start()
                owner = event.bot.owner
                logger.info(
                    f"Enabling task: New Book Check on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")
                # Send debug notification if enabled
                if s.DEBUG_MODE and s.INITIALIZED_MSG:
                    await owner.send(
                        f"Subscription Task db was populated, auto enabling tasks on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")

            # Auto-start finished book check task if configured
            if not self.finishedBookTask.running and 'finished-book-check' in task_list:
                self.finishedBookTask.start()
                logger.info(
                    f"Enabling task: Finished Book Check on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")