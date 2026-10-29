# voxcord

A small Discord bot that reads text messages aloud in a voice channel, so people who can't (or don't want to) talk can still be heard in the call.

## Features

- Reads messages typed in the voice channel's built-in text chat, plus any extra channels you configure
- Only reads messages from people who are actually in the call
- Announces the sender ("Rahul says: ...") when the speaker changes
- Uses [Sarvam AI](https://www.sarvam.ai/) text-to-speech (good for Indian English and Hindi/other Indian languages)
- Falls back to free [edge-tts](https://github.com/rany2/edge-tts) automatically if Sarvam errors, runs out of credits, or no key is set
- Cleans up messages: links become "a link", custom emoji are read by name, markdown is stripped, long messages are truncated
- Queues messages so they're read one at a time, in order
- Leaves automatically when everyone else leaves the call

## Commands

| Command  | What it does                                   |
|----------|------------------------------------------------|
| `/join`  | Joins your current voice channel               |
| `/leave` | Leaves the voice channel                       |
| `/skip`  | Stops the current message and clears the queue |

## Setup

### 1. Create the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Open the **Bot** tab, click **Reset Token**, and copy the token.
3. On the same tab, turn on **Message Content Intent** (the bot can't read messages without it).
4. Open **OAuth2 → URL Generator**, tick the `bot` and `applications.commands` scopes, then tick the bot permissions **View Channels**, **Read Message History**, **Connect**, and **Speak**.
5. Open the generated URL and add the bot to your server.

### 2. Install

Requires Python 3.10+ and [FFmpeg](https://ffmpeg.org/download.html) on your `PATH`.

```bash
git clone https://github.com/NikhilBhatt-15/voxcord.git
cd voxcord
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

Copy `.env.example` to `.env` and fill in at least `DISCORD_TOKEN`. Add `SARVAM_API_KEY` to use Sarvam; without it the bot uses edge-tts.

| Variable          | Default              | Notes                                                       |
|-------------------|----------------------|-------------------------------------------------------------|
| `DISCORD_TOKEN`   | (required)           | Bot token from the Developer Portal                         |
| `SARVAM_API_KEY`  | empty                | Sarvam API subscription key                                 |
| `SARVAM_MODEL`    | `bulbul:v3`          | Sarvam TTS model                                            |
| `SARVAM_SPEAKER`  | `shubh`              | Voice name; must match the model (e.g. `ritu`, `priya`)     |
| `SARVAM_LANGUAGE` | `en-IN`              | e.g. `hi-IN`, `ta-IN`                                        |
| `SARVAM_PACE`     | `1.0`                | Speed, `0.5` to `2.0`                                       |
| `EDGE_VOICE`      | `en-IN-NeerjaNeural` | Fallback voice (`edge-tts --list-voices` to see all)        |
| `SAY_NAMES`       | `true`               | Announce the sender before their message                    |
| `MAX_CHARS`       | `300`                | Longer messages are truncated                               |
| `TTS_CHANNEL_IDS` | empty                | Extra text channel IDs to read from, comma-separated        |

### 4. Run

```bash
python bot.py
```

Join a voice channel, run `/join`, and type in the voice channel's chat. Slash commands can take a minute to show up the first time.

## How it works

The bot runs as its own Discord account. Running `python bot.py` on your PC connects it to Discord over the internet; no ports or hosting are needed. The bot is only online while the script is running.

When a message arrives, the bot checks that it was posted in a watched channel by someone in the same voice channel, cleans up the text, and puts it on a per-server queue. A worker sends each queued message to Sarvam's `/text-to-speech` endpoint (or edge-tts), gets audio back, and streams it into the voice channel through FFmpeg. Discord delivers that audio to everyone in the call. It does not go through anyone's microphone.
