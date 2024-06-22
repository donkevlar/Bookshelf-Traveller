from interactions import Extension, slash_command, SlashContext, slash_option, OptionType, AutocompleteContext, Task, \
    IntervalTrigger
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings
import logging

# Logger Config
logger = logging.getLogger("bot")

# Update Frequency for session sync
updateFrequency = settings.UPDATES


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
        self.bookFinished = False
        self.moveToTime = 0.0
        # Audio VARS
        self.audioObj = AudioVolume(src='')
        self.placeholder = None

    @Task.create(IntervalTrigger(seconds=updateFrequency))
    async def session_update(self):
        print("Initializing Session Sync")
        updatedTime = c.bookshelf_session_update(itemID=self.bookItemID, sessionID=self.sessionID, currentTime=updateFrequency-0.5)
        self.currentTime = updatedTime

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

                await ctx.send(f"Playing: {self.bookTitle}", ephemeral=True)

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
            await ctx.send("Pausing Audio", ephemeral=True)
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
                await ctx.send("Resuming Audio", ephemeral=True)
                print("Resuming Audio")
                ctx.voice_state.resume()

                # Start session
                self.session_update.start()
            else:
                await ctx.send(content="Bot isn't connected to channel, aborting.", ephemeral=True)

    @slash_command(name="next-chapter", description="play next chapter, if available.")
    async def next_chapter(self, ctx):
        if ctx.voice_state:
            CurrentChapter = self.currentChapter
            ChapterArray = self.chapterArray
            bookFinished = self.bookFinished

            if not bookFinished:

                currentChapterID = int(CurrentChapter.get('id'))
                nextChapterID = currentChapterID + 1
                found_next_chapter = False
                print(nextChapterID)

                self.session_update.stop()
                c.bookshelf_close_session(self.sessionID)
                await ctx.voice_state.stop()

                for chapter in ChapterArray:
                    chapterID = int(chapter.get('id'))

                    if nextChapterID == chapterID:

                        chapterStart = float(chapter.get('start'))
                        newChapterTitle = chapter.get('title')
                        print(f"Next Chapter: {newChapterTitle}, Starting at: {chapterStart}")

                        audio_obj, currentTime, sessionID, bookTitle = c.bookshelf_audio_obj(self.bookItemID)
                        self.sessionID = sessionID
                        self.currentTime = currentTime
                        audio = AudioVolume(audio_obj)
                        audio.ffmpeg_before_args = f"-ss {chapterStart}"

                        await ctx.send(content=f"Skipping to Chapter: {newChapterTitle}", ephemeral=True)
                        self.session_update.start()

                        found_next_chapter = True
                        await ctx.voice_state.play_no_wait(audio)
                        break

                if not found_next_chapter:
                    await ctx.send(content=f"Book Finished or No New Chapter Found, aborting", ephemeral=True)
                    self.session_update.start()
                    audio = self.audioObj
                    audio.locked_stream = True
                    audio.ffmpeg_before_args = f"-ss {self.currentTime}"
                    await ctx.voice_state.play(self.audioObj)
        else:
            await ctx.send(content="Bot isn't connected to channel, aborting.", ephemeral=True)

    @slash_command(name="stop", description="Will disconnect from the voice channel and stop audio.")
    async def stop_audio(self, ctx: SlashContext):
        if ctx.voice_state:
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
        print(user_input)
        if user_input != "":
            try:
                titles_ = c.bookshelf_title_search(user_input)
                for info in titles_:
                    book_title = info["title"]
                    book_id = info["id"]
                    choices.append({"name": f"{book_title}", "value": f"{book_id}"})

                await ctx.send(choices=choices)

            except Exception as e:  # NOQA
                await ctx.send(choices=choices)

        else:
            await ctx.send(choices=choices)

