import os
import discord
from discord.ext import commands
from discord import app_commands
from openai import OpenAI, APITimeoutError, APIError
import random
import time
from tone_engine import detect_tone
import asyncio
from datetime import datetime, timezone
import re
import io
import base64
import aiohttp
from typing import Optional

import config
import responses
import message_store
from health import start_health_server

# OpenAI client (new SDK)
client = OpenAI(api_key=config.OPENAI_API_KEY)

# Load system prompt
def load_system_prompt():
    try:
        with open("system_prompt.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        raise SystemExit("system_prompt.txt not found.")

system_prompt = load_system_prompt()

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory state
user_memory = {}  # (channel_id, user_id): [messages]
active_conversation = {}  # channel_id: last_active_time


# === HELPERS ===

def call_llm(messages, max_tokens=500, temperature=0.8):
    """Single place for all OpenAI calls."""
    return client.chat.completions.create(
        model=config.MODEL,
        messages=messages,
        max_completion_tokens=max_tokens,
        temperature=temperature,
        timeout=30,
    )


def build_prompt(base_prompt, tone, user_id_mention, user_memory_str):
    """Construct the full system prompt with tone and context."""
    # Replace placeholders in prompt
    base_prompt = base_prompt.replace("{{BOT_NAME}}", config.BOT_NAME)
    base_prompt = base_prompt.replace("{{YOUR_COMMUNITY}}", config.COMMUNITY_NAME)
    base_prompt = base_prompt.replace("{{YOUR_TOPIC}}", config.COMMUNITY_TOPIC)
    prompt = f"{base_prompt}\n\n--- USER ID FOR MENTION ---\n{user_id_mention}\n\n--- USER MEMORY ---\n{user_memory_str}"

    if tone in responses.TONE:
        prompt += responses.TONE[tone]

    return prompt


def parse_actions(reply):
    """Extract @REACT, @FIND, @SUMMARY, @IMAGE from reply. Returns cleaned reply and actions dict."""
    actions = {}

    react_match = re.search(r"@REACT=['\"](.+?)['\"]", reply)
    if react_match:
        actions["react"] = react_match.group(1).strip()
        reply = reply.replace(react_match.group(0), "").strip()

    find_match = re.search(r"@FIND=['\"](.+?)['\"]", reply)
    if find_match:
        actions["find"] = find_match.group(1).strip()
        reply = reply.replace(find_match.group(0), "").strip()

    summary_match = re.search(r"@SUMMARY=['\"](.+?)['\"]", reply)
    if summary_match:
        actions["summary"] = summary_match.group(1).strip()
        reply = reply.replace(summary_match.group(0), "").strip()

    image_match = re.search(r"@IMAGE=['\"](.+?)['\"]", reply, re.DOTALL)
    if image_match:
        actions["image"] = image_match.group(1).strip()
        reply = reply.replace(image_match.group(0), "").strip()

    gif_match = re.search(r"@GIF=['\"](.+?)['\"]", reply)
    if gif_match:
        actions["gif"] = gif_match.group(1).strip()
        reply = reply.replace(gif_match.group(0), "").strip()

    return reply, actions


def clean_reply(reply, bot_name, author_name):
    """Strip bot/user name prefixes the LLM sometimes adds."""
    for prefix in [f"{bot_name}: ", f"{author_name}: "]:
        if reply.startswith(prefix):
            reply = reply[len(prefix):]
    return reply.strip()


# === IMAGE GENERATION ===

async def generate_image(prompt, channel):
    """Generate an image via OpenAI and send it to a Discord channel."""
    try:
        print(f"[Image] Generating: {prompt[:80]}...")
        result = client.images.generate(
            model=config.IMAGE_MODEL,
            prompt=prompt,
            n=1,
            size="1024x1024",
        )

        # gpt-image-1 returns base64
        if result.data[0].b64_json:
            image_bytes = base64.b64decode(result.data[0].b64_json)
            file = discord.File(io.BytesIO(image_bytes), filename="bot_creation.png")
            await channel.send(file=file)
        elif result.data[0].url:
            embed = discord.Embed(color=0xFF69B4)
            embed.set_image(url=result.data[0].url)
            await channel.send(embed=embed)

        print(f"[Image] Sent successfully.")
        return True

    except Exception as e:
        print(f"[Image] Generation failed: {e}")
        await channel.send(responses.IMAGE_FAIL)
        return False


def should_spontaneously_create(tone):
    """Roll the dice on spontaneous image generation. Higher chance for playful/emotional tones."""
    base_chance = config.IMAGE_SPONTANEOUS_CHANCE
    # Boost chance for emotional moments
    if tone in ("play", "sad", "spiral"):
        base_chance *= 1.5
    return random.random() < base_chance


# === GIF (GIPHY) ===

async def search_gif(query, channel):
    """Search Giphy for a GIF and send it to a Discord channel."""
    if not config.GIPHY_API_KEY:
        print("[GIF] No GIPHY_API_KEY set — skipping.")
        return False
    try:
        url = "https://api.giphy.com/v1/gifs/search"
        params = {
            "api_key": config.GIPHY_API_KEY,
            "q": query,
            "limit": 8,
            "rating": "r",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    print(f"[GIF] Giphy returned {resp.status}")
                    return False
                data = await resp.json()

        results = data.get("data", [])
        if not results:
            await channel.send(responses.GIF_NO_RESULTS)
            return False

        pick = random.choice(results)
        gif_url = pick["images"]["original"]["url"]
        await channel.send(gif_url)
        print(f"[GIF] Sent for query: {query}")
        return True

    except Exception as e:
        print(f"[GIF] Failed: {e}")
        return False


# === SEARCH ===

async def do_search(guild, query, requester, channel_id=None, limit=None):
    """Search messages. Uses DB first, falls back to Discord history."""
    limit = limit or config.SEARCH_MAX_RESULTS

    # Try database first — always scoped to this server
    guild_id = str(guild.id) if guild else None
    db_results = await message_store.search(query, guild_id=guild_id, channel_id=channel_id, limit=limit)
    if db_results:
        return db_results

    # Fallback: scan Discord history (original behavior, improved)
    results = []

    if config.SEARCH_CHANNEL_IDS:
        channels = [guild.get_channel(cid) for cid in config.SEARCH_CHANNEL_IDS]
        channels = [ch for ch in channels if ch is not None]
    else:
        channels = guild.text_channels

    query_lower = query.lower()
    query_words = query_lower.split()

    async def scan_channel(channel):
        found = []
        if not channel.permissions_for(requester).read_messages:
            return []
        if not channel.permissions_for(guild.me).read_message_history:
            return []
        try:
            async for msg in channel.history(limit=config.SEARCH_MESSAGES_PER_CHANNEL):
                if msg.author.bot or msg.content.startswith("!") or msg.content.startswith("/"):
                    continue
                content_lower = msg.content.lower()
                # Word-level matching — all query words must appear
                if all(w in content_lower for w in query_words):
                    found.append({
                        "channel_name": channel.name,
                        "author_name": msg.author.display_name,
                        "created_at": msg.created_at.isoformat(),
                        "content": msg.content,
                        "discord_id": str(msg.id),
                        "channel_id": str(channel.id),
                    })
                    # Also log to DB while we're at it
                    await message_store.log_message(msg)
        except discord.Forbidden:
            pass
        return found

    tasks = [scan_channel(ch) for ch in channels]
    lists = await asyncio.gather(*tasks)
    results = [msg for sublist in lists for msg in sublist]

    # Deduplicate and sort
    seen = set()
    deduped = []
    for r in results:
        if r["discord_id"] not in seen:
            seen.add(r["discord_id"])
            deduped.append(r)
    deduped.sort(key=lambda x: x["created_at"], reverse=True)

    return deduped[:limit]


def format_search_results(results, query, mention):
    """Format search results for Discord."""
    if not results:
        return responses.SEARCH_NO_RESULTS.format(mention=mention, query=query)

    response = responses.SEARCH_HEADER.format(mention=mention)
    for r in results:
        trimmed = r["content"][:150] + ("..." if len(r["content"]) > 150 else "")
        ch_name = r["channel_name"]
        author = r["author_name"]
        # Build jump URL if we have channel and message IDs
        url_part = ""
        if r.get("discord_id") and r.get("channel_id"):
            url_part = f" [Jump](https://discord.com/channels/@me/{r['channel_id']}/{r['discord_id']})"
        response += f"  **#{ch_name}** -- **{author}** said: *\"{trimmed}\"*{url_part}\n"

    return response


# === SUMMARY ===

async def do_summary(channel, guild, hours=None):
    """Generate a summary. Uses DB if available, falls back to Discord history."""
    # Try database first
    db_messages = await message_store.get_channel_messages(
        str(channel.id),
        limit=config.SUMMARY_MESSAGE_LIMIT,
        hours=hours,
    )

    if db_messages:
        parts = []
        for m in db_messages:
            if m["is_bot"] and m["content"].startswith("Here's what I dug up:"):
                continue
            parts.append(f"{m['author_name']}: {m['content']}")
    else:
        # Fallback: fetch from Discord
        messages = [msg async for msg in channel.history(limit=config.SUMMARY_MESSAGE_LIMIT)]
        messages.reverse()

        parts = []
        for msg in messages:
            if not msg.content and msg.author.bot:
                continue
            if msg.content.startswith(("!summarize", "!find", "/summarize", "/find")):
                continue
            if msg.author.id == bot.user.id and msg.embeds:
                continue
            parts.append(f"{msg.author.display_name}: {msg.content}")
            # Log while we're here
            await message_store.log_message(msg)

    # Crop to char limit
    while len("\n".join(parts)) > config.SUMMARY_MAX_CHARS and len(parts) > 1:
        parts.pop(0)

    content = "\n".join(parts)
    if not content:
        return None

    summary_prompt = (
        f"You are {config.BOT_NAME}. "
        "Summarize this Discord conversation in a clear but informal way. "
        "Skip filler. Be concise. Add personality where it fits. "
        "Highlight the most interesting points and any drama. "
        "Keep it under 400 words."
    )

    response = call_llm(
        messages=[
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": content},
        ],
        max_tokens=500,
        temperature=0.8,
    )

    return response.choices[0].message.content or ""


# === RESOLVE CHANNEL ===

def resolve_channel(guild, input_name):
    """Find a channel by name, ID, or mention."""
    if not input_name:
        return None

    # Handle <#id> format
    if input_name.startswith("<#") and input_name.endswith(">"):
        try:
            return guild.get_channel(int(input_name.strip("<#>")))
        except ValueError:
            return None

    # Strip leading #
    cleaned = input_name.lstrip("#")

    # Try as raw ID
    if cleaned.isdigit():
        ch = guild.get_channel(int(cleaned))
        if ch:
            return ch

    # Exact name match
    for channel in guild.text_channels:
        if channel.name == input_name:
            return channel

    # Suffix match (only if input is specific enough)
    matches = [ch for ch in guild.text_channels if ch.name.endswith(input_name) and len(input_name) > 5]
    if len(matches) == 1:
        return matches[0]

    return None


# === EVENTS ===

@bot.event
async def on_ready():
    global bot_trigger
    if not config.BOT_TRIGGER:
        bot_trigger = bot.user.name.lower()
        print(f"[Bot] Using username '{bot_trigger}' as trigger")
    else:
        bot_trigger = config.BOT_TRIGGER

    # Initialize message store
    await message_store.init()

    # Start health server
    await start_health_server()

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"[Bot] Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"[Bot] Slash command sync failed: {e}")

    print(f"[Bot] {config.BOT_NAME} is online as {bot.user}")


@bot.event
async def on_message(message):
    # Ignore bots (including self)
    if message.author.bot:
        return

    # Log every message to the store (silently)
    await message_store.log_message(message)

    now = time.time()
    channel_id = message.channel.id
    user_key = (channel_id, message.author.id)

    # Update user memory
    if user_key not in user_memory:
        user_memory[user_key] = []
    user_memory[user_key].append({
        "role": "user",
        "content": f"{message.author.display_name}: {message.content}",
    })
    user_memory[user_key] = user_memory[user_key][-config.USER_MEMORY_LIMIT:]

    # Check triggers
    is_mentioned = bot.user.mentioned_in(message) and not message.mention_everyone
    is_summon = bot_trigger in message.content.lower() or is_mentioned
    is_active = channel_id in active_conversation and now - active_conversation[channel_id] < config.CONVERSATION_TIMEOUT

    # Shush
    if "shush" in message.content.lower():
        if channel_id in active_conversation:
            del active_conversation[channel_id]
            reply = random.choice(responses.SHUSH).format(mention=message.author.mention)
            await message.channel.send(reply)
        return

    if is_summon or is_active:
        async with message.channel.typing():
            # Fetch live channel context
            live_history = [msg async for msg in message.channel.history(limit=config.CHANNEL_HISTORY_LIMIT)]
            live_history.reverse()

            channel_context = []
            for msg in live_history:
                role = "assistant" if (msg.author.bot and msg.author.id == bot.user.id) else "user"
                channel_context.append({
                    "role": role,
                    "content": f"{msg.author.display_name}: {msg.content}",
                })

            tone = detect_tone(message.content)

            user_id_mention = f"<@{message.author.id}>"
            user_mem_str = "\n".join(f"- {m['content']}" for m in user_memory.get(user_key, []))
            adjusted_prompt = build_prompt(system_prompt, tone, user_id_mention, user_mem_str)

            # If someone explicitly asks for an image, always enable the action
            image_keywords = ["draw", "imagine", "create an image", "generate", "make me a picture", "paint", "sketch"]
            if any(kw in message.content.lower() for kw in image_keywords):
                adjusted_prompt += "\n\nThe user wants an image. Append @IMAGE='detailed description of the image' to your reply. Be creative with the description."

            try:
                response = call_llm(
                    messages=[
                        {"role": "system", "content": adjusted_prompt},
                        *channel_context,
                    ],
                )

                reply = response.choices[0].message.content or ""
                reply = clean_reply(reply, bot.user.display_name, message.author.display_name)
                reply, actions = parse_actions(reply)

                if not reply.strip():
                    print(f"[WARN] Empty reply — raw: '{response.choices[0].message.content}'")
                    await message.channel.send(responses.EMPTY_REPLY)
                else:
                    await message.channel.send(reply)
                active_conversation[channel_id] = now

                # Execute actions
                if actions.get("react"):
                    try:
                        await message.add_reaction(actions["react"])
                    except Exception as e:
                        print(f"[Action] React failed: {e}")

                if actions.get("find"):
                    ctx = await bot.get_context(message)
                    results = await do_search(message.guild, actions["find"], message.author)
                    result_text = format_search_results(results, actions["find"], message.author.mention)
                    await message.channel.send(result_text)

                if actions.get("summary"):
                    channel_name = actions["summary"]
                    if channel_name.upper() == "THIS_CHANNEL":
                        target = message.channel
                    else:
                        target = resolve_channel(message.guild, channel_name)

                    if target:
                        summary = await do_summary(target, message.guild)
                        if summary:
                            embed = discord.Embed(
                                title=f"Summary of #{target.name}",
                                description=summary,
                                color=0xFF69B4,
                            )
                            await message.channel.send(embed=embed)
                        else:
                            await message.channel.send(responses.SUMMARY_EMPTY)
                    else:
                        await message.channel.send(responses.CHANNEL_NOT_FOUND)

                # GIF response
                if actions.get("gif"):
                    await search_gif(actions["gif"], message.channel)

                # Image generation — explicit action
                if actions.get("image"):
                    await generate_image(actions["image"], message.channel)

                # Spontaneous image generation
                elif not actions.get("image") and should_spontaneously_create(tone):
                    inspiration = call_llm(
                        messages=[
                            {"role": "system", "content": (
                                f"You are {config.BOT_NAME}. Based on this conversation, describe a single image you'd create "
                                "for this person right now. Be creative, unexpected, personal. "
                                "Output ONLY the image description, nothing else. Keep it under 200 characters. "
                                "It can be funny, sweet, chaotic, roast-worthy, or beautiful — match the vibe."
                            )},
                            *channel_context,
                        ],
                        max_tokens=100,
                        temperature=1.0,
                    )
                    image_prompt = inspiration.choices[0].message.content.strip()
                    if image_prompt:
                        await message.channel.send(responses.IMAGE_SPONTANEOUS)
                        await generate_image(image_prompt, message.channel)

            except APITimeoutError:
                await message.channel.send(responses.API_TIMEOUT)
            except APIError as e:
                print(f"[ERROR] API error: {e}")
                await message.channel.send(responses.API_ERROR)
            except Exception as e:
                print(f"[ERROR] Unexpected: {e}")
                await message.channel.send(responses.GENERAL_ERROR)

    await bot.process_commands(message)


# === SLASH COMMANDS ===

@bot.tree.command(name="find", description="Search messages across channels")
@app_commands.describe(
    query="What to search for",
    channel="Specific channel to search (optional)",
)
async def slash_find(interaction: discord.Interaction, query: str, channel: Optional[discord.TextChannel] = None):
    await interaction.response.defer()

    channel_id = str(channel.id) if channel else None
    results = await do_search(interaction.guild, query, interaction.user, channel_id=channel_id)
    text = format_search_results(results, query, interaction.user.mention)

    await interaction.followup.send(text)


@bot.tree.command(name="imagine", description="Generate an image")
@app_commands.describe(prompt="What to create")
async def slash_imagine(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    await interaction.followup.send(responses.IMAGE_WORKING)
    await generate_image(prompt, interaction.channel)


@bot.tree.command(name="summarize", description="Get a summary of a channel")
@app_commands.describe(
    channel="Channel to summarize (defaults to current)",
    hours="Only summarize the last N hours (optional)",
)
async def slash_summarize(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
    hours: Optional[int] = None,
):
    await interaction.response.defer()

    target = channel or interaction.channel

    # Permission check
    if channel and not channel.permissions_for(interaction.user).read_messages:
        await interaction.followup.send(responses.SUMMARY_NO_PERMISSION)
        return

    summary = await do_summary(target, interaction.guild, hours=hours)
    if not summary:
        await interaction.followup.send(responses.SUMMARY_EMPTY)
        return

    embed = discord.Embed(
        title=f"Summary of #{target.name}" + (f" (last {hours}h)" if hours else ""),
        description=summary,
        color=0xFF69B4,
    )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="ping", description="Check if the bot is alive")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(responses.PING.format(latency=latency))


@bot.tree.command(name="stats", description="Message store stats")
async def slash_stats(interaction: discord.Interaction):
    stats = await message_store.get_stats()
    if not stats.get("available"):
        await interaction.response.send_message(responses.DB_UNAVAILABLE)
        return

    await interaction.response.send_message(
        f"**Messages logged:** {stats['total_messages']:,}\n"
        f"**Channels tracked:** {stats['channels']}\n"
        f"**Unique users:** {stats['users']}"
    )


# === PREFIX COMMANDS (keep for backwards compat) ===

@bot.command(name="find")
async def cmd_find(ctx, *, query: str):
    async with ctx.typing():
        results = await do_search(ctx.guild, query, ctx.author)
        text = format_search_results(results, query, ctx.author.mention)
        await ctx.send(text)


@bot.command(name="summarize")
async def cmd_summarize(ctx, *, channel_input: str = None):
    async with ctx.typing():
        if not channel_input or channel_input.upper() == "THIS_CHANNEL":
            target = ctx.channel
        else:
            if isinstance(channel_input, discord.TextChannel):
                target = channel_input
            else:
                target = resolve_channel(ctx.guild, channel_input)

        if not target:
            await ctx.send(responses.CHANNEL_NOT_FOUND)
            return

        if not target.permissions_for(ctx.author).read_messages:
            await ctx.send(responses.SUMMARY_NO_PERMISSION)
            return

        summary = await do_summary(target, ctx.guild)
        if not summary:
            await ctx.send(responses.SUMMARY_EMPTY)
            return

        embed = discord.Embed(
            title=f"Summary of #{target.name}",
            description=summary,
            color=0xFF69B4,
        )
        await ctx.send(embed=embed)


@bot.command(name="ping")
async def cmd_ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(responses.PING.format(latency=latency))


@bot.command(name="chat")
async def deprecated_chat(ctx):
    await ctx.send(f"{ctx.author.mention} {responses.DEPRECATED_CHAT}")


# === ERROR HANDLING ===

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(responses.COMMAND_NOT_FOUND)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(responses.MISSING_ARGUMENT)
    else:
        await ctx.send(f"Unexpected error: {str(error)}")
        raise error


# === RUN ===

if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        print("Missing token. Set DISCORD_BOT_TOKEN.")
    elif not config.OPENAI_API_KEY:
        print("Missing API key. Set OPENAI_API_KEY.")
    else:
        bot.run(config.DISCORD_TOKEN)
