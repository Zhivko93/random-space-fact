import os
import random
import re
from pathlib import Path

import requests

WIKI_API = "https://en.wikipedia.org/w/api.php"

WEIGHTED_TOPICS = [
    "Astronomy", "Astronomy", "Astronomy",
    "Cosmology", "Cosmology",
    "Astrophysics", "Astrophysics",
    "Black holes", "Black holes",
    "Galaxies", "Galaxies",
    "Stars", "Stars",
    "Exoplanets",
    "Space exploration",
    "Solar System",
    "Physics", "Physics", "Physics",
    "Quantum mechanics",
    "Relativity",
    "Particle physics",
    "Geophysics",
    "Volcanology",
    "Earthquakes",
    "Extreme weather",
    "Natural disasters",
    "Geology",
    "Planetary science",
    "Human evolution",
    "Ancient humans",
]

PRIMARY_KEYWORDS = [
    "largest",
    "smallest",
    "millions",
    "billions",
    "light-years",
    "black hole",
    "faster than",
]

BONUS_TERMS = [
    "universe",
    "star",
    "galaxy",
    "planet",
    "cosmic",
    "neutron",
    "supernova",
    "singularity",
    "gravity",
    "volcano",
    "earthquake",
    "massive",
    "extreme",
    "giant",
    "oldest",
    "youngest",
    "dense",
    "speed",
    "temperature",
    "deepest",
    "highest",
    "solar",
    "lunar",
    "orbit",
    "asteroid",
    "comet",
    "quasar",
    "magnetic",
    "atmosphere",
    "evolution",
    "extinct",
]

STATE_FILE = Path("last_fact_title.txt")


def get_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_last_title() -> str | None:
    if STATE_FILE.exists():
        return STATE_FILE.read_text(encoding="utf-8").strip() or None
    return None


def save_last_title(title: str) -> None:
    STATE_FILE.write_text(title, encoding="utf-8")


def wiki_request(params: dict) -> dict:
    response = requests.get(WIKI_API, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def get_random_page_from_category(category: str) -> tuple[str, int]:
    params = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": 100,
        "cmtype": "page",
    }
    data = wiki_request(params)
    pages = data.get("query", {}).get("categorymembers", [])
    if not pages:
        raise RuntimeError(f"No pages found for category: {category}")

    chosen = random.choice(pages)
    return chosen["title"], chosen["pageid"]


def get_page_extract(pageid: int) -> str:
    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts",
        "pageids": pageid,
        "explaintext": 1,
        "exintro": 1,
    }
    data = wiki_request(params)
    pages = data.get("query", {}).get("pages", {})
    page = pages.get(str(pageid), {})
    return page.get("extract", "")


def clean_text(text: str) -> str:
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [clean_text(p) for p in parts if clean_text(p)]


def looks_bad(sentence: str) -> bool:
    s = sentence.lower()

    if len(sentence) < 45:
        return True
    if len(sentence) > 320:
        return True

    bad_starts = [
        "it is",
        "this is",
        "he was",
        "she was",
        "they were",
        "in ",
        "on ",
        "for ",
    ]
    if any(s.startswith(x) for x in bad_starts) and len(sentence) < 80:
        return True

    bad_contains = [
        "may refer to",
        "can refer to",
        "is a surname",
        "is a given name",
        "may also refer to",
        "disambiguation",
    ]
    if any(x in s for x in bad_contains):
        return True

    return False


def sentence_score(sentence: str, title: str = "") -> int:
    s = sentence.lower()
    score = 0

    for keyword in PRIMARY_KEYWORDS:
        if keyword in s:
            score += 8

    for term in BONUS_TERMS:
        if term in s:
            score += 2

    # numbers often make facts stronger
    if re.search(r"\b\d+\b", s):
        score += 3

    if re.search(r"\b\d+(,\d{3})+\b", s):
        score += 2

    # scientific units / scales
    if any(unit in s for unit in [
        "km", "kilomet", "mile", "light-year", "°c", "kelvin",
        "million", "billion", "trillion", "years", "tons"
    ]):
        score += 3

    # Prefer stronger sentence structure
    if "," in sentence:
        score += 1

    # Topic boost from title too
    title_lower = title.lower()
    for term in ["black hole", "galaxy", "neutron", "earthquake", "volcano", "planet", "star"]:
        if term in title_lower:
            score += 2

    return score


def choose_best_sentence(extract: str, title: str) -> tuple[str | None, int]:
    sentences = split_sentences(extract)
    if not sentences:
        return None, -1

    scored = []
    for sentence in sentences:
        if looks_bad(sentence):
            continue
        scored.append((sentence_score(sentence, title), sentence))

    if not scored:
        return None, -1

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_sentence = scored[0]
    return best_sentence, best_score


def find_fact(max_attempts: int = 60) -> tuple[str, str]:
    last_title = load_last_title()
    best_fallback = None
    best_fallback_score = -1

    for _ in range(max_attempts):
        category = random.choice(WEIGHTED_TOPICS)

        try:
            title, pageid = get_random_page_from_category(category)
        except Exception:
            continue

        if last_title and title == last_title:
            continue

        try:
            extract = get_page_extract(pageid)
        except Exception:
            continue

        if not extract:
            continue

        sentence, score = choose_best_sentence(extract, title)
        if not sentence:
            continue

        # Strong hit: take it immediately
        if score >= 8:
            return title, sentence

        # Otherwise remember the best fallback
        if score > best_fallback_score:
            best_fallback = (title, sentence)
            best_fallback_score = score

    if best_fallback:
        return best_fallback

    raise RuntimeError("Could not find a good fact after multiple attempts.")


def send_to_discord(webhook_url: str, title: str, fact: str) -> None:
    message = f"🌌 **Daily mind-blowing fact**\n\n{fact}\n\n*Source topic: {title}*"

    response = requests.post(
        webhook_url,
        data={"content": message},
        timeout=60,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook error: {response.status_code} {response.text}")


def main() -> None:
    webhook_url = get_env("DISCORD_FACTS_WEBHOOK_URL")

    title, fact = find_fact()
    send_to_discord(webhook_url, title, fact)
    save_last_title(title)


if __name__ == "__main__":
    main()
