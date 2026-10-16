"""
Recupere les cours des titres BRVM et ecrit cours-auto.json a la racine du depot.
Concu pour tourner via GitHub Actions, une fois par jour.

- "cours"   : tes titres habituels, sous le nom utilise dans l'app (compatibilite)
- "tickers" : TOUS les titres trouves sur la page, par code BRVM (ex: SGBC, ORAC...),
              ce qui permet a l'app de trouver le cours de n'importe quel nouveau titre.
- "fractionnements" : les fractionnements (ou regroupements) d'actions PROBABLES,
              reperes en comparant le cours du jour a celui de la veille. La BRVM
              plafonne la variation d'une seance a environ 7,5 % : un cours divise
              (ou multiplie) d'un coup par 2, 5, 10... ne peut etre qu'une operation
              sur le titre. L'app les propose ensuite a la validation (jamais applique
              sans confirmation).

Source : la page publique brvm.org (le petit tableau "cours du jour" present sur
presque toutes les pages). On analyse le texte de la page plutot que sa structure
HTML, pour rester robuste si la mise en page du site change legerement.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

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

# Ratios "ronds" plausibles pour un fractionnement ou un regroupement
RATIOS_CANDIDATS = [2, 3, 4, 5, 10, 20, 25, 50, 100]
TOLERANCE = 0.12          # ecart relatif admis autour du ratio rond
SEUIL_DETECTION = 1.6     # en dessous d'une division par 1,6 on ne regarde meme pas
CONSERVATION_JOURS = 120  # duree pendant laquelle un fractionnement detecte reste propose

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


def charger_precedent():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ratio_rond(r):
    """Renvoie le ratio rond le plus proche de r s'il est assez proche, sinon None."""
    meilleur = None
    for c in RATIOS_CANDIDATS:
        ecart = abs(r / c - 1)
        if ecart <= TOLERANCE and (meilleur is None or ecart < meilleur[1]):
            meilleur = (c, ecart)
    return meilleur[0] if meilleur else None


def detecter_fractionnements(precedent, all_cours, today, today_iso):
    """Compare les cours du jour aux cours precedents et renvoie la liste a jour."""
    anciens = precedent.get("tickers") or {}
    liste = [f for f in (precedent.get("fractionnements") or []) if isinstance(f, dict)]
    limite = (datetime.now(timezone.utc) - timedelta(days=CONSERVATION_JOURS)).strftime("%Y-%m-%d")
    liste = [f for f in liste if (f.get("dateISO") or "") >= limite]
    deja = {(f.get("code"), f.get("dateISO")) for f in liste}
    for code, nouveau in all_cours.items():
        ancien_info = anciens.get(code) or {}
        ancien = ancien_info.get("cours")
        if not ancien or not nouveau or ancien_info.get("date") == today:
            continue
        if ancien / nouveau >= SEUIL_DETECTION:
            c = ratio_rond(ancien / nouveau)
            ratio = c                       # 1 ancienne action -> c nouvelles
        elif nouveau / ancien >= SEUIL_DETECTION:
            c = ratio_rond(nouveau / ancien)
            ratio = (1.0 / c) if c else None  # regroupement : c anciennes -> 1 nouvelle
        else:
            continue
        if not ratio or (code, today_iso) in deja:
            continue
        liste.append({
            "code": code, "date": today, "dateISO": today_iso, "ratio": ratio,
            "coursAvant": ancien, "coursApres": nouveau,
        })
        print("Fractionnement probable :", code, ancien, "->", nouveau, "ratio", ratio)
    return liste


def main():
    try:
        html = fetch_html(BRVM_URL)
    except Exception as e:
        print("ERREUR reseau lors de la recuperation de la page BRVM :", e, file=sys.stderr)
        sys.exit(1)

    flat = strip_and_collapse(html)
    precedent = charger_precedent()
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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

    fractionnements = detecter_fractionnements(precedent, all_cours, today, today_iso)

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": BRVM_URL,
        "cours": cours,
        "tickers": tickers,
        "fractionnements": fractionnements,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Titres trouves :", len(tickers))
    print(json.dumps(output["cours"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
