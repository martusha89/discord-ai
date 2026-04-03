import os
from dotenv import load_dotenv

load_dotenv()

# Required
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Bot identity
BOT_NAME = os.getenv("BOT_NAME", "Bot")
COMMUNITY_NAME = os.getenv("COMMUNITY_NAME", "our server")
COMMUNITY_TOPIC = os.getenv("COMMUNITY_TOPIC", "hanging out and having fun")
BOT_TRIGGER = os.getenv("BOT_TRIGGER", "").lower()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Conversation
CONVERSATION_TIMEOUT = int(os.getenv("CONVERSATION_TIMEOUT", "180"))  # seconds
CHANNEL_HISTORY_LIMIT = int(os.getenv("CHANNEL_HISTORY_LIMIT", "10"))
USER_MEMORY_LIMIT = int(os.getenv("USER_MEMORY_LIMIT", "8"))

# Search
SEARCH_MESSAGES_PER_CHANNEL = int(os.getenv("SEARCH_MESSAGES_PER_CHANNEL", "500"))
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

# Summary
SUMMARY_MESSAGE_LIMIT = int(os.getenv("SUMMARY_MESSAGE_LIMIT", "200"))
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "24000"))

# Search channels — comma-separated IDs in env, or empty for "all accessible"
_search_ids = os.getenv("SEARCH_CHANNEL_IDS", "")
SEARCH_CHANNEL_IDS = [int(x.strip()) for x in _search_ids.split(",") if x.strip()] if _search_ids else []

# Health check
HEALTH_PORT = int(os.getenv("PORT", os.getenv("HEALTH_PORT", "8080")))

# Image generation
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
IMAGE_SPONTANEOUS_CHANCE = float(os.getenv("IMAGE_SPONTANEOUS_CHANCE", "0.02"))  # 2% chance per response

# GIF (Giphy API)
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "")

# Database
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")
DB_FALLBACK_PATH = os.getenv("DB_FALLBACK_PATH", "bot.db")
