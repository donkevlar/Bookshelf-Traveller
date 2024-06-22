from interactions import Extension, slash_command, SlashContext, slash_option, OptionType, AutocompleteContext, Task, \
    IntervalTrigger
import interactions.api.events
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings


# Update Frequency for session sync
updateFrequency = settings.UPDATES


class AudioPlayBack(Extension):
    def __init__(self, bot):
        self.sessionID = ''
        self.bookID = ''

    @Task.create(IntervalTrigger(seconds=updateFrequency))
    async def session_update(self, book_title: str, session_id: str, current_time=updateFrequency):
        print("Initializing Session Sync")
        c.bookshelf_session_update(itemID=book_title, sessionID=session_id, currentTime=current_time)

    @slash_command(name="play", description="Test Play Functionality")
    @slash_option(name="book_title", description="Enter a book title", required=True, opt_type=OptionType.STRING,
                  autocomplete=True)
    async def play_audio(self, ctx, book_title: str):

        # Get Bookshelf Playback URI, Starts new session
        audio_obj, currentTime, sessionID = c.bookshelf_audio_obj(book_title)

        # Audio Object Arguments
        audio = AudioVolume(audio_obj)
        audio.buffer_seconds = 15
        audio.locked_stream = True
        audio.ffmpeg_before_args = f"-ss {currentTime}"

        # Class VARS
        self.sessionID = sessionID
        self.bookID = book_title

        # check if bot currently connected to voice
        if not ctx.voice_state:

            # if we haven't already joined a voice channel
            try:
                # Connect to voice channel
                await ctx.author.voice.channel.connect()

                # Start Session Updates
                self.session_update.start(self.bookID, self.sessionID)

                await ctx.send(f"Playing Audio", ephemeral=True)

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

        # Play Audio, skip connection
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

    @slash_command(name="pause", description="pause audio")
    async def pause_audio(self, ctx):
        if ctx.voice_state:
            await ctx.send("Pausing Audio", ephemeral=True)
            print("Pausing Audio")
            ctx.voice_state.pause()
        # Stop Any Tasks Running
        if self.session_update.running:
            self.session_update.stop()

    @slash_command(name="resume", description="resume audio")
    async def resume_audio(self, ctx):
        if ctx.voice_state:
            if self.sessionID != "":
                await ctx.send("Resuming Audio", ephemeral=True)
                print("Resuming Audio")
                ctx.voice_state.resume()

                # Start session
                self.session_update.start(self.bookID, self.sessionID)

    @play_audio.autocomplete("book_title")
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

    @slash_command(name="disconnect", description="Will disconnect from the voice channel")
    async def disconnect_voice(self, ctx: SlashContext):
        if ctx.voice_state:
            await ctx.send(content="Disconnected from Audio Channel", ephemeral=True)
            await ctx.author.voice.channel.disconnect()

            if self.session_update.running:
                self.session_update.stop()
                c.bookshelf_close_session(self.sessionID)
