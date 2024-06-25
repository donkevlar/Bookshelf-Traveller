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
user TEXT,
token TEXT UNIQUE,
discord_id INTEGER UNIQUE)
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

    @slash_command(name="user-login", description="Login into ABS", dm_permission=False)
    @slash_option(name="username", description="ABS username", opt_type=OptionType.STRING, required=True)
    @slash_option(name="password", description="ABS password", opt_type=OptionType.STRING, required=True)
    async def user_login(self, ctx, username: str, password: str):
        author_discord_id = ctx.author.id

        result = search_user_token(int(author_discord_id))
        user_info = c.bookshelf_user_login(username, password)

        abs_token = user_info["token"]
        abs_username = user_info["username"]
        abs_user_type = user_info["type"]

        if not result:

            if abs_token != "":
                r = insert_data(abs_username, abs_token, author_discord_id)
                if r:
                    await ctx.send(content=f"Successfully logged in as {abs_username}, type: {abs_user_type}",
                                   ephemeral=True)
                    self.userLogin = True

            else:
                await ctx.send(content="Invalid username or password", ephemeral=True)

        else:

            retrieved_user = result[0][0]
            retrieved_token = result[0][1]

            await ctx.send(content=f"login already registered, registration tied to abs user: {retrieved_user}",
                           ephemeral=True)
            self.userLogin = True
