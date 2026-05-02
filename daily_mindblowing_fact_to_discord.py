import os
import random
import re
from datetime import date, timedelta
from pathlib import Path

import requests

NASA_APOD_API = "https://api.nasa.gov/planetary/apod"
APOD_START_DATE = date(1995, 6, 16)
SENT_HISTORY_FILE = Path("sent_fact_history.txt")
MAX_APOD_ATTEMPTS = 20

FALLBACK_FACTS = [
    {
        "id": "fallback:neutron-star-density",
        "title": "Neutron star",
        "fact": "A teaspoon of neutron star matter would weigh billions of tons on Earth.",
        "url": "https://science.nasa.gov/universe/stars/neutron-stars/",
    },
    {
        "id": "fallback:venus-day-year",
        "title": "Venus",
        "fact": "A day on Venus is longer than a year on Venus.",
        "url": "https://science.nasa.gov/venus/",
    },
    {
        "id": "fallback:supernova-brightness",
        "title": "Supernova",
        "fact": "A supernova can briefly outshine an entire galaxy.",
        "url": "https://science.nasa.gov/universe/stars/supernovae/",
    },
]


def get_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_optional_env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def load_sent_ids() -> set[str]:
    sent_ids = set()
    if not SENT_HISTORY_FILE.exists():
        return sent_ids

    for line in SENT_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if item and not item.startswith("#"):
            sent_ids.add(item.casefold())

    return sent_ids


def save_sent_id(sent_id: str) -> None:
    existing_ids = []
    normalized_ids = set()

    if SENT_HISTORY_FILE.exists():
        for line in SENT_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                existing_ids.append(item)
                normalized_ids.add(item.casefold())

    if sent_id.casefold() not in normalized_ids:
        existing_ids.append(sent_id)

    SENT_HISTORY_FILE.write_text("\n".join(sorted(existing_ids, key=str.casefold)) + "\n", encoding="utf-8")


def random_apod_date() -> str:
    latest = date.today() - timedelta(days=1)
    days = (latest - APOD_START_DATE).days
    return (APOD_START_DATE + timedelta(days=random.randint(0, days))).isoformat()


def fetch_apod(apod_date: str, api_key: str) -> dict | None:
    params = {
        "api_key": api_key,
        "date": apod_date,
        "thumbs": "true",
    }
    try:
        response = requests.get(NASA_APOD_API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    if not data.get("title") or not data.get("explanation"):
        return None

    return data


def clean_text(text: str) -> str:
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def discord_position_text(text: str) -> str:
    text = re.sub(r"\babove picture\b", "below picture", text, flags=re.IGNORECASE)
    text = re.sub(r"\babove image\b", "below image", text, flags=re.IGNORECASE)
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [clean_text(part) for part in parts if clean_text(part)]


def sentence_score(sentence: str) -> int:
    lowered = sentence.lower()
    score = 0

    punchy_terms = [
        "billion",
        "million",
        "light-year",
        "massive",
        "giant",
        "black hole",
        "supernova",
        "galaxy",
        "nebula",
        "star",
        "planet",
        "comet",
        "asteroid",
        "radiation",
        "gravity",
        "collision",
        "explosion",
        "largest",
        "oldest",
        "fastest",
        "deepest",
        "hottest",
    ]
    for term in punchy_terms:
        if term in lowered:
            score += 3

    if re.search(r"\b\d+([,.]\d+)?\b", lowered):
        score += 4
    if 80 <= len(sentence) <= 240:
        score += 3
    if len(sentence) > 300:
        score -= 6

    return score


def best_fact_sentence(explanation: str) -> str:
    candidates = [
        sentence for sentence in split_sentences(explanation)
        if 45 <= len(sentence) <= 320
    ]
    if not candidates:
        return discord_position_text(clean_text(explanation)[:300].rstrip())

    candidates.sort(key=sentence_score, reverse=True)
    return discord_position_text(candidates[0])


def media_url(apod: dict) -> str | None:
    if apod.get("media_type") == "image":
        return apod.get("hdurl") or apod.get("url")
    return apod.get("thumbnail_url") or apod.get("url")


def find_fact() -> dict:
    api_key = get_optional_env("NASA_API_KEY", "DEMO_KEY")
    sent_ids = load_sent_ids()

    for _ in range(MAX_APOD_ATTEMPTS):
        apod_date = random_apod_date()
        sent_id = f"apod:{apod_date}"
        if sent_id.casefold() in sent_ids:
            continue

        apod = fetch_apod(apod_date, api_key)
        if not apod:
            continue

        selected_media_url = media_url(apod)
        return {
            "id": sent_id,
            "title": apod["title"],
            "fact": best_fact_sentence(apod["explanation"]),
            "url": selected_media_url or apod.get("url"),
            "date": apod_date,
        }

    fallback_choices = [
        fact for fact in FALLBACK_FACTS
        if fact["id"].casefold() not in sent_ids
    ]
    if not fallback_choices:
        raise RuntimeError("No unsent NASA APOD dates or fallback facts were available.")

    return random.choice(fallback_choices)


def send_to_discord(webhook_url: str, fact: dict) -> None:
    message = (
        f"🌌 **Daily NASA transmission for the boys**\n\n"
        f"{fact['fact']}\n\n"
        f"*Source: NASA APOD - {fact['title']}*"
    )

    if fact.get("date"):
        message += f"\n*APOD date: {fact['date']}*"
    if fact.get("url"):
        message += f"\n🔗 {fact['url']}"

    response = requests.post(
        webhook_url,
        data={"content": message},
        timeout=60,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook error: {response.status_code} {response.text}")


def main() -> None:
    webhook_url = get_env("DISCORD_FACTS_WEBHOOK_URL")

    fact = find_fact()
    send_to_discord(webhook_url, fact)
    save_sent_id(fact["id"])


if __name__ == "__main__":
    main()
