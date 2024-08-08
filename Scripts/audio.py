import sys
import time

import pytz
from interactions import *
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings as s
from settings import os, TIMEZONE
import logging
from datetime import datetime
from dotenv import load_dotenv

# Temp hot fix
from interactions.api.voice.voice_gateway import VoiceGateway, OP, random


# HOT FIX for voice - Remove once 5.14 has been released.
async def new_send_heartbeat(self) -> None:
    await self.send_json({"op": OP.HEARTBEAT, "d": random.getrandbits(64)})
    self.logger.debug("❤ Voice Connection is sending Heartbeat")

VoiceGateway.send_heartbeat = new_send_heartbeat

load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# Update Frequency for session sync
updateFrequency = s.UPDATES

# ENV VARS Specific to Audio Module
playback_role = int(s.PLAYBACK_ROLE)

# Default only owner can use this bot
ownership = s.OWNER_ONLY
ownership = eval(ownership)

# Timezone
timeZone = pytz.timezone(TIMEZONE)

# Button Vars
# Initial components loaded when play is first initialized
component_rows_initial: list[ActionRow] = [
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="Pause",
            custom_id='pause_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS,
            label="+",
            custom_id='volume_up_button'
        ),
        Button(
            style=ButtonStyle.RED,
            label="-",
            custom_id='volume_down_button')),
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="- 30s",
            custom_id='rewind_button'
        ),
        Button(
            style=ButtonStyle.SECONDARY,
            label="+ 30s",
            custom_id='forward_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY,
            label="Previous Chapter",
            custom_id='previous_chapter_button'
        ),
        Button(
            style=ButtonStyle.PRIMARY,
            label="Next Chapter",
            custom_id='next_chapter_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.RED,
            label="Stop",
            custom_id='stop_audio_button'
        )
    )
]
# Components when the audio is paused
component_rows_paused: list[ActionRow] = [
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY.SUCCESS,
            label='Play',
            custom_id='play_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS,
            label="+",
            custom_id='volume_up_button'
        ),
        Button(
            style=ButtonStyle.RED,
            label="-",
            custom_id='volume_down_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="- 30s",
            custom_id='rewind_button'
        ),
        Button(
            style=ButtonStyle.SECONDARY,
            label="+ 30s",
            custom_id='forward_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY,
            label="Previous Chapter",
            custom_id='previous_chapter_button'
        ),
        Button(
            style=ButtonStyle.PRIMARY,
            label="Next Chapter",
            custom_id='next_chapter_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.RED,
            label='Stop',
            custom_id='stop_audio_button'
        )
    )]


# Voice Status Check

# Custom check for ownership
async def ownership_check(ctx: BaseContext):  # NOQA

    logger.info(f'Ownership is currently set to: {ownership}')

    if ownership:
        logger.info('OWNERSHIP is enabled, verifying if user is authorized.')
        # Check to see if user is the owner while ownership var is true
        if ctx.bot.owner.id == ctx.user.id or ctx.user in ctx.bot.owners:
            logger.info('Verified, executing command!')
            return True
        else:
            logger.warning('User is not an owner!')
            return False

    else:
        logger.info('ownership is disabled! skipping!')
        return True


