"""Drain non-authoritative thread work before releasing its owning component."""
import asyncio


async def run(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        # Retrieve failures as well as success; cancellation retains priority.
        if not task.cancelled():
            task.exception()
        raise
