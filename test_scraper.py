import asyncio
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
os.environ["DATA_DIR"] = os.path.join(current_dir, "data")

from bot.marleenkookt import MarleenChecker
from bot.config import MARLEENKOOKT_EMAIL

async def main():
    print("=" * 60)
    print("STARTING MARLEENKOOKT SCRAPER TEST")
    print(f"Target email: {MARLEENKOOKT_EMAIL[:3]}***@{MARLEENKOOKT_EMAIL.split('@')[-1] if '@' in MARLEENKOOKT_EMAIL else 'unknown'}")
    print(f"Data directory: {os.environ['DATA_DIR']}")
    print("=" * 60)

    checker = MarleenChecker()
    is_selected, reason, info = await checker.check_meals_selected()

    print("=" * 60)
    print("TEST RESULT:")
    print(f"Is Selected: {is_selected}")
    print(f"Reason:      {reason}")
    print(f"Info:        {info}")
    print(f"Screenshot:  {checker.screenshot_path}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
