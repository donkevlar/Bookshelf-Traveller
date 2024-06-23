from interactions import Extension, slash_command, SlashContext, slash_option, OptionType, AutocompleteContext, Task, \
    IntervalTrigger
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings as s
import logging

# Logger Config
logger = logging.getLogger("bot")

# Update Frequency for session sync
updateFrequency = s.UPDATES


class AudioPlayBack(Extension):
    def __init__(self, bot):
        # Session VARS
        self.sessionID = ''
        self.bookItemID = ''
        self.bookTitle = ''
        self.currentTime = 0.0
        # Chapter VARS
        self.currentChapter = None
        self.chapterArray = None
        self.currentChapterTitle = ''
        self.bookFinished = False
        self.nextTime = None
        # Audio VARS
        self.audioObj = AudioVolume(src='')
        self.placeholder = None

    @Task.create(IntervalTrigger(seconds=updateFrequency))
    async def session_update(self):
        logger.info("Initializing Session Sync")
        c.bookshelf_session_update(itemID=self.bookItemID, sessionID=self.sessionID, currentTime=updateFrequency-0.5, nextTime=self.nextTime) # NOQA
        current_chapter, chapter_array, bookFinished = c.bookshelf_get_current_chapter(self.bookItemID)
        logger.info("Current Chapter Sync: " + current_chapter['title'] + "\n")
        self.currentChapter = current_chapter

    @slash_command(name="play", description="Play audio from ABS server")
    @slash_option(name="book", description="Enter a book title", required=True, opt_type=OptionType.STRING,
                  autocomplete=True)
    async def play_audio(self, ctx, book: str):
        logger.info(f"executing command /play")

        current_chapter, chapter_array, bookFinished = c.bookshelf_get_current_chapter(book)

        if bookFinished:
            await ctx.send(content="Book finished, please mark it as unfinished in UI. Aborting.", ephemeral=True)
            return

        # Get Bookshelf Playback URI, Starts new session
        audio_obj, currentTime, sessionID, bookTitle = c.bookshelf_audio_obj(book)

        # Audio Object Arguments
        audio = AudioVolume(audio_obj)
        audio.buffer_seconds = 10
        audio.locked_stream = True
        audio.ffmpeg_before_args = f"-ss {currentTime}"

        # Class VARS

        # Session Vars
        self.sessionID = sessionID
        self.bookItemID = book
        self.bookTitle = bookTitle
        self.audioObj = audio
        self.currentTime = currentTime

        # Chapter Vars
        self.currentChapter = current_chapter
        self.currentChapterTitle = current_chapter.get('title')
        self.chapterArray = chapter_array
        self.bookFinished = bookFinished

        # check if bot currently connected to voice
        if not ctx.voice_state:

            # if we haven't already joined a voice channel
            try:
                # Connect to voice channel
                await ctx.author.voice.channel.connect()

                # Start Session Updates
                self.session_update.start()

                await ctx.send(f"Playing: {self.bookTitle}", ephemeral=s.EPHEMERAL_OUTPUT)
                logger.info(f"Beginning audio stream")

                # Start audio playback
                await ctx.voice_state.play_no_wait(audio)

            except Exception as e:
                # Stop Session Update Tasks
                self.session_update.stop()
                # Close ABS session
                c.bookshelf_close_session(sessionID) # NOQA
                # Cleanup discord interactions
                await ctx.author.voice.channel.disconnect()
                await ctx.author.channel.send(f'Issue with playback: {e}')
                audio.cleanup() # NOQA

                print(e)

        # Play Audio, skip channel connection
        else:
            try:
                print("\nVoice already connected, playing new audio selection.")

                await ctx.voice_state.play_no_wait(audio)

            except Exception as e:

                await ctx.voice_state.stop()
                await ctx.author.voice.channel.disconnect()
                await ctx.author.channel.send(f'Issue with playback: {e}')
                logger.warning(f"Error occured during execution of /play : \n {e}")
                print(e)

        # Check if bot is playing something
        if not ctx.voice_state:
            # Stop any running tasks
            if self.session_update.running:
                self.session_update.stop()
            # close ABS session
            c.bookshelf_close_session(sessionID)
            return

    @slash_command(name="pause", description="pause audio")
    async def pause_audio(self, ctx):
        if ctx.voice_state:
            await ctx.send("Pausing Audio", ephemeral=s.EPHEMERAL_OUTPUT)
            logger.info(f"executing command /pause")
            print("Pausing Audio")
            ctx.voice_state.pause()
            # Stop Any Tasks Running
            if self.session_update.running:
                self.session_update.stop()
        else:
            await ctx.send(content="Bot isn't connected to channel, aborting.", ephemeral=True)

    @slash_command(name="resume", description="resume audio")
    async def resume_audio(self, ctx):
        if ctx.voice_state:
            if self.sessionID != "":
                await ctx.send("Resuming Audio", ephemeral=s.EPHEMERAL_OUTPUT)
                logger.info(f"executing command /resume")
                print("Resuming Audio")
                ctx.voice_state.resume()

                # Start session
                self.session_update.start()
            else:
                await ctx.send(content="Bot isn't connected to channel, aborting.", ephemeral=s.EPHEMERAL_OUTPUT)

    @slash_command(name="change-chapter", description="play next chapter, if available.")
    @slash_option(name="option", description="Select 'next or 'previous' as options", opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    async def change_chapter(self, ctx, option: str):
        if ctx.voice_state:
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
                found_next_chapter = False
                print(nextChapterID)

                for chapter in ChapterArray:
                    chapterID = int(chapter.get('id'))

                    if nextChapterID == chapterID:

                        chapterStart = float(chapter.get('start'))
                        newChapterTitle = chapter.get('title')

                        logger.info(f"Selected Chapter: {newChapterTitle}, Starting at: {chapterStart}")

                        audio_obj, currentTime, sessionID, bookTitle = c.bookshelf_audio_obj(self.bookItemID)
                        self.sessionID = sessionID
                        self.currentTime = currentTime

                        audio = AudioVolume(audio_obj)
                        audio.ffmpeg_before_args = f"-ss {chapterStart}"
                        self.audioObj = audio

                        # Set next time to new chapter time
                        self.nextTime = chapterStart
                        self.session_update.stop()
                        # Send manual next chapter sync
                        c.bookshelf_session_update(itemID=self.bookItemID, sessionID=self.sessionID,
                                                   currentTime=updateFrequency - 0.5, nextTime=self.nextTime)
                        # Reset Next Time to None before starting task again
                        self.nextTime = None
                        self.session_update.start()
                        await ctx.send(content=f"Moving to chapter: {newChapterTitle}",
                                       ephemeral=s.EPHEMERAL_OUTPUT)

                        found_next_chapter = True

                        await ctx.voice_state.play_no_wait(audio)
                        break

                if not found_next_chapter:
                    await ctx.send(content=f"Book Finished or No New Chapter Found, aborting",
                                   ephemeral=s.EPHEMERAL_OUTPUT)
        else:
            await ctx.send(content="Bot isn't connected to channel, aborting.", ephemeral=s.EPHEMERAL_OUTPUT)

    @slash_command(name="stop", description="Will disconnect from the voice channel and stop audio.")
    async def stop_audio(self, ctx: SlashContext):
        if ctx.voice_state:
            logger.info(f"executing command /stop")
            await ctx.send(content="Disconnected from audio channel and stopping playback.", ephemeral=True)
            await ctx.author.voice.channel.disconnect()

            if self.session_update.running:
                self.session_update.stop()
                c.bookshelf_close_session(self.sessionID)
        else:
            await ctx.send(content="Bot isn't connected to channel, aborting.", ephemeral=True)

    # Auto complete options below
    #
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



