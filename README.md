# voxcord

A small Discord bot that reads text messages aloud in a voice channel, so people who can't (or don't want to) talk can still be heard in the call. Built for Hindi/Hinglish chats.

## Features

- Reads messages from one text channel (`#general` by default), only from people who are in the bot's voice call
- Every user gets their own voice, and keeps it across restarts
- Voices can be pinned per user with `/voice` or by editing `voices.json`
- Uses [Sarvam AI](https://www.sarvam.ai/) `bulbul:v3` text-to-speech in Hindi (`hi-IN`) by default
- Falls back to free [edge-tts](https://github.com/rany2/edge-tts) Hindi voices if Sarvam errors, runs out of credits, or no key is set
- Cleans up messages: links become "link", custom emoji are read by name, markdown is stripped, long messages are truncated
- Queues messages so they're read one at a time, in order
- Leaves automatically when everyone else leaves the call

## Commands

| Command                   | What it does                                                    |
|---------------------------|-----------------------------------------------------------------|
| `/join`                   | Joins your current voice channel                                |
| `/leave`                  | Leaves the voice channel                                        |
| `/skip`                   | Stops the current message and clears the queue                  |
| `/voice`                  | Shows your current voice                                        |
| `/voice voice:<name>`     | Changes your voice (autocompletes the list)                     |
| `/voice voice:<name> user:@someone` | Changes someone else's voice (needs Manage Server)    |

## Voices

New users are assigned the next unused voice from a list of the clearest Sarvam voices, alternating male and female, so no two people sound the same. Assignments are saved in `voices.json`, keyed by Discord user ID:

```json
{
  "123456789012345678": "mani",
  "234567890123456789": "priya"
}
```

To pin voices by hand, stop the bot, edit this file, and start it again. To get a user ID, enable **Developer Mode** in Discord settings, then right-click the user and choose **Copy User ID**.

Available `bulbul:v3` voices:

- **Male:** shubh, aditya, rahul, rohan, amit, dev, ratan, varun, manan, sumit, kabir, aayan, ashutosh, advait, anand, tarun, sunny, mani, gokul, vijay, mohit, rehan, soham
- **Female:** ritu, priya, neha, pooja, simran, kavya, ishita, shreya, roopa, tanya, shruti, suhani, kavitha, rupali

You can preview them on Sarvam's [voices page](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices).

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

| Variable            | Default              | Notes                                                  |
|---------------------|----------------------|--------------------------------------------------------|
| `DISCORD_TOKEN`     | (required)           | Bot token from the Developer Portal                    |
| `SARVAM_API_KEY`    | empty                | Sarvam API subscription key                            |
| `SARVAM_MODEL`      | `bulbul:v3`          | Sarvam TTS model                                       |
| `SARVAM_LANGUAGE`   | `hi-IN`              | e.g. `en-IN`, `ta-IN`                                  |
| `SARVAM_PACE`       | `1.0`                | Speed, `0.5` to `2.0`                                  |
| `TTS_CHANNEL`       | `general`            | Text channel to read, by name or ID                    |
| `EDGE_MALE_VOICE`   | `hi-IN-MadhurNeural` | Fallback voice for users with a male Sarvam voice      |
| `EDGE_FEMALE_VOICE` | `hi-IN-SwaraNeural`  | Fallback voice for users with a female Sarvam voice    |
| `SAY_NAMES`         | `false`              | Say the sender's name before their message             |
| `MAX_CHARS`         | `300`                | Longer messages are truncated                          |

### 4. Run

On Windows, double-click **`voxcord.bat`** to turn the bot on, and double-click it again to turn it off. A small popup confirms each time. It runs hidden (no console window) at below-normal priority and uses about 50 MB of RAM and almost no CPU while idle.

```
voxcord.bat            # toggle on/off
voxcord.bat start      # start only
voxcord.bat stop       # stop only
voxcord.bat status     # show whether it's running and its memory use
voxcord.bat log        # print the last lines of the log (in a terminal)
```

Logs go to `voxcord.log.err`. Run `voxcord.bat shortcut` once to create a **voxcord** shortcut on your Desktop and in the Start menu. To pin it, search "voxcord" in Start, then right-click → **Pin to taskbar** (or **Pin to Start**).

To run it in a visible terminal instead (any OS):

```bash
python bot.py
```

Join a voice channel, run `/join`, and type in `#general`. Slash commands can take a minute to show up the first time.

## How it works

The bot runs as its own Discord account. Running `python bot.py` on your PC connects it to Discord over the internet; no ports or hosting are needed. The bot is only online while the script is running.

When a message arrives in the configured channel, the bot checks that the author is in the same voice channel as the bot, cleans up the text, and puts it on a per-server queue. A worker looks up the author's voice, sends the text to Sarvam's `/text-to-speech` endpoint (or edge-tts), gets audio back, and streams it into the voice channel through FFmpeg. Discord delivers that audio to everyone in the call. It does not go through anyone's microphone.
