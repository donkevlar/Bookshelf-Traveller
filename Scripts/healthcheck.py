import asyncio
import sys
import os
import logging

from bookshelfAPI import bookshelf_user_login
from dotenv import load_dotenv

# Used only for DOCKER HEALTHCHECK, do not import into MAIN or ANY EXTENSION
load_dotenv()

logger = logging.getLogger("bot")

# Database configuration
DB_TYPE = os.getenv('DB_TYPE', 'sqlite').lower()
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'bookshelf')


async def check_database_connection():
    """Check database connection based on DB_TYPE"""
    try:
        if DB_TYPE == 'mariadb':
            import aiomysql
            logger.debug('Checking MariaDB connection...')
            conn = await aiomysql.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                db=DB_NAME
            )
            await conn.ensure_closed()
            logger.debug('MariaDB connection successful')
            return True
        else:
            # SQLite check - just verify the db directory exists
            import aiosqlite
            logger.debug('Checking SQLite connection...')
            db_path = 'db/wishlist.db'
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

            # Try to connect to SQLite
            conn = await aiosqlite.connect(db_path)
            await conn.close()
            logger.debug('SQLite connection successful')
            return True
    except Exception as e:
        logger.error(f'Database connection check failed: {e}')
        return False


async def main():
    if __name__ == "__main__":
        try:
            # Check Audiobookshelf connection
            user_token = os.getenv('bookshelfToken')
            result = bookshelf_user_login(token=user_token)

            if not result:
                print('HEALTHCHECK FAILED: Audiobookshelf connection failed', file=None)
                sys.exit(1)

            logger.debug('Audiobookshelf connection successful')

            # Check database connection
            db_check = await check_database_connection()

            if not db_check:
                print('HEALTHCHECK FAILED: Database connection failed', file=None)
                sys.exit(1)

            # All checks passed
            print('HEALTHCHECK SUCCEEDED!', file=None)
            sys.exit(0)

        except Exception as e:
            print('HEALTHCHECK FAILED!', e, file=None)
            sys.exit(1)


logger.debug('RUNNING HEALTHCHECK')
asyncio.run(main())