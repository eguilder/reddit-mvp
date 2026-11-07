import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()

ROOT = Path(__file__).parent
DATABASE_PATH = os.getenv("DATABASE_PATH", str(ROOT / "reddit_curator.db"))
DEFAULT_SUBREDDITS = os.getenv(
    "REDDIT_SUBREDDITS", "MachineLearning,LocalLLaMA,programming,Entrepreneur"
)
REDDIT_USER_AGENT = "reddit-curator-local/0.1 by local-user"

app = FastAPI(title="Reddit Curator", version="0.1.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class Settings(BaseModel):
    interests: list[str] = Field(default_factory=lambda: [
        "practical machine learning",
        "indie software businesses",
        "useful programming techniques",
    ])
    avoid: list[str] = Field(default_factory=lambda: ["rage-bait", "celebrity news"])
    subreddits: list[str] = Field(default_factory=lambda: [x.strip() for x in DEFAULT_SUBREDDITS.split(",") if x.strip()])
    minimum_score: float = 0.45
    limit: int = 40


class Feedback(BaseModel):
    post_id: str
    label: str


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS feedback (post_id TEXT PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    connection.commit()
    return connection


def get_settings() -> Settings:
    connection = db()
    row = connection.execute("SELECT data FROM settings WHERE id = 1").fetchone()
    connection.close()
    if not row:
        return Settings()
    return Settings.model_validate_json(row["data"])


def save_settings(settings: Settings) -> Settings:
    connection = db()
    connection.execute(
        "INSERT INTO settings(id, data) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
        (settings.model_dump_json(),),
    )
    connection.commit()
    connection.close()
    return settings


def hard_filter(post: dict[str, Any], settings: Settings) -> bool:
    text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
    return not any(term.lower() in text for term in settings.avoid)


def heuristic_score(post: dict[str, Any], settings: Settings) -> tuple[float, list[str], str]:
    text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
    matched = [interest for interest in settings.interests if any(word.lower() in text for word in interest.split() if len(word) > 3)]
    score = min(0.95, 0.28 + 0.18 * len(matched) + min(post.get("score", 0), 500) / 5000)
    reason = "Matched: " + ", ".join(matched) if matched else "Weak match based on configured interests."
    return round(score, 2), matched, reason


def score_with_model(posts: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not posts:
        for post in posts:
            post["interest_score"], post["matched_interests"], post["reason"] = heuristic_score(post, settings)
        return posts

    client = OpenAI(api_key=api_key)
    payload = [{"id": p["id"], "title": p["title"], "body": p["selftext"][:1500], "subreddit": p["subreddit"]} for p in posts]
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        input=[{
            "role": "system",
            "content": "Score Reddit posts for a personal feed. Return JSON array only. Each item must have id, interest_score (0 to 1), matched_interests (array), and reason (short string). Be conservative: show a post only when it clearly matches the interests.",
        }, {
            "role": "user",
            "content": json.dumps({"interests": settings.interests, "avoid": settings.avoid, "posts": payload}),
        }],
    )
    try:
        scored = {item["id"]: item for item in json.loads(response.output_text)}
        for post in posts:
            result = scored.get(post["id"], {})
            post["interest_score"] = float(result.get("interest_score", 0))
            post["matched_interests"] = result.get("matched_interests", [])
            post["reason"] = result.get("reason", "")
    except (ValueError, TypeError, KeyError):
        for post in posts:
            post["interest_score"], post["matched_interests"], post["reason"] = heuristic_score(post, settings)
    return posts


async def fetch_posts(settings: Settings) -> list[dict[str, Any]]:
    token = os.getenv("REDDIT_ACCESS_TOKEN")
    headers = {"User-Agent": REDDIT_USER_AGENT}
    url = "https://oauth.reddit.com/best" if token else "https://www.reddit.com/r/" + "+".join(settings.subreddits) + "/hot.json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"limit": min(settings.limit, 100), "raw_json": 1}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        response = await client.get(url, params=params)
        if response.status_code == 403 and not token:
            return [
                {"id": "demo-1", "title": "A practical guide to evaluating small language models", "selftext": "Benchmarks, deployment notes, and lessons from a small production experiment.", "subreddit": "MachineLearning", "author": "demo", "score": 184, "num_comments": 31, "url": "https://www.reddit.com/r/MachineLearning/", "created_utc": 0},
                {"id": "demo-2", "title": "How I built a tiny paid developer tool", "selftext": "A transparent write-up covering product decisions, distribution, and recurring revenue.", "subreddit": "Entrepreneur", "author": "demo", "score": 96, "num_comments": 18, "url": "https://www.reddit.com/r/Entrepreneur/", "created_utc": 0},
                {"id": "demo-3", "title": "Discussion: choosing a reliable Python web stack", "selftext": "Comparing a few lightweight approaches for a maintainable personal project.", "subreddit": "programming", "author": "demo", "score": 72, "num_comments": 22, "url": "https://www.reddit.com/r/programming/", "created_utc": 0},
            ]
        response.raise_for_status()
    data = response.json()
    children = data.get("data", {}).get("children", [])
    return [{
        "id": item["data"]["id"],
        "title": item["data"].get("title", ""),
        "selftext": item["data"].get("selftext", ""),
        "subreddit": item["data"].get("subreddit", ""),
        "author": item["data"].get("author", "[deleted]"),
        "score": item["data"].get("score", 0),
        "num_comments": item["data"].get("num_comments", 0),
        "url": "https://www.reddit.com" + item["data"].get("permalink", ""),
        "created_utc": item["data"].get("created_utc", 0),
    } for item in children]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/settings")
def read_settings() -> Settings:
    return get_settings()


@app.put("/api/settings")
def update_settings(settings: Settings) -> Settings:
    return save_settings(settings)


@app.post("/api/feedback")
def add_feedback(feedback: Feedback) -> dict[str, str]:
    connection = db()
    connection.execute(
        "INSERT INTO feedback(post_id, label, created_at) VALUES(?, ?, ?) ON CONFLICT(post_id) DO UPDATE SET label=excluded.label, created_at=excluded.created_at",
        (feedback.post_id, feedback.label, datetime.now(timezone.utc).isoformat()),
    )
    connection.commit()
    connection.close()
    return {"status": "saved"}


@app.get("/api/feed")
async def feed() -> dict[str, Any]:
    settings = get_settings()
    try:
        posts = [post for post in await fetch_posts(settings) if hard_filter(post, settings)]
        posts = score_with_model(posts, settings)
        posts = [post for post in posts if post["interest_score"] >= settings.minimum_score]
        posts.sort(key=lambda post: (post["interest_score"], post["score"]), reverse=True)
        return {"posts": posts, "mode": "openai" if os.getenv("OPENAI_API_KEY") else "heuristic", "count": len(posts)}
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"Reddit request failed: {error}") from error
