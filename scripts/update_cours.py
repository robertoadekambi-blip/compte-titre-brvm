"""
Recupere les cours de cloture des titres BRVM suivis dans l'app, et ecrit
cours-auto.json a la racine du depot. Concu pour tourner via GitHub Actions,
une fois par jour.

Source : la page publique brvm.org (le petit tableau "cours du jour" qui
apparait sur presque toutes les pages du site). On analyse le texte de la
page plutot que sa structure HTML precise, pour rester robuste si la mise
en page du site change legerement.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

BRVM_URL = "https://www.brvm.org/fr/capitalisations/0"

# Ticker BRVM -> nom du titre tel qu'utilise dans l'app
TICKER_MAP = {
    "CBIBF": "CBI BF",
    "BOAM": "BOA Mali",
    "BOAB": "BOA Bénin",
    "BICB": "BICB",
    "SNTS": "SNTS",
}

OUTPUT_FILE = "cours-auto.json"


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; compte-titre-brvm-bot/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def strip_and_collapse(html):
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_cours(text, ticker):
    pattern = re.compile(r"\b" + re.escape(ticker) + r"\s+(\d{1,3}(?: \d{3})*)\s+(-?\d+[,.]\d+)\s*%")
    m = pattern.search(text)
    if not m:
        return None
    return int(m.group(1).replace(" ", ""))


def main():
    try:
        html = fetch_html(BRVM_URL)
    except Exception as e:
        print("ERREUR reseau lors de la recuperation de la page BRVM :", e, file=sys.stderr)
        sys.exit(1)

    flat = strip_and_collapse(html)
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    found = {}
    missing = []
    for ticker, titre in TICKER_MAP.items():
        cours = parse_cours(flat, ticker)
        if cours is not None:
            found[titre] = {"cours": cours, "date": today}
        else:
            missing.append(ticker)

    if missing:
        print("Avertissement : tickers non trouves cette fois-ci :", ", ".join(missing), file=sys.stderr)

    if not found:
        print("ERREUR : aucun cours n'a pu etre extrait, on n'ecrase pas le fichier existant.", file=sys.stderr)
        sys.exit(1)

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": BRVM_URL,
        "cours": found,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
