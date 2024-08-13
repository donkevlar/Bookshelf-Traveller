import json

import json5
import logging
import os
import sqlite3

from interactions.ext.paginators import Paginator

import bookshelfAPI as c

from interactions import *

from settings import DEBUG_MODE, DEFAULT_PROVIDER, bookshelf_traveller_footer

logger = logging.getLogger("bot")

# Create new relative path
tasks_db_path = 'db/wishlist.db'
os.makedirs(os.path.dirname(tasks_db_path), exist_ok=True)

# Initialize sqlite3 connection

wishlist_conn = sqlite3.connect(tasks_db_path)
wishlist_cursor = wishlist_conn.cursor()


def table_create():
    wishlist_cursor.execute('''
CREATE TABLE IF NOT EXISTS wishlist (
id INTEGER PRIMARY KEY,
title TEXT NOT NULL,
author TEXT NOT NULL,
description TEXT NOT NULL,
cover TEXT,
provider TEXT NOT NULL,
provider_id TEXT NOT NULL, 
discord_id INTEGER NOT NULL,
book_data TEXT NOT NULL,
UNIQUE(title, author)
)
                        ''')


# Initialize Table
logger.info("Initializing wishlist table")
table_create()


def insert_wishlist_data(title: str, author: str, description: str, cover: str, provider: str, provider_id: str,
                         discord_id: int, data: str):
    try:
        wishlist_cursor.execute('''
        INSERT INTO wishlist (title, author, description, cover, provider, provider_id, discord_id, book_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                                (str(title), str(author), str(description), str(cover), str(provider), str(provider_id),
                                 int(discord_id), str(data)))
        wishlist_conn.commit()
        logger.info(f"Inserted: {title} by author {author}")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Failed to insert: {title}. title and author already exists under this discord_id.")
        return False


def search_wishlist_db(discord_id: int = 0, title=""):
    logger.debug('Searching for books in wishlist db!')
    if discord_id == 0 and title == "":
        wishlist_cursor.execute(
            '''SELECT title, author, description, cover, provider, provider_id, discord_id, book_data FROM wishlist''')

        rows = wishlist_cursor.fetchall()
    elif discord_id != 0 and title =="":
        logger.debug("Searching wishlist db using discord id!")
        wishlist_cursor.execute(
            '''SELECT title, author, description, cover, provider, provider_id, discord_id, book_data FROM wishlist WHERE discord_id = ?''', (discord_id,))

        rows = wishlist_cursor.fetchall()

    elif title != "" and discord_id == 0:
        wishlist_cursor.execute(
            '''SELECT discord_id, book_data, title FROM wishlist WHERE title LIKE ?''',
            (title,))

        rows = wishlist_cursor.fetchall()

    return rows # NOQA


async def wishlist_search_embed(title: str, title_desc: str, author: str, cover: str, additional_info: str, footer=''):
    embed_message = Embed(title=title, description=title_desc)
    embed_message.add_field(name='Author', value=author)
    embed_message.add_field(name='Additional Information', value=additional_info, inline=False)
    embed_message.add_image(cover)
    embed_message.footer = bookshelf_traveller_footer + " | " + footer

    return embed_message


def remove_book_db(title: str, discord_id: int):
    logger.warning(f'Attempting to delete user {title} from db!')
    try:
        wishlist_cursor.execute("DELETE FROM wishlist WHERE title = ? AND discord_id = ?", (title, int(discord_id)))
        wishlist_conn.commit()
        logger.info(f"Successfully deleted title {title} from db!")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error while attempting to delete {title}: {e}")
        return False


component_initial: list[ActionRow] = [
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY,
            label="Request",
            custom_id="request_button"
        ),
        Button(
            style=ButtonStyle.RED,
            label="Cancel",
            custom_id="cancel_button"
        )
    )
]

component_success = Button(
    style=ButtonStyle.SUCCESS,
    label="Success!",
    disabled=True
)

component_fail = Button(
    style=ButtonStyle.RED,
    label="Failed!",
    disabled=True
)


class WishList(Extension):
    def __init__(self, bot):
        self.searchBookData = None
        self.messageString = ''
        self.selectedBook = {}
        self.searchComponents = None
        self.completeAudioLibrary = []

    @slash_command(name='add-book', description='Add a book to your wishlist. Server wide command.')
    @slash_option(name='title', description='Book Title', opt_type=OptionType.STRING, required=True)
    async def add_book_command(self, ctx: SlashContext, title: str):
        await ctx.defer(ephemeral=True)
        book_search = await c.bookshelf_search_books(title=title)
        title_list = []
        count = 0
        options = []
        book_list = []
        valid = False

        if DEBUG_MODE == "True":
            print(book_search)

        for books in book_search:

            book_title = books.get('title')
            book_author = books.get('author')
            book_published = books.get('publishedYear')
            book_publisher = books.get('publisher')

            if book_title not in title_list:
                title_list.append(book_title)
                count += 1
                books['internal_id'] = count

                desc_component = f"Author: {book_author} | Year: {book_published}"
                if len(desc_component) <= 100:
                    pass
                else:
                    desc_component = f"Year: {book_published} | Publisher: {book_publisher}"

                if count <= 25 and book_title is not None:
                    valid = True
                    options.append(StringSelectOption(label=book_title, value=str(count),
                                                      description=desc_component))
                    book_list.append(books)

        components = StringSelectMenu(
            options,  # NOQA
            min_values=1,
            max_values=1,
            placeholder="",
            custom_id='search_select_menu')
        try:
            if count >= 1 and valid:
                await ctx.send(f"Search Result for Title **{title}**, provided by **{DEFAULT_PROVIDER}**",
                               components=components, ephemeral=True)
                self.messageString = f"Search Result for Title **{title}**, provided by **{DEFAULT_PROVIDER}**"
                self.searchBookData = book_list
            else:
                await ctx.send(f"No results found for title **{title}**", ephemeral=True)

        except Exception as e:
            logger.error(f"Error occured: {e}")
            await ctx.send(f"An error occured while trying to search for book title {title}. Normally this occurs if the title has a bad typo or if there are too many results. Visit logs for details.")

    @slash_command(name='remove-book', description="Manually remove a book from your wishlist.")
    @slash_option(name='book', description='Your wishlist of books. Note: If empty, no books were found.', opt_type=OptionType.STRING, required=True, autocomplete=True)
    async def remove_book_command(self, ctx: SlashContext, book: str):
        await ctx.defer(ephemeral=True)
        result = remove_book_db(discord_id=ctx.author_id, title=book)
        if result:
            await ctx.send(f"Successfully removed {book} from your wishlist!", ephemeral=True)
        else:
            await ctx.send(f"Failed to remove {book} from your wishlist, please visit logs for additional details.", ephemeral=True)

    @slash_command(name='wishlist', description='View your wishlist')
    async def view_wishlist(self, ctx: SlashContext):
        result = search_wishlist_db(ctx.author_id)
        embeds = []
        count = 0
        if result:
            for item in result:
                count += 1
                logger.debug(f"Wishlist DB Result {count}: {item[7]}")
                book_dict = json5.loads(item[7])

                title = book_dict.get('title')
                subtitle = book_dict.get('subtitle')
                author = book_dict.get('author')
                narrators = book_dict.get('narrator')
                cover = book_dict.get('cover')
                publisher = book_dict.get('publisher')
                provider = DEFAULT_PROVIDER
                published = book_dict.get('publishedYear')

                add_info = f"Publisher: **{publisher}**\nYear Published: **{published}**\nProvided by: **{provider}**\nNarrator: **{narrators}**\n"

                embed_message = await wishlist_search_embed(title=title, author=author, cover=cover, additional_info=add_info, title_desc=subtitle, footer=f'Search Provider: {provider}')
                embeds.append(embed_message)

            paginator = Paginator.create_from_embeds(self.client, *embeds)
            await paginator.send(ctx, ephemeral=True)

        else:
            await ctx.send("You currently don't have any items in your wishlist. Please use **`/add-book`** to add items to your wishlist.", ephemeral=True)

    # Autocomplete -------------------------------------------------
    @remove_book_command.autocomplete('book')
    async def book_search_autocomplete(self, ctx: AutocompleteContext):
        choices = []
        result = search_wishlist_db(ctx.author_id)
        if result:
            for item in result:
                book_data = json5.loads(item[7])
                title = book_data.get('title')
                choices.append({"name": title, "value": title})
        await ctx.send(choices=choices)

    # Component Callbacks -----------------------------------------
    @component_callback('search_select_menu')
    async def on_search_menu_select(self, ctx: ComponentContext):
        selected_value = ctx.values
        extracted_value = ''

        for value in selected_value:
            extracted_value = value

        for book in self.searchBookData:
            internal_id = book.get('internal_id')
            if int(extracted_value) == int(internal_id):
                print(book)
                self.selectedBook = book

                title = book.get('title')
                subtitle = book.get('subtitle')
                language = book.get('language')
                author = book.get('author')
                narrator = book.get('narrator')
                published = book.get('publishedYear')
                cover = book.get('cover')
                provider = DEFAULT_PROVIDER

                additional_info = f"Narrator(s): {narrator}\nPublished Year: {published}\nLanguage: {language}"

                embed_message = await wishlist_search_embed(title=title, author=author, cover=cover,
                                                            additional_info=additional_info, title_desc=subtitle, footer=f'Search Provider: {provider}')

                await ctx.edit_origin(content=f"You selected: **{title}**", embed=embed_message, components=component_initial)
                # Reset Vars
                self.searchBookData = None
                self.messageString = ''

            else:
                self.searchBookData = None
                self.messageString = ''

    @component_callback('request_button')
    async def request_button_callback(self, ctx: ComponentContext):
        # Book Variables
        title = self.selectedBook['title']
        author = self.selectedBook['author']
        description = self.selectedBook['description']
        cover = self.selectedBook['cover']
        provider = DEFAULT_PROVIDER
        discord_id = ctx.author_id

        if 'audible' in provider:
            provider_id = self.selectedBook['asin']
        else:
            provider_id = self.selectedBook['id']

        result = insert_wishlist_data(title=title, author=author, description=description, cover=cover, provider=provider,
                                      provider_id=provider_id, discord_id=discord_id, data=str(json.dumps(self.selectedBook)))
        if result:
            logger.info('Successfully added book to wishlist db!')
            await ctx.edit_origin(content=f"Successfully added title **{title}** to wishlist", components=component_success)
        else:
            logger.warning('Book title or author already exists, marking as failed!')
            await ctx.edit_origin(content="Request already exists!", components=component_fail)
        # Reset Vars
        self.selectedBook = None

    @component_callback('cancel_button')
    async def cancel_button_callback(self, ctx: ComponentContext):
        await ctx.edit_origin()
        await ctx.delete()

    # @listen()
    # async def wishlist_on_startup(self, event: Startup):
    #     result = search_task_db(override_response="Verifying if wishlist task is enabled and setup for startup!")
    #     task_name = 'add-book'
    #     task_list = []
    #     if result:
    #         for item in result:
    #             task = item[1]
    #             task_list.append(task)
    #
    #     if task_name in task_list:
    #         logger.info('Wishlist task setup found! Executing startup task!')
    #         if not self.wishlist_primary_task.running:
    #             self.wishlist_primary_task.start()
    #             owner = event.bot.owner
    #             if DEBUG_MODE != "True":
    #                 await owner.send(
    #                     f"Wishlist Task activated automatically! Refresh rate set to {TASK_FREQUENCY} minutes")
    #     else:
    #         logger.info("No wishlist task setup found during startup! Ignoring!")
