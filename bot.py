import asyncio
import base64
import io
import logging
import os
import re

import aiohttp
import discord
import edge_tts
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_MODEL = os.getenv("SARVAM_MODEL", "bulbul:v3")
SARVAM_SPEAKER = os.getenv("SARVAM_SPEAKER", "shubh")
SARVAM_LANGUAGE = os.getenv("SARVAM_LANGUAGE", "en-IN")
SARVAM_PACE = float(os.getenv("SARVAM_PACE", "1.0"))
EDGE_VOICE = os.getenv("EDGE_VOICE", "en-IN-NeerjaNeural")
SAY_NAMES = os.getenv("SAY_NAMES", "true").lower() in ("1", "true", "yes")
MAX_CHARS = int(os.getenv("MAX_CHARS", "300"))
TTS_CHANNEL_IDS = {int(c) for c in os.getenv("TTS_CHANNEL_IDS", "").replace(" ", "").split(",") if c}

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"

log = logging.getLogger("voxcord")

URL_RE = re.compile(r"https?://\S+")
CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")


def clean_text(message: discord.Message) -> str:
    text = message.clean_content
    text = URL_RE.sub(" a link ", text)
    text = CUSTOM_EMOJI_RE.sub(r" \1 ", text)
    text = re.sub(r"[*_~`|>]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "..."
    return text


class Speaker:
    """Per-guild queue that synthesizes and plays messages one at a time."""

    def __init__(self, bot: "VoxBot", guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: asyncio.Queue[tuple[int, str, str]] = asyncio.Queue()
        self.last_author: int | None = None
        self.task = asyncio.create_task(self.run())

    def stop(self):
        self.task.cancel()

    def clear(self):
        while not self.queue.empty():
            self.queue.get_nowait()

    async def run(self):
        while True:
            author_id, name, text = await self.queue.get()
            try:
                await self.speak(author_id, name, text)
            except Exception:
                log.exception("Failed to speak message")

    async def speak(self, author_id: int, name: str, text: str):
        if SAY_NAMES and author_id != self.last_author:
            text = f"{name} says: {text}"
        self.last_author = author_id

        audio = await self.bot.synthesize(text)
        vc = self.guild.voice_client
        if audio is None or vc is None or not vc.is_connected():
            return

        done = asyncio.Event()
        loop = asyncio.get_running_loop()
        source = discord.FFmpegPCMAudio(io.BytesIO(audio), pipe=True)
        vc.play(source, after=lambda _: loop.call_soon_threadsafe(done.set))
        await done.wait()


class VoxBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.speakers: dict[int, Speaker] = {}
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        await self.tree.sync()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

    async def synthesize(self, text: str) -> bytes | None:
        if SARVAM_API_KEY:
            try:
                return await self.sarvam_tts(text)
            except Exception as e:
                log.warning("Sarvam TTS failed, falling back to edge-tts: %s", e)
        try:
            return await self.edge_tts(text)
        except Exception as e:
            log.error("edge-tts failed: %s", e)
            return None

    async def sarvam_tts(self, text: str) -> bytes:
        payload = {
            "text": text,
            "language_code": SARVAM_LANGUAGE,
            "model": SARVAM_MODEL,
            "speaker": SARVAM_SPEAKER,
            "pace": SARVAM_PACE,
        }
        headers = {"api-subscription-key": SARVAM_API_KEY}
        timeout = aiohttp.ClientTimeout(total=15)
        async with self.http_session.post(SARVAM_URL, json=payload, headers=headers, timeout=timeout) as r:
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:200]}")
            data = await r.json()
        return base64.b64decode("".join(data["audios"]))

    async def edge_tts(self, text: str) -> bytes:
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, EDGE_VOICE).stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        if not buf:
            raise RuntimeError("no audio returned")
        return bytes(buf)

    def speaker_for(self, guild: discord.Guild) -> Speaker:
        if guild.id not in self.speakers:
            self.speakers[guild.id] = Speaker(self, guild)
        return self.speakers[guild.id]

    async def disconnect_guild(self, guild: discord.Guild):
        speaker = self.speakers.pop(guild.id, None)
        if speaker:
            speaker.stop()
        if guild.voice_client:
            await guild.voice_client.disconnect(force=True)

    async def on_ready(self):
        log.info("Logged in as %s (TTS: %s)", self.user, "Sarvam" if SARVAM_API_KEY else "edge-tts")

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        vc = message.guild.voice_client
        if vc is None or not vc.is_connected():
            return
        if message.channel.id != vc.channel.id and message.channel.id not in TTS_CHANNEL_IDS:
            return
        voice = getattr(message.author, "voice", None)
        if voice is None or voice.channel != vc.channel:
            return
        text = clean_text(message)
        if not text:
            return
        self.speaker_for(message.guild).queue.put_nowait(
            (message.author.id, message.author.display_name, text)
        )

    async def on_voice_state_update(self, member, before, after):
        vc = member.guild.voice_client
        if vc is None:
            return
        if member.id == self.user.id and after.channel is None:
            speaker = self.speakers.pop(member.guild.id, None)
            if speaker:
                speaker.stop()
            return
        if not any(not m.bot for m in vc.channel.members):
            await self.disconnect_guild(member.guild)


bot = VoxBot()


@bot.tree.command(description="Join your voice channel and start reading messages aloud")
@app_commands.guild_only()
async def join(interaction: discord.Interaction):
    voice = interaction.user.voice
    if voice is None or voice.channel is None:
        await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    vc = interaction.guild.voice_client
    if vc is None:
        await voice.channel.connect(self_deaf=True)
    elif vc.channel != voice.channel:
        await vc.move_to(voice.channel)
    bot.speaker_for(interaction.guild)
    await interaction.followup.send(
        f"Joined **{voice.channel.name}**. Type in this voice channel's chat and I'll read it out.",
        ephemeral=True,
    )


@bot.tree.command(description="Leave the voice channel")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client is None:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
        return
    await bot.disconnect_guild(interaction.guild)
    await interaction.response.send_message("Left the voice channel.", ephemeral=True)


@bot.tree.command(description="Skip the current message and clear the queue")
@app_commands.guild_only()
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    speaker = bot.speakers.get(interaction.guild.id)
    if speaker:
        speaker.clear()
    if vc and vc.is_playing():
        vc.stop()
    await interaction.response.send_message("Skipped.", ephemeral=True)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN, root_logger=True)
