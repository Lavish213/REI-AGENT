import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from backend.scout.expired import run_expired_scraper

if __name__ == "__main__":
    run_expired_scraper()
