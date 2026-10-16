"""
Lit le Bulletin Officiel de la Cote (BOC) publie chaque jour par la BRVM et ecrit
boc-auto.json a la racine du depot :

- "marche"   : PER moyen et taux de rendement moyen du marche
- "secteurs" : PER moyen de chaque secteur BRVM
- "titres"   : pour chaque societe, son PER du jour, son rendement net et son
               secteur officiel BRVM (code TEL, FIN, CB, ...)

Le PER publie par la BRVM = cours / benefice net par action (BNPA) ; le rendement
net = dividende net par action / cours. L'app s'en sert pour calculer
automatiquement le prix maximum des titres suivis avec la methode PER.

Si le bulletin est introuvable ou illisible, le fichier existant n'est pas
modifie et le script se termine sans erreur (le reste du robot continue).
Necessite le paquet pip "pypdf".
"""
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

OUTPUT_FILE = "boc-auto.json"
URLS = [
    "https://www.brvm.org/sites/default/files/boc_{d}_2.pdf",
    "https://bfin.brvm.org/boc/BOC_JOUR/BOC_{d}.pdf",
]
JOURS_EN_ARRIERE = 7
FUSEAU = timezone(timedelta(hours=1))

CODES = [
    "ABJC", "BBGC", "BICB", "BICC", "BNBC", "BOAB", "BOABF", "BOAC", "BOAM", "BOAN", "BOAS", "CABC",
    "CBIBF", "CFAC", "CIEC", "ECOC", "ETIT", "FTSC", "LNBB", "NEIC", "NSBC", "NTLC", "ONTBF", "ORAC",
    "ORGT", "PALC", "PRSC", "SAFC", "SCRC", "SDCC", "SDSC", "SEMC", "SGBC", "SHEC", "SIBC", "SICC",
    "SIVC", "SLBC", "SMBC", "SNTS", "SOGC", "SPHC", "STAC", "STBC", "TTLC", "TTLS", "UNLC", "UNXC",
]
# Code secteur BRVM (debut de ligne du tableau des actions) -> nom du secteur du tableau des indices
SECTEUR_DE_CODE = {
    "TEL": "TELECOMMUNICATIONS", "FIN": "SERVICES FINANCIERS", "CB": "CONSOMMATION DE BASE",
    "CD": "CONSOMMATION DISCRETIONNAIRE", "IND": "INDUSTRIELS", "ENE": "ENERGIE",
    "SPU": "SERVICES PUBLICS", "SP": "SERVICES PUBLICS",
}
NOMS_SECTEURS = sorted(set(SECTEUR_DE_CODE.values()), key=len, reverse=True)

NOMBRE = r"-?\d{1,3}(?:[  ]\d{3})*(?:,\d+)?"
DATE_FR = r"\d{1,2}-[a-zéèûô\.]+-\d{2}"
RE_LIGNE_TITRE = re.compile(r"(?<![A-Z])([A-Z]{2,4})\s+(" + "|".join(sorted(CODES, key=len, reverse=True)) + r")\s+(?=[A-Z0-9'])")
RE_FIN_DE_LIGNE = re.compile("(" + DATE_FR + r")\s+(" + NOMBRE + r")\s*%\s+(" + NOMBRE + r"|NS|ns|N/S)")
RE_PER_MARCHE = re.compile(r"PER moyen du march[ée]\s*(?:\(\*+\))?\s*(" + NOMBRE + ")")
RE_RDT_MARCHE = re.compile(r"Taux de rendement moyen du march[ée]\s*(?:\(\*+\))?\s*(" + NOMBRE + ")")


def nombre(txt):
    try:
        return float(txt.replace(" ", "").replace(" ", "").replace(",", "."))
    except (AttributeError, ValueError):
        return None


def analyser(texte):
    """Analyse le texte brut du bulletin. Renvoie (marche, secteurs, titres)."""
    lignes = [l.strip() for l in texte.splitlines()]
    plat = re.sub(r"\s+", " ", " ".join(lignes))

    marche = {}
    m = RE_PER_MARCHE.search(plat)
    if m:
        marche["per"] = nombre(m.group(1))
    m = RE_RDT_MARCHE.search(plat)
    if m:
        marche["rendement"] = nombre(m.group(1))

    secteurs = {}
    for ligne in lignes:
        if not ligne.upper().startswith("BRVM") or "%" not in ligne:
            continue
        haut = ligne.upper()
        nom = next((n for n in NOMS_SECTEURS if n in haut), None)
        if not nom or nom in secteurs:
            continue
        # Le PER est le dernier nombre de la ligne. Les milliers etant separes par des
        # espaces, on prend le dernier "mot" pour ne pas le coller au volume qui precede.
        dernier = ligne.split()[-1]
        if re.fullmatch(r"-?\d+(?:,\d+)?", dernier):
            secteurs[nom] = nombre(dernier)

    titres = {}
    debuts = list(RE_LIGNE_TITRE.finditer(plat))
    for i, d in enumerate(debuts):
        code_secteur, code = d.group(1), d.group(2)
        if code in titres:
            continue
        fin = debuts[i + 1].start() if i + 1 < len(debuts) else min(len(plat), d.end() + 400)
        segment = plat[d.end():fin]
        fins = list(RE_FIN_DE_LIGNE.finditer(segment))
        if not fins:
            continue
        f = fins[-1]
        per = nombre(f.group(3)) if f.group(3).upper() not in ("NS", "N/S") else None
        titres[code] = {
            "per": per,
            "rendementNet": nombre(f.group(2)),
            "secteurBrvm": SECTEUR_DE_CODE.get(code_secteur, code_secteur),
        }
    return marche, secteurs, titres


def telecharger(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; compte-titre-brvm-bot/1.0)"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read()


def texte_du_pdf(contenu):
    from pypdf import PdfReader
    lecteur = PdfReader(io.BytesIO(contenu))
    return "\n".join((page.extract_text() or "") for page in lecteur.pages)


def main():
    aujourd_hui = datetime.now(FUSEAU).date()
    for decalage in range(JOURS_EN_ARRIERE + 1):
        jour = aujourd_hui - timedelta(days=decalage)
        for modele in URLS:
            url = modele.format(d=jour.strftime("%Y%m%d"))
            try:
                contenu = telecharger(url)
            except Exception:
                continue
            if not contenu.startswith(b"%PDF"):
                continue
            try:
                marche, secteurs, titres = analyser(texte_du_pdf(contenu))
            except Exception as e:
                print("Bulletin illisible :", url, e, file=sys.stderr)
                continue
            if len(titres) < 20:
                print("Bulletin", url, ": seulement", len(titres), "titres reconnus, on ignore.", file=sys.stderr)
                continue
            sortie = {
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "dateBulletin": jour.isoformat(),
                "source": url,
                "marche": marche,
                "secteurs": secteurs,
                "titres": dict(sorted(titres.items())),
            }
            with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
                json.dump(sortie, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            print("Bulletin du", jour.isoformat(), ":", len(titres), "titres, PER marche", marche.get("per"),
                  ", rendement marche", marche.get("rendement"), ",", len(secteurs), "secteurs")
            manquants = [c for c in CODES if c not in titres]
            if manquants:
                print("Titres sans PER dans ce bulletin :", ", ".join(manquants))
            return
    print("Aucun bulletin BRVM lisible sur les", JOURS_EN_ARRIERE + 1, "derniers jours : boc-auto.json inchange.", file=sys.stderr)


if __name__ == "__main__":
    main()
