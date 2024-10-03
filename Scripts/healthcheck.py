import asyncio
import sys
import os
import logging

from bookshelfAPI import bookshelf_user_login
from dotenv import load_dotenv

# Used only for DOCKER HEALTHCHECK, do not import into MAIN or ANY EXTENSION
load_dotenv()

logger = logging.getLogger("bot")


async def main():
    if __name__ == "__main__":
        try:
            user_token = os.getenv('bookshelfToken')
            result = bookshelf_user_login(token=user_token)
            if result:
                print('HEALTHCHECK SUCCEEDED!', file=None)
                sys.exit(0)
            else:
                print('HEALTHCHECK FAILED!', file=None)
                sys.exit(1)

        except Exception as e:
            print('HEALTHCHECK FAILED!', e, file=None)
            sys.exit(1)


logger.debug('RUNNING HEALTHCHECK')
asyncio.run(main())
