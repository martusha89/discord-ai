<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:8B5CF6,100:22D3EE&height=170&section=header&text=Discord%20AI&fontColor=ffffff&fontSize=46&fontAlignY=40&desc=A%20Discord%20bot%20with%20personality,%20tone,%20memory%20%26%20image%20gen&descSize=17&descAlignY=64" width="100%" />

[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](#)
[![license MIT](https://img.shields.io/badge/license-MIT-A855F7?style=for-the-badge)](LICENSE)
[![deploy Railway](https://img.shields.io/badge/deploy-Railway-22D3EE?style=for-the-badge&logo=railway&logoColor=white)](https://railway.com)

</div>

A Discord bot with personality. Not another generic ChatGPT wrapper — this one has a tone engine, emotional awareness, full-text message search, channel summaries, image generation, and GIF reactions.

## Features

- **Conversational AI** — responds to mentions or a trigger word, maintains per-user and per-channel context
- **Tone Detection** — detects emotional tone (spiral, sad, playful, angry, support) and adapts responses automatically
- **Message Search** — full-text search across your server using SQLite FTS5, with jump links to results
- **Channel Summaries** — generates summaries of channel conversations on demand
- **Image Generation** — creates images via OpenAI (on request or spontaneously when the vibe hits)
- **GIF Reactions** — Giphy integration for contextual GIF responses
- **Persistent Memory** — SQLite database logs messages for search and summaries

## Quick Start

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, give it a name
3. Go to **Bot** tab, click **Reset Token**, copy it — you'll need this
4. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent**
   - **Server Members Intent**
5. Go to **OAuth2 > URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Permissions: `Send Messages`, `Read Message History`, `Add Reactions`, `Attach Files`, `Use Slash Commands`, `Read Messages/View Channels`
6. Copy the generated URL and open it to invite the bot to your server

### 2. Get API Keys

- **OpenAI API key** — [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (required)
- **Giphy API key** — [developers.giphy.com](https://developers.giphy.com/) (optional, for GIF reactions)

### 3. Customize the Personality

Two files control your bot's personality — **no code knowledge required:**

1. **`system_prompt.txt`** — your bot's soul. The template has placeholders and examples. Define who your bot *is*.
2. **`responses.py`** — every canned response (shush replies, error messages, ping text, tone reactions). Open it, change the strings, done.

The tone engine (`tone_engine.py`) detects emotional states and adjusts how the bot responds. The default patterns work well out of the box, but you can tune the keywords and weights if you want.

### 4. Deploy on Railway

[Railway](https://railway.com) is the easiest way to run this. Free tier works fine for small servers.

1. Push this repo to GitHub (or fork it)
2. Go to [railway.com](https://railway.com), sign in with GitHub
3. **New Project > Deploy from GitHub repo** — select your repo
4. Add a **Volume**:
   - Click your service > **+ New** > **Volume**
   - Mount path: `/data`
   - This is where the message database lives — without it, search/summary data is lost on redeploy
5. Set **environment variables** (Settings > Variables):
   ```
   DISCORD_BOT_TOKEN=your_token_here
   OPENAI_API_KEY=your_key_here
   BOT_NAME=YourBotName
   BOT_TRIGGER=yourbotname
   COMMUNITY_NAME=Your Server Name
   COMMUNITY_TOPIC=what your server is about
   ```
   See `.env.example` for all available options.
6. Railway auto-detects Python and deploys. Check the logs — you should see:
   ```
   [Bot] YourBotName is online as YourBot#1234
   [DB] Using persistent storage: /data/bot.db
   [Health] Listening on port 8080
   ```

That's it. The bot is live.

### Railway Tips

- **Custom start command:** If Railway doesn't auto-detect, set the start command to `python main.py`
- **Health check:** The bot runs a health endpoint on the port Railway assigns (`PORT` env var). Railway uses this to know the bot is alive.
- **Logs:** Check **Deployments > View Logs** if something isn't working
- **Volume:** Make sure the volume is mounted at `/data` — the database goes there. Without it, the bot still works but search/summary data resets on every deploy.
- **Cost:** A Discord bot uses minimal resources. Railway's free tier or Hobby plan ($5/mo) is plenty.

## Running Locally

```bash
# Clone the repo
git clone <your-repo-url>
cd <repo-name>

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your tokens and settings

# Run
python main.py
```

The bot will use `bot.db` in the project directory when no `/data` volume is available.

## Commands

| Command | Description |
|---------|-------------|
| `/find <query>` | Search messages across channels |
| `/summarize [channel] [hours]` | Get a summary of a channel |
| `/imagine <prompt>` | Generate an image |
| `/ping` | Check bot latency |
| `/stats` | Message database statistics |
| `!find <query>` | Prefix version of search |
| `!summarize [channel]` | Prefix version of summary |
| `!shush` | Tell the bot to stop talking in the current channel |

The bot also responds when mentioned or when someone says its trigger word in chat.

## How It Works

### Tone Engine

The bot detects emotional tone using weighted keyword patterns:

- **spiral** — burnout, overwhelmed, can't cope (bot grounds and calms)
- **sad** — depressed, lonely, crying (bot is warm and present)
- **play** — lol, flirt, tease (bot matches the energy)
- **fire** — angry, rage, bullshit (bot stays sharp and unshaken)
- **support** — anxious, scared, confused (bot offers clarity)
- **neutral** — default conversational mode

You can customize patterns and weights in `tone_engine.py`.

### Message Store

All messages are logged to SQLite with FTS5 (full-text search). This powers both `/find` and `/summary`. The database auto-creates on first run.

If the database isn't available, the bot falls back to scanning Discord history directly — slower but functional.

### Actions System

The AI can append special actions to its replies that the bot processes:

- `@REACT='emoji'` — react to the user's message
- `@FIND='query'` — trigger a search
- `@SUMMARY='channel'` — trigger a summary
- `@IMAGE='description'` — generate an image
- `@GIF='search terms'` — search and post a GIF

These are stripped from the visible reply and executed separately.

## File Structure

```
main.py              # Core bot logic — events, commands, actions
config.py            # Environment variable loading and defaults
responses.py         # All bot responses — edit to customize personality
system_prompt.txt    # Bot personality prompt — edit to define who your bot is
tone_engine.py       # Emotional tone detection (weighted patterns)
message_store.py     # SQLite + FTS5 message database
health.py            # Health check endpoint for Railway/Docker
requirements.txt     # Python dependencies
.env.example         # Template for environment variables
```

## License

MIT
