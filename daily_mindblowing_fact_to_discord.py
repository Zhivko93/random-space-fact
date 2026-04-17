import os
import random
import re
from pathlib import Path
from urllib.parse import quote

import requests

WIKI_SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# Weighted toward space, physics, Earth extremes, and humanity
WEIGHTED_TOPICS = [
    "Black hole", "Black hole", "Black hole",
    "Neutron star", "Neutron star",
    "Supernova", "Supernova",
    "Milky Way", "Andromeda Galaxy", "Galaxy",
    "Observable universe", "Observable universe",
    "Exoplanet", "Exoplanet",
    "Sun", "Mars", "Jupiter", "Saturn",
    "Solar System", "Asteroid belt",
    "Quasar", "Pulsar", "Magnetar",
    "General relativity", "Quantum mechanics",
    "Speed of light", "Gravity", "Dark matter",
    "Earth", "Earthquake", "Volcano", "Plate tectonics",
    "Yellowstone Caldera", "Toba catastrophe theory",
    "Mount Everest", "Mariana Trench",
    "Atmosphere of Earth", "Aurora",
    "Human evolution", "Homo sapiens", "Neanderthal",
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
    "collapse",
    "explosion",
    "radiation",
    "core",
    "ice giant",
]

# Guaranteed fallback facts so the automation never dies on a bad day
FALLBACK_FACTS = [
    (
        "Neutron star",
        "A teaspoon of neutron star matter would weigh billions of tons on Earth."
    ),
    (
        "Observable universe",
        "The observable universe is about 93 billion light-years in diameter, even though it is only about 13.8 billion years old."
    ),
    (
        "Black hole",
        "Near a black hole, gravity is so extreme that time passes more slowly compared with farther-away observers."
    ),
    (
        "Mariana Trench",
        "The Mariana Trench is so deep that if Mount Everest were placed inside it, the summit would still be underwater."
    ),
    (
        "Supernova",
        "A supernova can briefly outshine an entire galaxy."
    ),
    (
        "Human evolution",
        "Modern humans shared the Earth with other human species, including Neanderthals."
    ),
    (
        "Lightning",
        "Lightning can heat the air to temperatures hotter than the surface of the Sun."
    ),
    (
        "Venus",
        "A day on Venus is longer than a year on Venus."
    ),
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


def fetch_summary(title: str) -> dict | None:
    url = WIKI_SUMMARY_API + quote(title, safe="")
    try:
        response = requests.get(url, timeout=30, headers={"User-Agent": "daily-fact-bot/1.0"})
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    if data.get("type") == "disambiguation":
        return None

    extract = data.get("extract", "").strip()
    if not extract:
        return None

    wiki_url = data.get("content_urls", {}).get("desktop", {}).get("page")

    return {
        "title": data.get("title", title),
        "extract": extract,
        "url": wiki_url,
    }


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

    if len(sentence) < 35:
        return True
    if len(sentence) > 320:
        return True

    bad_contains = [
        "may refer to",
        "can refer to",
        "is a surname",
        "is a given name",
        "may also refer to",
        "disambiguation",
        "is an american",
        "is a british",
        "is a canadian",
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

    if re.search(r"\b\d+\b", s):
        score += 3

    if any(unit in s for unit in [
        "million", "billions", "billion", "trillion",
        "light-year", "light-years", "km", "miles",
        "degrees", "tons", "years old", "diameter"
    ]):
        score += 3

    title_lower = title.lower()
    for term in ["black hole", "neutron", "galaxy", "planet", "earthquake", "volcano", "supernova"]:
        if term in title_lower:
            score += 2

    # Slight boost for punchier statements
    if "," in sentence:
        score += 1

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
        # fallback to first decent sentence
        for sentence in sentences:
            if 35 <= len(sentence) <= 320:
                return sentence, 0
        return None, -1

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1], scored[0][0]


def pick_topic(last_title: str | None) -> str:
    attempts = 0
    while attempts < 20:
        title = random.choice(WEIGHTED_TOPICS)
        if title != last_title:
            return title
        attempts += 1
    return random.choice(WEIGHTED_TOPICS)


def find_fact(max_attempts: int = 30) -> tuple[str, str]:
    last_title = load_last_title()
    best_fallback = None
    best_fallback_score = -1

    for _ in range(max_attempts):
        topic = pick_topic(last_title)
        summary = fetch_summary(topic)
        if not summary:
            continue

        title = summary["title"]
        extract = summary["extract"]
        wiki_url = summary.get("url")

        sentence, score = choose_best_sentence(extract, title)
        if not sentence:
            continue

        # Strong hit: use immediately
        if score >= 8:
            return title, sentence, wiki_url

        if score > best_fallback_score:
            best_fallback = (title, sentence)
            best_fallback_score = score

    if best_fallback:
        return best_fallback

    # Guaranteed final fallback
    fallback_choices = [item for item in FALLBACK_FACTS if item[0] != last_title] or FALLBACK_FACTS
    title, fact = random.choice(fallback_choices)
    return title, fact, None


def send_to_discord(webhook_url: str, title: str, fact: str, wiki_url: str | None) -> None:
    message = f"🌌 **Daily mind-blowing fact**\n\n{fact}\n\n*Source topic: {title}*"

    if wiki_url:
        message += f"\n🔗 {wiki_url}"

    response = requests.post(
        webhook_url,
        data={"content": message},
        timeout=60,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook error: {response.status_code} {response.text}")


def main() -> None:
    webhook_url = get_env("DISCORD_FACTS_WEBHOOK_URL")

    title, fact, wiki_url = find_fact()
    send_to_discord(webhook_url, title, fact, wiki_url)
    save_last_title(title)


if __name__ == "__main__":
    main()
