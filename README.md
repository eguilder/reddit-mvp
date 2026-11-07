# Reddit Curator

A small local web app for fetching Reddit posts, filtering them with explicit rules, scoring them against your interests, and browsing a ranked feed.

## Run on Ubuntu 22.04

```bash
sudo apt update
sudo apt install -y python3 python3-venv
cd reddit-curator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.

The app works in demo mode without API keys. Add `OPENAI_API_KEY` to enable semantic scoring. Add a Reddit OAuth access token to read your personal home feed; otherwise it reads the configured public subreddits.

## Configuration

Edit `.env` or use the settings panel in the UI:

- `REDDIT_SUBREDDITS`: comma-separated public subreddits
- `REDDIT_ACCESS_TOKEN`: optional OAuth bearer token
- `OPENAI_API_KEY`: optional model scoring
- `OPENAI_MODEL`: defaults to `gpt-5-mini`
- `DATABASE_PATH`: defaults to `reddit_curator.db`
