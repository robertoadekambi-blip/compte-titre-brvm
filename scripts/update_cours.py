"""
Recupere les cours des titres BRVM et ecrit cours-auto.json a la racine du depot.
Concu pour tourner via GitHub Actions, deux fois par jour (16h30 et 23h30, heure du Benin).

- "cours"   : tes titres habituels, sous le nom utilise dans l'app (compatibilite)
- "tickers" : TOUS les titres trouves sur la page, par code BRVM (ex: SGBC, ORAC...),
              ce qui permet a l'app de trouver le cours de n'importe quel nouveau titre.
- "fractionnements" : les fractionnements (ou regroupements) d'actions PROBABLES,
              reperes en comparant le cours du jour a celui de la veille. La BRVM
              plafonne la variation d'une seance a environ 7,5 % : un cours divise
              (ou multiplie) d'un coup par 2, 5, 10... ne peut etre qu'une operation
              sur le titre. L'app les propose ensuite a la validation (jamais applique
              sans confirmation).

Source principale : la page "Cours des actions" de brvm.org, colonne "Cours Cloture",
avec la date de seance indiquee par la BRVM ("Derniere mise a jour").
Attention : la petite liste qui defile en haut du site affiche, une fois la seance
finie, le cours de la VEILLE et non la cloture. Elle ne sert plus que de secours si
le tableau de cloture est illisible (et c'est alors signale dans le fichier).
"""
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

COURS_URL = "https://www.brvm.org/fr/cours-actions/0"       # tableau officiel des clotures
BRVM_URL = "https://www.brvm.org/fr/capitalisations/0"      # secours : liste qui defile
FUSEAU_BENIN = timezone(timedelta(hours=1))
MIN_TITRES = 20   # en dessous, on considere que le tableau n'a pas ete lu correctement
MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}

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


