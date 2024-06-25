import os

from interactions import *
import bookshelfAPI as c
import logging
import sqlite3

logger = logging.getLogger("bot")

conn = sqlite3.connect('user_info.db')
cursor = conn.cursor()


def table_create():
    cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
id INTEGER PRIMARY KEY,
user TEXT UNIQUE,
token TEXT UNIQUE,
discord_id INTEGER)
                        ''')


# Initialize table
logger.info("Initializing Sqlite DB")
table_create()


def insert_data(user: str, token: str, discord_id: int):
    try:
        cursor.execute('''
        INSERT INTO users (user, token, discord_id) VALUES (?, ?, ?)''',
                       (str(user), str(token), int(discord_id)))
        conn.commit()
        print(f"Inserted: {user} with token and discord_id")
        return True
    except sqlite3.IntegrityError:
        print(f"Failed to insert: {user}. User or token already exists.")
        return False


# Custom check for ownership
async def ownership_check(ctx: BaseContext):
    # Default only owner can use this bot
    ownership = os.getenv('OWNER_ONLY', True)
    if ownership:
        # Check to see if user is the owner while ownership var is true
        if ctx.bot.owner.username == ctx.user.username:
            logger.info(f"{ctx.user.username}, you are the owner and ownership is enabled!")
            return True

        else:
            logger.warning(f"{ctx.user.username}, is not the owner and ownership is enabled!")
            return False
    else:
        return True


# Function to search for a specific user and token
def search_user_token(discord_id):
    cursor.execute('''
    SELECT user, token FROM users WHERE discord_id = ?
    ''', (discord_id,))

    rows = cursor.fetchall()

    return rows


class MultiUser(Extension):
    def __init__(self, bot):
        self.userLogin = False
        self.user_discord_id = ''

    @check(ownership_check)
    @slash_command(name="user-login", description="Login into ABS", dm_permission=False)
    @slash_option(name="username", description="ABS username", opt_type=OptionType.STRING, required=True)
    @slash_option(name="password", description="ABS password", opt_type=OptionType.STRING, required=True)
    async def user_login(self, ctx, username: str, password: str):
        author_discord_id = ctx.author.id
        self.user_discord_id = author_discord_id

        user_result = search_user_token(int(author_discord_id))
        user_info = c.bookshelf_user_login(username, password)

        abs_token = user_info["token"]
        abs_username = user_info["username"]
        abs_user_type = user_info["type"]

        if not user_result:

            if abs_token != "":
                insert_result = insert_data(abs_username, abs_token, author_discord_id)
                if insert_result:
                    await ctx.send(content=f"Successfully logged in as {abs_username}, type: {abs_user_type}",
                                   ephemeral=True)
                    self.userLogin = True
                    logger.warning(
                        f'user {ctx.author} logged in to ABS, changing token to assigned user: {abs_username}')
                    os.environ['bookshelfToken'] = abs_token

            else:
                await ctx.send(content="Invalid username or password", ephemeral=True)
                self.user_discord_id = ''

        else:

            retrieved_user = user_result[0][0]
            retrieved_token = user_result[0][1]
            abs_stored_token = os.environ.get('bookshelfToken')

            if retrieved_token == 0:
                insert_result = insert_data(abs_username, abs_token, author_discord_id)
                if insert_result:
                    logger.warning(
                        f'user {ctx.author} logged in to ABS, changing token to assigned user: {abs_username}')
                    os.environ['bookshelfToken'] = abs_token
                    await ctx.send(content=f"Successfully logged in as {abs_username}, type: {abs_user_type}.",
                                   ephemeral=True)

            if retrieved_token == abs_stored_token:
                await ctx.send(content=f"login already registered, registration tied to abs user: {retrieved_user}",
                               ephemeral=True)
                self.userLogin = True

            else:
                logger.warning(f'user {ctx.author} logged in to ABS, changing token to assigned user: {abs_username}')
                os.environ['bookshelfToken'] = retrieved_token
                await ctx.send(content=f"Successfully logged in as {abs_username}, type: {abs_user_type}.",
                               ephemeral=True)
