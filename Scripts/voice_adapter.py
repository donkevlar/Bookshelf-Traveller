# Scripts/voice_adapter.py
import discord
import logging
import threading

logger = logging.getLogger("bot")

class VoiceAdapter:
    """
    Voice runs ONLY on the discord.py client's event loop.
    Fire-and-forget API with a connection gate.
    """

    def __init__(self, discord_client: discord.Client):
        self.client = discord_client
        self.voice_clients: dict[int, discord.VoiceClient] = {}
        self.connected_events: dict[int, threading.Event] = {}

    def _call(self, fn, *args, **kwargs):
        loop = getattr(self.client, "loop", None)
        if loop is None:
            raise RuntimeError("discord.py loop not available yet")
        loop.call_soon_threadsafe(fn, *args, **kwargs)

    def _task(self, coro):
        loop = getattr(self.client, "loop", None)
        if loop is None:
            raise RuntimeError("discord.py loop not available yet")
        loop.call_soon_threadsafe(loop.create_task, coro)

    def connect(self, guild_id: int, channel_id: int):
        ev = self.connected_events.setdefault(guild_id, threading.Event())
        ev.clear()

        async def _do_connect():
            guild = self.client.get_guild(guild_id)
            if not guild:
                logger.error(f"[VOICE] Guild not found: {guild_id}")
                return

            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                logger.error(f"[VOICE] Channel is not a voice channel: {channel_id}")
                return

            vc = self.voice_clients.get(guild_id)
            if vc and vc.is_connected():
                if vc.channel.id == channel_id:
                    ev.set()
                    return
                try:
                    await vc.move_to(channel)
                    logger.info(f"[VOICE] Moved to {channel.name} ({guild.name})")
                    ev.set()
                    return
                except Exception as e:
                    logger.exception(f"[VOICE] Move failed: {e}")

            try:
                vc = await channel.connect()
                self.voice_clients[guild_id] = vc
                logger.info(f"[VOICE] Connected to {channel.name} ({guild.name})")
                ev.set()
            except Exception as e:
                logger.exception(f"[VOICE] Connect failed: {e}")

        self._task(_do_connect())

    def disconnect(self, guild_id: int):
        async def _do_disconnect():
            vc = self.voice_clients.pop(guild_id, None)
            ev = self.connected_events.get(guild_id)
            if ev:
                ev.clear()

            if not vc:
                return

            try:
                await vc.disconnect(force=True)
                logger.info(f"[VOICE] Disconnected from guild {guild_id}")
            except Exception as e:
                logger.exception(f"[VOICE] Disconnect failed: {e}")

        self._task(_do_disconnect())

    def wait_connected(self, guild_id: int, timeout: float = 10.0) -> bool:
        ev = self.connected_events.setdefault(guild_id, threading.Event())
        return ev.wait(timeout)

    def play(self, guild_id: int, source: discord.AudioSource):
        def _do():
            vc = self.voice_clients.get(guild_id)
            if not vc or not vc.is_connected():
                logger.error(f"[VOICE] Play requested but not connected (guild {guild_id})")
                return

            try:
                if vc.is_playing() or vc.is_paused():
                    vc.stop()
                vc.play(
                    source,
                    after=lambda err: logger.info(
                        f"[VOICE] Playback ended (guild {guild_id}) err={err}"
                    )
                )
            except Exception as e:
                logger.exception(f"[VOICE] Play failed: {e}")

        self._call(_do)

    def pause(self, guild_id: int):
        def _do():
            vc = self.voice_clients.get(guild_id)
            if vc and vc.is_playing():
                vc.pause()

        self._call(_do)

    def resume(self, guild_id: int):
        def _do():
            vc = self.voice_clients.get(guild_id)
            if vc and vc.is_paused():
                vc.resume()

        self._call(_do)

    def stop(self, guild_id: int):
        def _do():
            vc = self.voice_clients.get(guild_id)
            if vc:
                vc.stop()

        self._call(_do)

# ------------------------------------------------------------------
# Compatibility shim to emulate interactions ctx.voice_state
# ------------------------------------------------------------------

class VoiceStateShim:
    """
    Emulates interactions ctx.voice_state API while routing through VoiceAdapter.
    NOTE: connect/disconnect/play are intentionally NOT awaited across loops.
    """

    def __init__(self, adapter: VoiceAdapter, guild_id: int, channel):
        self._adapter = adapter
        self.guild_id = guild_id
        self.channel = channel  # keep ctx.voice_state.channel working

    async def play(self, source):
        # keep 'await' compatibility for existing code, but do not block
        self._adapter.play(self.guild_id, source)

    def pause(self):
        self._adapter.pause(self.guild_id)

    def resume(self):
        self._adapter.resume(self.guild_id)

    def stop(self):
        self._adapter.stop(self.guild_id)

    async def disconnect(self):
        # keep 'await' compatibility for existing code, but do not block
        self._adapter.disconnect(self.guild_id)
