"""
Recupere le calendrier officiel des paiements de dividendes publie par la BRVM
(page "Paiement de dividendes") et ecrit dividendes-auto.json a la racine du
depot. Concu pour tourner via GitHub Actions, une fois par jour, juste apres
update_cours.py.

Le fichier est indexe par CODE BRVM (comme cours-auto.json), pas par le nom
que l'utilisatrice donne a ses titres dans l'app : c'est l'app qui fait le
lien entre le nom qu'elle utilise et le code correspondant.

Les dividendes ne sont PAS fusionnes automatiquement dans les donnees de
l'app : ce fichier ne fait que lister ce que la BRVM a publie. C'est l'app
qui propose ensuite, a l'utilisatrice, d'ajouter chaque nouveau dividende
d'un simple tap (ou de l'ignorer / le saisir autrement).

Limites connues :
- On ne lit que les N premieres pages du tableau (les plus recentes),
  pas tout l'historique.
- Le tableau officiel utilise le nom complet (ou parfois abrege) de la
  societe, pas toujours son code BRVM : NOM_MAP fait la correspondance,
  construite et verifiee au fil de l'eau. Un emetteur non reconnu est
  liste tel quel dans "non_reconnus" plutot que d'etre ignore silencieusement.
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE_URL = "https://www.brvm.org/fr/esv/paiement-de-dividendes"
PAGES_TO_READ = 10  # les ~10 pages les plus recentes (~2 ans de publications)
OUTPUT_FILE = "dividendes-auto.json"

# Nom de l'emetteur tel qu'il peut apparaitre sur brvm.org -> code BRVM (ticker).
# Compare apres normalisation (majuscules, accents et apostrophes retires,
# espaces multiples reduits). Plusieurs variantes par societe car le nom
# exact utilise a pu changer au fil des annees (ex: "SGB CI" -> "SOCIETE
# GENERALE CI").
NOM_MAP = {
    # Services financiers
    "BANQUE INTERNATIONALE POUR L'INDUSTRIE ET LE COMMERCE DU BENIN": "BICB",
    "BIIC BENIN": "BICB", "BIIC": "BICB",
    "BICI CI": "BICC", "BICI COTE D'IVOIRE": "BICC",
    "BANK OF AFRICA BN": "BOAB", "BANK OF AFRICA BENIN": "BOAB",
    "BANK OF AFRICA BF": "BOABF", "BANK OF AFRICA BURKINA FASO": "BOABF",
    "BANK OF AFRICA CI": "BOAC", "BANK OF AFRICA COTE D'IVOIRE": "BOAC",
    "BANK OF AFRICA ML": "BOAM", "BANK OF AFRICA MALI": "BOAM",
    "BANK OF AFRICA NG": "BOAN", "BANK OF AFRICA NIGER": "BOAN",
    "BANK OF AFRICA SN": "BOAS", "BANK OF AFRICA SENEGAL": "BOAS",
    "CORIS BANK INTERNATIONAL": "CBIBF", "CORIS BANK INTERNATIONAL BURKINA FASO": "CBIBF",
    "ECOBANK CI": "ECOC", "ECOBANK COTE D'IVOIRE": "ECOC",
    "ECOBANK TRANSNATIONAL INCORPORATED": "ETIT", "ETI": "ETIT", "ECOBANK TG": "ETIT",
    "NSIA BANQUE": "NSBC", "NSIA BANQUE CI": "NSBC", "NSIA BANQUE COTE D'IVOIRE": "NSBC", "NSBC": "NSBC",
    "ORAGROUP": "ORGT", "ORAGROUP TOGO": "ORGT", "ORAGROUP SA": "ORGT", "ORAGROUP TG": "ORGT",
    "SAFCA": "SAFC", "SAFCA CI": "SAFC", "SAFCA COTE D'IVOIRE": "SAFC",
    "SOCIETE GENERALE CI": "SGBC", "SGB CI": "SGBC", "SGCI": "SGBC",
    "SIB": "SIBC", "SOCIETE IVOIRIENNE DE BANQUE": "SIBC",
    # Consommation de base
    "NESTLE CI": "NTLC", "NESTLE COTE D'IVOIRE": "NTLC",
    "PALM CI": "PALC", "PALMCI": "PALC",
    "SUCRIVOIRE": "SCRC", "SUCRIVOIRE CI": "SCRC",
    "SICOR": "SICC", "SICOR CI": "SICC", "SICOR COTE D'IVOIRE": "SICC",
    "SOLIBRA": "SLBC", "SOLIBRA CI": "SLBC",
    "SOGB": "SOGC", "SOGB CI": "SOGC", "SOGB COTE D'IVOIRE": "SOGC",
    "SAPH CI": "SPHC", "SAPH COTE D'IVOIRE": "SPHC",
    "SITAB": "STBC", "SITAB CI": "STBC",
    "UNILEVER CI": "UNLC", "UNILEVER COTE D'IVOIRE": "UNLC",
    # Consommation discretionnaire
    "SERVAIR ABIDJAN": "ABJC", "SERVAIR ABIDJAN CI": "ABJC",
    "BERNABE": "BNBC", "BERNABE CI": "BNBC",
    "CFAO MOTORS CI": "CFAC", "CFAO MOTORS COTE D'IVOIRE": "CFAC",
    "LNB": "LNBB", "LOTERIE NATIONALE DU BENIN": "LNBB",
    "NEI-CEDA CI": "NEIC", "NEI CEDA CI": "NEIC",
    "TRACTAFRIC MOTORS": "PRSC", "TRACTAFRIC MOTORS CI": "PRSC", "TRACTAFRIC CI": "PRSC",
    "UNIWAX": "UNXC", "UNIWAX CI": "UNXC",
    # Industriels
    "SICABLE": "CABC", "SICABLE CI": "CABC",
    "FILTISAC": "FTSC", "FILTISAC CI": "FTSC",
    "BOLLORE TRANSPORT & LOGISTICS": "SDSC", "AFRICA GLOBAL LOGISTICS": "SDSC",
    "AFRICA GLOBAL LOGISTICS CI": "SDSC", "AGL CI": "SDSC",
    "EVIOSYS PACKAGING SIEM CI": "SEMC", "CROWN SIEM CI": "SEMC",
    "ERIUM CI": "SIVC", "SIVOA CI": "SIVC",
    "SETAO": "STAC", "SETAO CI": "STAC",
    # Energie
    "VIVO ENERGY CI": "SHEC", "VIVO ENERGY COTE D'IVOIRE": "SHEC",
    "SMB": "SMBC", "SMB CI": "SMBC",
    "TOTAL": "TTLC", "TOTAL CI": "TTLC", "TOTALENERGIES MARKETING CI": "TTLC",
    "TOTAL SENEGAL": "TTLS", "TOTAL SN": "TTLS", "TOTALENERGIES MARKETING SENEGAL": "TTLS",
    "TOTAL SENEGAL S.A.": "TTLS", "TOTAL SENEGAL SA": "TTLS",
    # Telecommunications
    "ONATEL BF": "ONTBF", "ONATEL BURKINA FASO": "ONTBF",
    "ORANGE CI": "ORAC", "ORANGE COTE D'IVOIRE": "ORAC",
    "SONATEL": "SNTS", "SONATEL SENEGAL": "SNTS", "SONATEL SN": "SNTS",
    # Services publics
    "CIE CI": "CIEC", "CIE COTE D'IVOIRE": "CIEC",
    "SODECI": "SDCC", "SODE CI": "SDCC",
}

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
}


def normalize_name(s):
    s = (s or "").strip().upper()
    s = s.replace("’", "'")
    s = re.sub(r"[^A-Z0-9' ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


NOM_MAP_NORM = {normalize_name(k): v for k, v in NOM_MAP.items()}


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; compte-titre-brvm-bot/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_french_date(s):
    """'20 mai 2025' -> '2025-05-20'. Retourne None si non reconnu."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s+([A-Za-zéû]+)\s+(\d{4})", s.strip())
    if not m:
        return None
    day, mois_txt, year = m.groups()
    mois = MOIS.get(mois_txt.lower())
    if not mois:
        return None
    return "%04d-%02d-%02d" % (int(year), mois, int(day))