def sans_accents(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


class LecteurTableaux(HTMLParser):
    """Recupere le texte de chaque cellule, ligne par ligne, de tous les tableaux."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lignes, self.ligne, self.cellule = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.ligne = []
        elif tag in ("td", "th") and self.ligne is not None:
            self.cellule = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.ligne is not None and self.cellule is not None:
            self.ligne.append(re.sub(r"\s+", " ", "".join(self.cellule)).strip())
            self.cellule = None
        elif tag == "tr" and self.ligne is not None:
            if self.ligne:
                self.lignes.append(self.ligne)
            self.ligne = None

    def handle_data(self, data):
        if self.cellule is not None:
            self.cellule.append(data)


def nombre(txt):
    t = re.sub(r"[\s\u00a0\u202f]", "", txt or "").replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return int(v) if v == int(v) else v


def lire_clotures(html):
    """Renvoie {code: cours de cloture} lu dans la colonne "Cours Cloture"."""
    lecteur = LecteurTableaux()
    lecteur.feed(html)
    resultat, i_code, i_clot = {}, None, None
    for ligne in lecteur.lignes:
        entetes = [sans_accents(c) for c in ligne]
        if any("cloture" in c for c in entetes) and any("symbole" in c or "code" in c for c in entetes):
            i_code = next(i for i, c in enumerate(entetes) if "symbole" in c or "code" in c)
            i_clot = next(i for i, c in enumerate(entetes) if "cloture" in c)
            continue
        if i_clot is None or len(ligne) <= max(i_code, i_clot):
            continue
        code = ligne[i_code].strip().upper()
        cours = nombre(ligne[i_clot])
        if re.fullmatch(r"[A-Z][A-Z0-9]{2,5}", code) and cours and code not in resultat:
            resultat[code] = cours
    return resultat


def lire_date_seance(html):
    """Date de la seance affichee par la BRVM ("Derniere mise a jour : ... 28 octobre 2026"),
    au format (jj/mm/aaaa, aaaa-mm-jj), ou (None, None) si introuvable."""
    texte = sans_accents(strip_and_collapse(html))
    m = re.search(r"mise a jour\W{0,10}(?:[a-z]+\W{1,3})?(\d{1,2})\s+([a-z]+)\s+(\d{4})", texte)
    if not m or m.group(2) not in MOIS:
        return None, None
    d = datetime(int(m.group(3)), MOIS[m.group(2)], int(m.group(1)))
    return d.strftime("%d/%m/%Y"), d.strftime("%Y-%m-%d")


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


def reference_veille(ancien_info, today):
    """Cours de reference d'une seance precedente, et sa date.

    Le robot passe deux fois par jour (16h30 et 23h30, heure du Benin). Au 2e passage,
    le cours enregistre est deja date d'aujourd'hui : la reference reste alors celle
    gardee au 1er passage (coursPrec). Sinon, c'est le dernier cours enregistre."""
    if not ancien_info:
        return None, None
    if ancien_info.get("date") == today:
        return ancien_info.get("coursPrec"), ancien_info.get("datePrec")
    return ancien_info.get("cours"), ancien_info.get("date")


def detecter_fractionnements(precedent, all_cours, today, today_iso):
    """Compare les cours du jour a ceux d'une seance precedente et renvoie la liste a jour.

    On compare toujours a un cours d'un AUTRE jour : si le passage de 16h30 a lu un
    cours pas encore mis a jour, celui de 23h30 detecte quand meme le fractionnement."""
    anciens = precedent.get("tickers") or {}
    liste = [f for f in (precedent.get("fractionnements") or []) if isinstance(f, dict)]
    limite = (datetime.now(timezone.utc) - timedelta(days=CONSERVATION_JOURS)).strftime("%Y-%m-%d")
    liste = [f for f in liste if (f.get("dateISO") or "") >= limite]
    deja = {(f.get("code"), f.get("dateISO")) for f in liste}
    for code, nouveau in all_cours.items():
        ancien, _ = reference_veille(anciens.get(code) or {}, today)
        if not ancien or not nouveau:
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
    precedent = charger_precedent()
    maintenant = datetime.now(FUSEAU_BENIN)
    today, today_iso = maintenant.strftime("%d/%m/%Y"), maintenant.strftime("%Y-%m-%d")
    all_cours, source, date_lue = {}, None, False

    # 1) Tableau officiel des clotures, date de seance donnee par la BRVM
    try:
        html = fetch_html(COURS_URL)
        all_cours = lire_clotures(html)
        if len(all_cours) >= MIN_TITRES:
            source = COURS_URL
            d, d_iso = lire_date_seance(html)
            if d:
                today, today_iso, date_lue = d, d_iso, True
            else:
                print("Avertissement : date de seance introuvable, date du jour utilisee.", file=sys.stderr)
        else:
            print("Avertissement : tableau des clotures illisible (", len(all_cours), "titres ).", file=sys.stderr)
    except Exception as e:
        print("Avertissement : page des clotures inaccessible :", e, file=sys.stderr)

    # 2) Secours : la liste qui defile (cours de la VEILLE une fois la seance finie)
    if source is None:
        try:
            all_cours = parse_all(strip_and_collapse(fetch_html(BRVM_URL)))
            source = BRVM_URL
        except Exception as e:
            print("ERREUR reseau lors de la recuperation de la page BRVM :", e, file=sys.stderr)
            sys.exit(1)

    # Les cours sont dates de la seance indiquee par la BRVM, pas du jour du passage : si
    # le robot passe avant la publication de la cloture du jour, il re-enregistre simplement
    # la seance precedente, sans la faire passer pour celle d'aujourd'hui.
    print("Source :", source, "| seance :", today if date_lue else "date du passage (" + today + ")")

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

    anciens = precedent.get("tickers") or {}
    tickers = {}
    for code, value in sorted(all_cours.items()):
        prec, date_prec = reference_veille(anciens.get(code) or {}, today)
        tickers[code] = {"cours": value, "date": today}
        if prec:
            tickers[code]["coursPrec"] = prec
            tickers[code]["datePrec"] = date_prec

    fractionnements = detecter_fractionnements(precedent, all_cours, today, today_iso)

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "dateSeance": today if date_lue else None,
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
