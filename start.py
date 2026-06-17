"""Start the FastAPI server + background scheduler."""

import asyncio
import uvicorn
from api.main import app
from scheduler.processor import start_scheduler


async def main():
    scheduler_task = start_scheduler()
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio", log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        scheduler_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