def parse_montant(s):
    """'254,6 FCFA' / 'XOF 209,25' / '1 655 FCFA' / '2 771,41' -> float. None si vide."""
    if not s:
        return None
    s = s.replace("XOF", "").replace("FCFA", "").replace("F CFA", "").strip()
    s = s.replace(" ", "").replace("\xa0", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


ROW_TAG_PATTERN = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL_TAG_PATTERN = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.I)
YEAR_PATTERN = re.compile(r"^(19|20)\d{2}$")
AMOUNT_HINT_PATTERN = re.compile(r"FCFA|XOF", re.I)
FRENCH_DATE_PATTERN = re.compile(
    r"\d{1,2}\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\s+\d{4}",
    re.I,
)


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#039;", "'").replace("&#39;", "'")
    return re.sub(r"\s+", " ", s).strip()


def parse_page(html):
    """Analyse independante de tout repere textuel ou de mise en page : on
    parcourt CHAQUE <tr> de la page entiere, on en extrait les cellules
    (<td> ou <th>), et on ne retient que celles qui ressemblent vraiment a
    une ligne de paiement de dividende (une annee 4 chiffres, un montant en
    FCFA/XOF, et au moins une date en francais parmi les cellules). Cette
    approche reste valable meme si la mise en page exacte du tableau change,
    et ignore naturellement les autres tableaux de la page (cours du jour,
    Top 5 / Flop 5, indices)."""
    rows = []
    for tr_match in ROW_TAG_PATTERN.finditer(html):
        raw_cells = CELL_TAG_PATTERN.findall(tr_match.group(1))
        if len(raw_cells) < 6:
            continue
        cells = [strip_tags(c) for c in raw_cells]
        year_idx = next((i for i, c in enumerate(cells) if YEAR_PATTERN.match(c)), None)
        if year_idx is None:
            continue
        joined = " ".join(cells)
        if not AMOUNT_HINT_PATTERN.search(joined):
            continue
        dates = [c for c in cells if FRENCH_DATE_PATTERN.search(c)]
        if len(dates) < 2:
            continue
        emetteur = cells[0] if year_idx > 0 else ""
        if not emetteur:
            continue
        montant_cell = next((c for c in cells if AMOUNT_HINT_PATTERN.search(c)), "")
        if not montant_cell:
            continue
        rows.append({
            "emetteur": emetteur,
            "exercice": int(cells[year_idx]),
            "datePaiement": dates[0],
            "dateExDividende": dates[1] if len(dates) > 1 else dates[0],
            "montantBrut": montant_cell,
        })
    return rows