class AudioPlayBack(Extension):
    def __init__(self, bot):
        # ABS Vars
        self.cover_image = ''
        # Session VARS
        self.sessionID = ''
        self.bookItemID = ''
        self.bookTitle = ''
        self.currentTime = 0.0
        # Chapter VARS
        self.currentChapter = None
        self.chapterArray = None
        self.currentChapterTitle = ''
        self.newChapterTitle = ''
        self.found_next_chapter = False
        self.bookFinished = False
        self.nextTime = None
        # Audio VARS
        self.audioObj = AudioVolume
        self.context_voice_channel = None
        self.bitrate = 128000
        self.volume = 0.0
        self.placeholder = None
        self.playbackSpeed = 1.0
        self.isPodcast = False
        self.updateFreqMulti = updateFrequency * self.playbackSpeed
        self.play_state = 'stopped'
        # User Vars
        self.username = ''
        self.user_type = ''

    # Tasks ---------------------------------
    #
    @Task.create(trigger=IntervalTrigger(seconds=updateFrequency))
    async def session_update(self):
        logger.info(f"Initializing Session Sync, current refresh rate set to: {updateFrequency} seconds")

        updatedTime, duration, serverCurrentTime, finished_book = c.bookshelf_session_update(item_id=self.bookItemID,
                                                                                             session_id=self.sessionID,
                                                                                             current_time=updateFrequency,
                                                                                             next_time=self.nextTime)  # NOQA

        logger.info(f"Successfully synced session to updated time: {updatedTime}, session ID: {self.sessionID}")

        current_chapter, chapter_array, bookFinished, isPodcast = c.bookshelf_get_current_chapter(self.bookItemID,
                                                                                                  updatedTime)

        if not isPodcast:
            logger.info("Current Chapter Sync: " + current_chapter['title'])
            self.currentChapter = current_chapter

    @Task.create(trigger=IntervalTrigger(minutes=5))
    async def terminal_clearer(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        logger.warning('Cleared terminal after 5 minutes of playback!')

    # Random Functions ------------------------
    # Change Chapter Function
    def move_chapter(self, option: str):
        logger.info(f"executing command /next-chapter")
        CurrentChapter = self.currentChapter
        ChapterArray = self.chapterArray
        bookFinished = self.bookFinished

        if not bookFinished:

            currentChapterID = int(CurrentChapter.get('id'))
            if option == 'next':
                nextChapterID = currentChapterID + 1
            else:
                nextChapterID = currentChapterID - 1

            for chapter in ChapterArray:
                chapterID = int(chapter.get('id'))

                if nextChapterID == chapterID:
                    self.session_update.stop()
                    self.terminal_clearer.stop()
                    c.bookshelf_close_session(self.sessionID)
                    chapterStart = float(chapter.get('start'))
                    self.newChapterTitle = chapter.get('title')

                    logger.info(f"Selected Chapter: {self.newChapterTitle}, Starting at: {chapterStart}")

                    audio_obj, currentTime, sessionID, bookTitle = c.bookshelf_audio_obj(self.bookItemID)
                    self.sessionID = sessionID
                    self.currentTime = currentTime

                    audio = AudioVolume(audio_obj)
                    audio.ffmpeg_before_args = f"-ss {chapterStart}"
                    audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
                    self.audioObj = audio

                    # Set next time to new chapter time
                    self.nextTime = chapterStart

                    # Send manual next chapter sync
                    c.bookshelf_session_update(item_id=self.bookItemID, session_id=self.sessionID,
                                               current_time=updateFrequency - 0.5, next_time=self.nextTime)
                    # Reset Next Time to None before starting task again
                    self.nextTime = None
                    self.session_update.start()
                    self.terminal_clearer.start()
                    self.found_next_chapter = True

    def modified_message(self, color, chapter):
        now = datetime.now(tz=timeZone)
        formatted_time = now.strftime("%m-%d %H:%M:%S")
        # Create embedded message
        embed_message = Embed(
            title=f"{self.bookTitle}",
            description=f"Currently playing {self.bookTitle}",
            color=color,
        )

        # Add ABS user info
        user_info = f"Username: **{self.username}**\nUser Type: **{self.user_type}**"
        embed_message.add_field(name='ABS Information', value=user_info)

        embed_message.add_field(name='Playback Information', value=f"Current State: **{self.play_state.upper()}**"
                                                                   f"\nCurrent Chapter: **{chapter}**"
                                                                   f"\nCurrent volume: **{round(self.volume * 100)}%**")  # NOQA

        # Add media image (If using HTTPS)
        embed_message.add_image(self.cover_image)

        embed_message.footer = f'Powered by Bookshelf Traveller 🕮 | {s.versionNumber} | Last Update: {formatted_time}'

        return embed_message

    # Commands --------------------------------

    # Main play command, place class variables here since this is required to play audio
    @slash_command(name="play", description="Play audio from ABS server", dm_permission=False)
    @slash_option(name="book", description="Enter a book title", required=True, opt_type=OptionType.STRING,
                  autocomplete=True)
    async def play_audio(self, ctx, book: str):
        if playback_role != 0:
            logger.info('PLAYBACK_ROLE is currently active, verifying if user is authorized.')
            if not ctx.author.has_role(playback_role):  # NOQA
                logger.info('user not authorized to use this command!')
                await ctx.send(content='You are not authorized to use this command!', ephemeral=True)
                return
            else:
                logger.info('user verified!, executing command!')
        elif ownership and playback_role == 0:
            if ctx.author.id not in ctx.bot.owners:
                logger.warning(f'User {ctx.author} attempted to use /play, and OWNER_ONLY is enabled!')
                ctx.send(content="Ownership enabled and you are not authorized to use this command. Contact bot owner.")
                return

        # Check bot is ready, if not exit command
        if not self.bot.is_ready or not ctx.author.voice:
            await ctx.send(content="Bot is not ready or author not in voice channel, please try again later.",
                           ephemeral=True)
            return

        logger.info(f"executing command /play")

        current_chapter, chapter_array, bookFinished, isPodcast = c.bookshelf_get_current_chapter(item_id=book)

        if bookFinished:
            await ctx.send(content="Book finished, please mark it as unfinished in UI. Aborting.", ephemeral=True)
            return

        if isPodcast:
            await ctx.send(content="The content you attempted to play is currently not supported, aborting.",
                           ephemeral=True)
            return

        # Get Bookshelf Playback URI, Starts new session
        audio_obj, currentTime, sessionID, bookTitle = c.bookshelf_audio_obj(book)

        # Get Book Cover URL
        cover_image = c.bookshelf_cover_image(book)

        # Retrieve current user information
        username, user_type, user_locked = c.bookshelf_auth_test()

        # Audio Object Arguments
        audio = AudioVolume(audio_obj)
        audio.buffer_seconds = 5
        audio.locked_stream = True
        self.volume = audio.volume
        audio.ffmpeg_before_args = f"-ss {currentTime}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
        audio.bitrate = self.bitrate

        # Class VARS

        # ABS User Vars
        self.username = username
        self.user_type = user_type
        self.cover_image = cover_image

        # Session Vars
        self.sessionID = sessionID
        self.bookItemID = book
        self.bookTitle = bookTitle
        self.audioObj = audio
        self.currentTime = currentTime

        # Chapter Vars
        self.isPodcast = isPodcast
        self.currentChapter = current_chapter
        self.currentChapterTitle = current_chapter.get('title')
        self.chapterArray = chapter_array
        self.bookFinished = bookFinished
        self.context_voice_channel = ctx.voice_state
        self.play_state = 'playing'

        # Create embedded message
        embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

        # check if bot currently connected to voice
        if not ctx.voice_state:

            # if we haven't already joined a voice channel
            try:
                # Connect to voice channel
                await ctx.author.voice.channel.connect()

                # Start Tasks
                self.session_update.start()
                self.terminal_clearer.start()

                # Start Voice Check
                await ctx.defer(ephemeral=True)

                await ctx.send(embed=embed_message, ephemeral=True, components=component_rows_initial)

                logger.info(f"Beginning audio stream")

                await self.client.change_presence(activity=Activity.create(name=f"{self.bookTitle}",
                                                                           type=ActivityType.LISTENING))

                # Start audio playback
                await ctx.voice_state.play_no_wait(audio)

            except Exception as e:
                # Stop Any Associated Tasks
                self.session_update.stop()
                self.terminal_clearer.stop()
                # Close ABS session
                c.bookshelf_close_session(sessionID)  # NOQA
                # Cleanup discord interactions
                await ctx.author.voice.channel.disconnect()
                audio.cleanup()  # NOQA

                print(e)

        # Play Audio, skip channel connection
        else:
            try:
                logger.info("Voice already connected, playing new audio selection.")

                await ctx.voice_state.play_no_wait(audio)

            except Exception as e:

                await ctx.voice_state.stop()
                await ctx.author.voice.channel.disconnect()
                await self.client.change_presence(activity=None)
                await ctx.author.channel.send(f'Issue with playback: {e}')
                logger.error(f"Error occured during execution of /play : \n {e}")
                logger.error(e)

        # Check if bot is playing something
        if not ctx.voice_state:
            # Stop any running tasks
            if self.session_update.running:
                self.session_update.stop()
                self.terminal_clearer.stop()
            # close ABS session
            c.bookshelf_close_session(sessionID)
            return

    # Pause audio, stops tasks, keeps session active.
    @slash_command(name="pause", description="pause audio", dm_permission=False)
    async def pause_audio(self, ctx):
        if ctx.voice_state:
            await ctx.send("Pausing Audio", ephemeral=True)
            logger.info(f"executing command /pause")
            ctx.voice_state.pause()
            logger.info("Pausing Audio")
            self.play_state = 'paused'
            # Stop Any Tasks Running
            if self.session_update.running:
                self.session_update.stop()
                self.terminal_clearer.stop()
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    # Resume Audio, restarts tasks, session is kept open
    @slash_command(name="resume", description="resume audio", dm_permission=False)
    async def resume_audio(self, ctx):
        if ctx.voice_state:
            if self.sessionID != "":
                await ctx.send("Resuming Audio", ephemeral=True)
                logger.info(f"executing command /resume")
                # Resume Audio Stream
                ctx.voice_state.resume()
                logger.info("Resuming Audio")
                # Start session
                self.play_state = 'playing'
                self.session_update.start()
                self.terminal_clearer.start()
            else:
                await ctx.send(content="Bot or author isn't connected to channel, aborting.",
                               ephemeral=True)

    @check(ownership_check)
    @slash_command(name="change-chapter", description="play next chapter, if available.", dm_permission=False)
    @slash_option(name="option", description="Select 'next or 'previous' as options", opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    async def change_chapter(self, ctx, option: str):
        if ctx.voice_state:
            if self.isPodcast:
                await ctx.send(content="Item type is not book, chapter skip disabled", ephemeral=True)
                return

            self.move_chapter(option)

            await ctx.send(content=f"Moving to chapter: {self.newChapterTitle}", ephemeral=True)

            await ctx.voice_state.play_no_wait(self.audioObj)

            if not self.found_next_chapter:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting",
                               ephemeral=True)
            # Resetting Variable
            self.found_next_chapter = False
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @check(ownership_check)
    @slash_command(name="volume", description="change the volume for the bot", dm_permission=False)
    @slash_option(name="volume", description="Must be between 1 and 100", required=False, opt_type=OptionType.INTEGER)
    async def volume_adjuster(self, ctx, volume=0):
        if ctx.voice_state:
            audio = self.audioObj
            if volume == 0:
                await ctx.send(content=f"Volume currently set to: {self.volume * 100}%", ephemaral=True)
            elif volume >= 1 < 100:
                volume_float = float(volume / 100)
                audio.volume = volume_float
                self.volume = audio.volume
                await ctx.send(content=f"Volume set to: {volume}%", ephemaral=True)

            else:
                await ctx.send(content=f"Invalid Entry", ephemeral=True)
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @slash_command(name="stop", description="Will disconnect from the voice channel and stop audio.",
                   dm_permission=False)
    async def stop_audio(self, ctx: SlashContext):
        if ctx.voice_state:
            logger.info(f"executing command /stop")
            await ctx.send(content="Disconnected from audio channel and stopping playback.", ephemeral=True)
            await ctx.voice_state.channel.voice_state.stop()
            await ctx.author.voice.channel.disconnect()
            self.audioObj.cleanup()  # NOQA
            await self.client.change_presence(activity=None)

            if self.session_update.running:
                self.session_update.stop()
                self.terminal_clearer.stop()
                self.play_state = 'stopped'
                c.bookshelf_close_session(self.sessionID)
                c.bookshelf_close_all_sessions(10)

        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            c.bookshelf_close_all_sessions(10)

    @check(ownership_check)
    @slash_command(name="close-all-sessions",
                   description="DEBUGGING PURPOSES, close all active sessions. Takes up to 60 seconds.",
                   dm_permission=False)
    @slash_option(name="max_items", description="max number of items to attempt to close, default=100",
                  opt_type=OptionType.INTEGER)
    async def close_active_sessions(self, ctx, max_items=50):
        # Wait for task to complete
        ctx.defer()

        openSessionCount, closedSessionCount, failedSessionCount = c.bookshelf_close_all_sessions(max_items)

        await ctx.send(content=f"Result of attempting to close sessions. success: {closedSessionCount}, "
                               f"failed: {failedSessionCount}, total: {openSessionCount}", ephemeral=True)

    @check(ownership_check)
    @slash_command(name='refresh', description='re-sends your current playback card.')
    async def refresh_play_card(self, ctx: SlashContext):
        if ctx.voice_state:
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
            if self.play_state == "playing":
                await ctx.send(embed=embed_message, components=component_rows_initial, ephemeral=True)
            elif self.play_state == "paused":
                await ctx.send(embed=embed_message, components=component_rows_paused, ephemeral=True)
        else:
            return await ctx.send("Bot not in voice channel or an error has occured. Please try again later!",
                                  ephemeral=True)

    # -----------------------------
    # Auto complete options below
    # -----------------------------
    @play_audio.autocomplete("book")
    async def search_media_auto_complete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        choices = []
        if user_input == "":
            try:
                formatted_sessions_string, data = c.bookshelf_listening_stats()

                for sessions in data['recentSessions']:
                    title = sessions.get('displayTitle')
                    bookID = sessions.get('libraryItemId')
                    formatted_item = {"name": title, "value": bookID}

                    if formatted_item not in choices:
                        choices.append(formatted_item)

                await ctx.send(choices=choices)
                logger.info(choices)

            except Exception as e:
                await ctx.send(choices=choices)
                print(e)

        else:
            try:
                titles_ = c.bookshelf_title_search(user_input)
                for info in titles_:
                    book_title = info["title"]
                    book_id = info["id"]
                    choices.append({"name": f"{book_title}", "value": f"{book_id}"})

                await ctx.send(choices=choices)
                logger.info(choices)

            except Exception as e:  # NOQA
                await ctx.send(choices=choices)
                print(e)

    @change_chapter.autocomplete("option")
    async def chapter_option_autocomplete(self, ctx: AutocompleteContext):
        choices = [
            {"name": "next", "value": "next"}, {"name": "previous", "value": "previous"}
        ]
        await ctx.send(choices=choices)

    # Component Callbacks ---------------------------
    @component_callback('pause_audio_button')
    async def callback_pause_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Pausing Playback!')
            self.play_state = 'paused'
            ctx.voice_state.channel.voice_state.pause()
            self.session_update.stop()
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
            await ctx.edit_origin(content="Play", components=component_rows_paused, embed=embed_message)

    @component_callback('play_audio_button')
    async def callback_play_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Resuming Playback!')
            self.play_state = 'playing'
            ctx.voice_state.channel.voice_state.resume()
            self.session_update.start()
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            await ctx.edit_origin(components=component_rows_initial, embed=embed_message)

    @component_callback('next_chapter_button')
    async def callback_next_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Moving to next chapter!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=component_rows_initial)
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=component_rows_paused)
                ctx.voice_state.channel.voice_state.player.stop()

            # Find next chapter
            self.move_chapter(option='next')

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.newChapterTitle)

            if self.found_next_chapter:
                await ctx.edit(embed=embed_message)
                await ctx.voice_state.channel.voice_state.play_no_wait(self.audioObj)  # NOQA
            else:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting", ephemeral=True)

            # Resetting Variable
            self.found_next_chapter = False

    @component_callback('previous_chapter_button')
    async def callback_previous_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Moving to previous chapter!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=component_rows_initial)
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=component_rows_paused)
                ctx.voice_state.channel.voice_state.player.stop()
            else:
                await ctx.send(content='Error with previous chapter command, bot not active or voice not connected!',
                               ephemeral=True)
                return

            # Find previous chapter
            self.move_chapter(option='previous')

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.newChapterTitle)

            if self.found_next_chapter:
                await ctx.edit(embed=embed_message)
                # Resetting Variable
                self.found_next_chapter = False
                ctx.voice_state.channel.voice_state.player.stop()
                await ctx.voice_state.channel.voice_state.play_no_wait(self.audioObj)  # NOQA

            else:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting", ephemeral=True)

    @component_callback('stop_audio_button')
    async def callback_stop_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Stopping Playback!')
            await ctx.voice_state.channel.voice_state.stop()
            await ctx.edit_origin()
            await ctx.delete()
            self.audioObj.cleanup()  # NOQA
            self.session_update.stop()
            await ctx.voice_state.channel.disconnect()
            await self.client.change_presence(activity=None)
            # Cleanup Session
            c.bookshelf_close_session(self.sessionID)

    @component_callback('volume_up_button')
    async def callback_volume_up_button(self, ctx: ComponentContext):
        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1
            # Update Audio OBJ
            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = self.volume + adjustment  # NOQA
            self.volume = audio.volume

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            await ctx.edit_origin(embed=embed_message)
            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('volume_down_button')
    async def callback_volume_down_button(self, ctx: ComponentContext):
        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1

            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = self.volume - adjustment  # NOQA
            self.volume = audio.volume

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            await ctx.edit_origin(embed=embed_message)

            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('forward_button')
    async def callback_forward_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)
        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.pause()
        c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA

        audio_obj, currentTime, sessionID, bookTitle = c.bookshelf_audio_obj(self.bookItemID)

        self.sessionID = sessionID
        self.currentTime = currentTime

        print(self.currentTime)

        self.nextTime = self.currentTime + 30.0
        logger.info(f"Moving to time using forward:  {self.nextTime}")

        audio = AudioVolume(audio_obj)

        audio.ffmpeg_before_args = f"-ss {self.nextTime}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"
        self.audioObj = audio
        self.session_update.start()
        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play_no_wait(self.audioObj)  # NOQA

    @component_callback('rewind_button')
    async def callback_rewind_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)
        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.pause()
        c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA
        audio_obj, currentTime, sessionID, bookTitle = c.bookshelf_audio_obj(self.bookItemID)

        self.currentTime = currentTime
        self.sessionID = sessionID
        self.nextTime = self.currentTime - 30.0
        logger.info(f"Moving to time using rewind: {self.nextTime}")

        audio = AudioVolume(audio_obj)

        audio.ffmpeg_before_args = f"-ss {self.nextTime}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"
        self.audioObj = audio
        self.session_update.start()
        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play_no_wait(self.audioObj)  # NOQA

    # ----------------------------
    # Other non discord related functions
    # ----------------------------
