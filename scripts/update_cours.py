"""
Recupere les cours des titres BRVM et ecrit cours-auto.json a la racine du depot.
Concu pour tourner via GitHub Actions, une fois par jour.

- "cours"   : tes titres habituels, sous le nom utilise dans l'app (compatibilite)
- "tickers" : TOUS les titres trouves sur la page, par code BRVM (ex: SGBC, ORAC...),
              ce qui permet a l'app de trouver le cours de n'importe quel nouveau titre.

Source : la page publique brvm.org (le petit tableau "cours du jour" present sur
presque toutes les pages). On analyse le texte de la page plutot que sa structure
HTML, pour rester robuste si la mise en page du site change legerement.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

BRVM_URL = "https://www.brvm.org/fr/capitalisations/0"

# Code BRVM -> nom du titre tel qu'utilise dans l'app (tes titres habituels)
TICKER_MAP = {
    "CBIBF": "CBI BF",
    "BOAM": "BOA Mali",
    "BOAB": "BOA Bénin",
    "BICB": "BICB",
    "SNTS": "SNTS",
}

OUTPUT_FILE = "cours-auto.json"

# code (3 a 6 caracteres), puis cours (espaces = separateur de milliers), puis variation en %
ALL_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{2,5})\s+(\d{1,3}(?: \d{3})*)\s+(-?\d+[,.]\d+)\s*%")


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


def parse_all(text):
    """Retourne {code: cours}. En cas de doublon, on garde la premiere occurrence."""
    result = {}
    for m in ALL_PATTERN.finditer(text):
        code = m.group(1)
        if code not in result:
            result[code] = int(m.group(2).replace(" ", ""))
    return result


def main():
    try:
        html = fetch_html(BRVM_URL)
    except Exception as e:
        print("ERREUR reseau lors de la recuperation de la page BRVM :", e, file=sys.stderr)
        sys.exit(1)

    flat = strip_and_collapse(html)
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    all_cours = parse_all(flat)

    cours = {}
    missing = []
    for ticker, titre in TICKER_MAP.items():
        if ticker in all_cours:
            cours[titre] = {"cours": all_cours[ticker], "date": today}
        else:
            missing.append(ticker)

    if missing:
        print("Avertissement : tickers non trouves cette fois-ci :", ", ".join(missing), file=sys.stderr)

    if not cours:
        print("ERREUR : aucun cours n'a pu etre extrait, on n'ecrase pas le fichier existant.", file=sys.stderr)
        sys.exit(1)

    tickers = {code: {"cours": value, "date": today} for code, value in sorted(all_cours.items())}

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": BRVM_URL,
        "cours": cours,
        "tickers": tickers,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Titres trouves :", len(tickers))
    print(json.dumps(output["cours"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
