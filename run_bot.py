"""run_bot.py — Start the Discord Bot v2."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "bot"))
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from bot.bot import main

if __name__ == "__main__":
    print("[Bot] Starting Discord Bot v2...")
    asyncio.run(main())
