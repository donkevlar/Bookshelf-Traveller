import os

from interactions import *
import bookshelfAPI as c
import logging
import sqlite3

logger = logging.getLogger("bot")

# Initialize sqlite3 connection
conn = sqlite3.connect('user_info.db')
cursor = conn.cursor()


def table_create():
    cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
id INTEGER PRIMARY KEY,
user TEXT NOT NULL,
token TEXT NOT NULL UNIQUE,
discord_id INTEGER NOT NULL)
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
def search_user_db(discord_id=0, user='', token=''):
    if discord_id != 0:
        cursor.execute('''
        SELECT token, user FROM users WHERE discord_id = ?
        ''', (discord_id,))
        rows = cursor.fetchall()
    elif token != '':
        cursor.execute('''
                SELECT user FROM users WHERE token = ?
                ''', (token,))
        rows = cursor.fetchone()
    elif discord_id != 0 and user != '':
        cursor.execute('''
                SELECT token FROM users WHERE discord_id = ? AND user = ?
                ''', (discord_id, user))
        rows = cursor.fetchone()
    elif user != '':
        cursor.execute('''SELECT token FROM users WHERE user = ?''', (user,))
        rows = cursor.fetchone()

    else:
        cursor.execute('''SELECT user, token FROM users''')

        rows = cursor.fetchall()

    return rows


class MultiUser(Extension):
    def __init__(self, bot):
        self.user_discord_id = ''

    @check(ownership_check)
    @slash_command(name="user-login", description="Login into ABS", dm_permission=False)
    @slash_option(name="username", description="ABS username", opt_type=OptionType.STRING, required=True)
    @slash_option(name="password", description="ABS password", opt_type=OptionType.STRING, required=True)
    async def user_login(self, ctx, username: str, password: str):
        author_discord_id = ctx.author.id
        self.user_discord_id = author_discord_id

        user_info = c.bookshelf_user_login(username, password)

        abs_token = user_info["token"]
        abs_username = user_info["username"]
        abs_user_type = user_info["type"]

        logger.info("Attempting to find logged in user...")
        user_result = search_user_db(int(author_discord_id), abs_username)
        print(user_result)

        if not user_result:
            logger.info("SQLite DB search returned nothing, attempting to insert new record.")

            if abs_token != "":
                logger.info(f"Registering user into sqlite db with username: {abs_username}, "
                            f"discord_id: {author_discord_id}")
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
            logger.info("SQLite found associated token, proceeding to update ENV VARS...")
            retrieved_token = [0][0]
            retrieved_token = str(retrieved_token)

            abs_stored_token = os.environ.get('bookshelfToken')

            if retrieved_token == "":
                insert_result = insert_data(abs_username, abs_token, author_discord_id)
                if insert_result:
                    logger.info("Option 1 executed")
                    logger.warning(
                        f'user {ctx.author} logged in to ABS, changing token to assigned user: {abs_username}')
                    os.environ['bookshelfToken'] = abs_token
                    await ctx.send(content=f"Successfully logged in as {abs_username}, type: {abs_user_type}.",
                                   ephemeral=True)

            elif retrieved_token == abs_stored_token:
                logger.info("Option 2 executed")
                await ctx.send(content=f"login already registered, registration tied to abs user: {abs_username}",
                               ephemeral=True)

            elif retrieved_token != abs_stored_token:
                logger.info("Option 3 executed")
                os.environ['bookshelfToken'] = retrieved_token
                logger.warning(f'user {ctx.author} logged in to ABS, changing token to assigned user: {abs_username}')
                await ctx.send(content=f"Successfully logged in as {abs_username}.",
                               ephemeral=True)

            else:
                logger.info('Option 4 executed')
                os.environ['bookshelfToken'] = retrieved_token
                info = search_user_db(int(author_discord_id))
                retrieved_user = info[0][1]
                logger.warning(f'user {ctx.author} logged in to ABS, changing token to assigned user: {retrieved_user}')
                await ctx.send(content=f"Successfully logged in as {retrieved_user}.",
                               ephemeral=True)

    @check(ownership_check)
    @slash_command(name="select",
                   description="log a user in via db pull")
    @slash_option(name="user", description="Select from previously logged in users.", opt_type=OptionType.STRING,
                  required=True, autocomplete=True)
    async def user_select_db(self, ctx, user):
        abs_stored_token = os.getenv('bookshelfToken')
        user_result = search_user_db(user=user)

        if user_result:
            token = user_result[0]
            user_info = c.bookshelf_user_login(token=token)
            username = user_info['username']
            if token == abs_stored_token:
                await ctx.send(content=f"user: {username} already logged in.", ephemeral=True)
                return
            elif username == user:
                os.environ['bookshelfToken'] = token
                await ctx.send(content=f'Successfully logged in as user {username}', ephemeral=True)
            else:
                await ctx.send(content="Error occured, please try again later.", ephemeral=True)
        else:
            await ctx.send(content="Error occured, please try again later.", ephemeral=True)

    @slash_command(name='user', description="display the currently logged in ABS user", dm_permission=False)
    async def user_check(self, ctx):
        abs_stored_token = os.getenv('bookshelfToken')
        discord_id = ctx.author.id
        result = search_user_db(token=abs_stored_token)
        if result:
            username = result[0]
            await ctx.send(content=f"user {username} is currently logged in.", ephemeral=True)
        else:
            user_call = c.bookshelf_user_login(token=abs_stored_token)
            if user_call == 200:
                username = user_call['username']
                user_insert = insert_data(discord_id=discord_id, token=abs_stored_token, user=username)
                if user_insert:
                    await ctx.send(content=f"user {username} is currently logged in.", ephemeral=True)
            else:
                await ctx.send(content=f"Error occured, please visit logs for details and try again later.", ephemeral=True)

    @user_select_db.autocomplete(option_name="user")
    async def user_search_autocomplete(self, ctx: AutocompleteContext):
        choices = []
        user_result = search_user_db()
        if user_result:
            for users in user_result:
                username = users[0]
                choices.append({'name': username, "value": username})
        await ctx.send(choices=choices)