def main():
    all_rows = []
    for page in range(PAGES_TO_READ):
        url = BASE_URL if page == 0 else BASE_URL + "?page=" + str(page)
        try:
            html = fetch_html(url)
        except Exception as e:
            print("Avertissement : page", page, "non recuperee :", e, file=sys.stderr)
            continue
        base_rows = parse_page(html)
        all_rows.extend(base_rows)
        time.sleep(0.3)

    tickers = {}
    non_reconnus = []
    seen = set()
    for row in all_rows:
        date_ex = parse_french_date(row["dateExDividende"])
        date_pay = parse_french_date(row["datePaiement"])
        montant = parse_montant(row.get("montantBrut"))
        if montant is None or date_ex is None:
            continue
        key_dedup = (row["emetteur"], row["exercice"], date_ex, montant)
        if key_dedup in seen:
            continue
        seen.add(key_dedup)

        code = NOM_MAP_NORM.get(normalize_name(row["emetteur"]))
        entry = {
            "dateExDividende": date_ex,
            "datePaiement": date_pay,
            "exercice": row["exercice"],
            "montant": montant,
        }
        if code:
            tickers.setdefault(code, []).append(entry)
        else:
            entry["emetteur"] = row["emetteur"]
            non_reconnus.append(entry)

    if not tickers and not non_reconnus:
        print("ERREUR : aucune ligne de dividende n'a pu etre extraite, on n'ecrase pas le fichier existant.", file=sys.stderr)
        sys.exit(1)

    for code in tickers:
        tickers[code].sort(key=lambda e: e["dateExDividende"])

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": BASE_URL,
        "tickers": tickers,
        "non_reconnus": non_reconnus,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Codes reconnus :", sorted(tickers.keys()))
    print("Lignes non reconnues :", len(non_reconnus))


if __name__ == "__main__":
    main()
