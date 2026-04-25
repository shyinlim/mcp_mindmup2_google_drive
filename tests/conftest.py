import asyncio


def run_async(coro):
    """Run an async coroutine in a fresh event loop. Shared test helper."""
    return asyncio.new_event_loop().run_until_complete(coro)
