from aiohttp import web
import config


async def start_health_server():
    """Minimal health endpoint. No Flask, no threads — async native."""
    app = web.Application()
    app.router.add_get("/", _health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.HEALTH_PORT)
    await site.start()
    print(f"[Health] Listening on port {config.HEALTH_PORT}")


async def _health(request):
    return web.Response(text="Bot is alive and running.")
