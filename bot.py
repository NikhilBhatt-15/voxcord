import asyncio
import base64
import io
import json
import logging
import os
import re
from pathlib import Path

import aiohttp
import discord
import edge_tts
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_MODEL = os.getenv("SARVAM_MODEL", "bulbul:v3")
SARVAM_LANGUAGE = os.getenv("SARVAM_LANGUAGE", "hi-IN")
SARVAM_PACE = float(os.getenv("SARVAM_PACE", "1.0"))
EDGE_MALE_VOICE = os.getenv("EDGE_MALE_VOICE", "hi-IN-MadhurNeural")
EDGE_FEMALE_VOICE = os.getenv("EDGE_FEMALE_VOICE", "hi-IN-SwaraNeural")
TTS_CHANNEL = os.getenv("TTS_CHANNEL", "general").lstrip("#")
SAY_NAMES = os.getenv("SAY_NAMES", "false").lower() in ("1", "true", "yes")
MAX_CHARS = int(os.getenv("MAX_CHARS", "300"))
VOICES_FILE = Path(os.getenv("VOICES_FILE", Path(__file__).with_name("voices.json")))

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"

MALE_VOICES = [
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun", "manan", "sumit", "kabir", "aayan",
    "ashutosh", "advait", "anand", "tarun", "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham",
]
FEMALE_VOICES = [
    "ritu", "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya", "roopa", "tanya", "shruti",
    "suhani", "kavitha", "rupali",
]
ALL_VOICES = MALE_VOICES + FEMALE_VOICES
# Order new users are assigned voices in: clearest voices first, alternating male/female
AUTO_VOICES = [
    "mani", "priya", "shubh", "ishita", "aditya", "roopa", "rahul", "kavya", "rohan", "neha",
    "amit", "simran", "kabir", "shreya", "dev", "tanya",
]

log = logging.getLogger("voxcord")

URL_RE = re.compile(r"https?://\S+")
CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")


def clean_text(message: discord.Message) -> str:
    text = message.clean_content
    text = URL_RE.sub(" link ", text)
    text = CUSTOM_EMOJI_RE.sub(r" \1 ", text)
    text = re.sub(r"[*_~`|>]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "..."
    return text


class VoiceStore:
    """Maps Discord user IDs to Sarvam voices, persisted in voices.json.

    Users without a voice get the next unused one from AUTO_VOICES on their first message,
    so everyone sounds different and keeps the same voice across restarts.
    Edit voices.json by hand (while the bot is stopped) or use /voice to pin voices.
    """

    def __init__(self, path: Path):
        self.path = path
        self.voices: dict[str, str] = {}
        if path.exists():
            self.voices = {str(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}

    def save(self):
        self.path.write_text(json.dumps(self.voices, indent=2), encoding="utf-8")

    def get(self, user_id: int) -> str:
        key = str(user_id)
        if key not in self.voices:
            used = set(self.voices.values())
            free = [v for v in AUTO_VOICES if v not in used] or [v for v in ALL_VOICES if v not in used]
            self.voices[key] = free[0] if free else AUTO_VOICES[len(self.voices) % len(AUTO_VOICES)]
            self.save()
        return self.voices[key]

    def set(self, user_id: int, voice: str):
        self.voices[str(user_id)] = voice
        self.save()


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
            text = f"{name}: {text}"
        self.last_author = author_id

        audio = await self.bot.synthesize(text, self.bot.voices.get(author_id))
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
        self.voices = VoiceStore(VOICES_FILE)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        await self.tree.sync()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

    async def synthesize(self, text: str, voice: str) -> bytes | None:
        if SARVAM_API_KEY:
            try:
                return await self.sarvam_tts(text, voice)
            except Exception as e:
                log.warning("Sarvam TTS failed, falling back to edge-tts: %s", e)
        try:
            return await self.edge_tts(text, EDGE_FEMALE_VOICE if voice in FEMALE_VOICES else EDGE_MALE_VOICE)
        except Exception as e:
            log.error("edge-tts failed: %s", e)
            return None

    async def sarvam_tts(self, text: str, voice: str) -> bytes:
        payload = {
            "text": text,
            "language_code": SARVAM_LANGUAGE,
            "model": SARVAM_MODEL,
            "speaker": voice,
            "pace": SARVAM_PACE,
        }
        headers = {"api-subscription-key": SARVAM_API_KEY}
        timeout = aiohttp.ClientTimeout(total=15)
        async with self.http_session.post(SARVAM_URL, json=payload, headers=headers, timeout=timeout) as r:
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:200]}")
            data = await r.json()
        return base64.b64decode("".join(data["audios"]))

    async def edge_tts(self, text: str, voice: str) -> bytes:
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
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
        log.info(
            "Logged in as %s, reading #%s (TTS: %s)", self.user, TTS_CHANNEL, "Sarvam" if SARVAM_API_KEY else "edge-tts"
        )

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if TTS_CHANNEL not in (getattr(message.channel, "name", None), str(message.channel.id)):
            return
        vc = message.guild.voice_client
        if vc is None or not vc.is_connected():
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


@bot.tree.command(description="Join your voice channel and start reading #general aloud")
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
        f"Joined **{voice.channel.name}**. Messages in #{TTS_CHANNEL} from people in this call will be read aloud.",
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


@bot.tree.command(description="Show or change a TTS voice")
@app_commands.guild_only()
@app_commands.describe(
    voice="Voice to use (leave empty to see the current one)",
    user="Whose voice to change (needs Manage Server for anyone but yourself)",
)
async def voice(interaction: discord.Interaction, voice: str | None = None, user: discord.Member | None = None):
    target = user or interaction.user
    if voice is None:
        await interaction.response.send_message(
            f"{target.display_name}'s voice is **{bot.voices.get(target.id)}**.", ephemeral=True
        )
        return
    voice = voice.lower().strip()
    if voice not in ALL_VOICES:
        await interaction.response.send_message(
            f"Unknown voice. Pick one of: {', '.join(ALL_VOICES)}", ephemeral=True
        )
        return
    if target.id != interaction.user.id and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server to change other people's voices.", ephemeral=True)
        return
    bot.voices.set(target.id, voice)
    await interaction.response.send_message(f"{target.display_name}'s voice is now **{voice}**.", ephemeral=True)


@voice.autocomplete("voice")
async def voice_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower()
    matches = [v for v in ALL_VOICES if current in v][:25]
    return [
        app_commands.Choice(name=f"{v} ({'female' if v in FEMALE_VOICES else 'male'})", value=v) for v in matches
    ]


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN, root_logger=True)
