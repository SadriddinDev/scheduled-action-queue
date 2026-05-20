import asyncio
import logging

from app.database import engine, Base
from app.worker import worker_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await worker_loop()


if __name__ == "__main__":
    asyncio.run(main())
