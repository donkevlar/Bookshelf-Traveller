from interactions import *
import os
import bookshelfAPI as c
import settings as s
import logging

# Logger Config
logger = logging.getLogger("bot")

EPHEMERAL_OUTPUT = s.EPHEMERAL_OUTPUT


def option_library_name():
    def wrapper(func):
        return slash_option(
            name="library_name",
            opt_type=OptionType.STRING,
            description="Select a library",
            required=True,
            autocomplete=True
        )(func)

    return wrapper


class ABSAdmin(Extension):
    def __init__(self, bot):
        pass

    # Custom check for ownership
    async def ownership_check(self, ctx: BaseContext): # NOQA
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

    # Searches for a specific user, uses autocomplete to retrieve the inputted name
    @slash_command(name="user-search",
                   description="Searches for a specific user, case sensitive")
    @check(ownership_check)
    @slash_option(name="name", description="enter a valid username", required=True, opt_type=OptionType.STRING)
    async def search_user(self, ctx: SlashContext, name: str):
        try:
            isFound, username, user_id, last_seen, isActive = c.bookshelf_get_users(name)

            if isFound:
                formatted_data = (
                    f'Last Seen: {last_seen}\n'
                    f'is Active: {isActive}\n'
                )

                # Create Embed Message
                embed_message = Embed(
                    title=f"User Info | {username}",
                    description=f"User information for {username}",
                    color=ctx.author.accent_color
                )
                embed_message.add_field(name="Username", value=username, inline=False)
                embed_message.add_field(name="User ID", value=user_id, inline=False)
                embed_message.add_field(name="General Information", value=formatted_data, inline=False)

                # Send message
                await ctx.send(embed=embed_message, ephemeral=EPHEMERAL_OUTPUT)
                logger.info(f' Successfully sent command: search_user')

        except TypeError as e:
            await ctx.send("Could not find that user, try a different name or make sure that it is spelt correctly.",
                           ephemeral=EPHEMERAL_OUTPUT)
            logger.warning(f' Error: {e}')

        except Exception as e:
            await ctx.send("Could not complete this at the moment, please try again later.", ephemeral=EPHEMERAL_OUTPUT)
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occurred: {e} | Command Name: search_user')

    # Autocomplete searches the username within the abs api
    @search_user.autocomplete("name")
    async def user_search_autocomplete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        isFound, username, user_id, last_seen, isActive = c.bookshelf_get_users(user_input)
        choice = []
        if user_input.lower() == username.lower():
            choice = [{"name": f"{username}", "value": f"{username}"}]

        await ctx.send(choices=choice)

    # Create user
    @slash_command(name="add-user",
                   description="Will create a user, user types: 'admin', 'guest', 'user' | Default = user")
    @check(ownership_check)
    @slash_option(name="name", description="enter a valid username", required=True, opt_type=OptionType.STRING)
    @slash_option(name="password", description="enter a unique password, note: CHANGE THIS LATER", required=True,
                  opt_type=OptionType.STRING)
    @slash_option(name="user_type", description="select user type", required=True, opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="email", description="enter a valid email address", required=False, opt_type=OptionType.STRING)
    async def add_user(self, ctx: SlashContext, name: str, password: str, user_type="user", email=None):
        try:
            user_id, c_username = c.bookshelf_create_user(name, password, user_type, email=email)
            await ctx.send(f"Successfully Created User: {c_username} with ID: {user_id}", ephemeral=True)
            logger.info(f' Successfully sent command: add-user')

        except Exception as e:
            await ctx.send("Could not complete this at the moment, please try again later.", ephemeral=True)
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occurred: {e} | Command Name: add-user')

    # Autocomplete for user types, static choices
    @add_user.autocomplete("user_type")
    async def autocomplete_user_search_type(self, ctx: AutocompleteContext):
        choices = [
            {"name": "Admin", "value": "admin"},
            {"name": "User", "value": "user"},
            {"name": "Guest", "value": "guest"}
        ]

        await ctx.send(choices=choices)
