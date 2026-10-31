"""
Copie les donnees de marche lues par le robot (cours, dividendes, bulletin) dans
Firebase (Firestore), collection "donnees", pour que l'app puisse les lire sans
qu'elles soient publiees dans le depot GitHub.

Usage :
  python3 scripts/sync_donnees.py publier    -> fichiers .json du depot  ->  Firestore
  python3 scripts/sync_donnees.py recuperer  -> Firestore  ->  fichiers .json (pour le robot)

Chaque fichier est range tel quel (texte JSON) dans un document :
  donnees/cours, donnees/dividendes, donnees/bulletin
Ces documents sont ecrits avec la cle de service (secret GitHub
FIREBASE_SERVICE_ACCOUNT) ; l'app ne peut que les lire, une fois connectee.
"""
import json
import os
import sys
from datetime import datetime, timezone

COLLECTION = "donnees"
FICHIERS = {
    "cours": "cours-auto.json",
    "dividendes": "dividendes-auto.json",
    "bulletin": "boc-auto.json",
}


def init_firestore():
    import firebase_admin
    from firebase_admin import credentials, firestore
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if not raw:
        print("ERREUR : variable FIREBASE_SERVICE_ACCOUNT absente.", file=sys.stderr)
        sys.exit(1)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)))
    return firestore.client()


def publier(db):
    erreurs = 0
    for doc_id, fichier in FICHIERS.items():
        if not os.path.exists(fichier):
            print("Absent, ignore :", fichier)
            continue
        try:
            with open(fichier, encoding="utf-8") as f:
                texte = f.read()
            json.loads(texte)  # on ne publie jamais un fichier abime
        except Exception as e:
            print("ERREUR lecture", fichier, ":", e, file=sys.stderr)
            erreurs += 1
            continue
        db.collection(COLLECTION).document(doc_id).set({
            "json": texte,
            "copieLe": datetime.now(timezone.utc).isoformat(),
        })
        print("Copie dans Firebase :", fichier, "->", COLLECTION + "/" + doc_id, "(", len(texte), "caracteres )")
    return erreurs


def recuperer(db):
    for doc_id, fichier in FICHIERS.items():
        snap = db.collection(COLLECTION).document(doc_id).get()
        data = snap.to_dict() if snap.exists else None
        if not data or not data.get("json"):
            print("Rien dans Firebase pour", doc_id, ": fichier", fichier, "non cree")
            continue
        with open(fichier, "w", encoding="utf-8") as f:
            f.write(data["json"])
        print("Recupere depuis Firebase :", COLLECTION + "/" + doc_id, "->", fichier)
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("publier", "recuperer"):
        print("Usage : sync_donnees.py publier|recuperer", file=sys.stderr)
        sys.exit(2)
    db = init_firestore()
    erreurs = publier(db) if mode == "publier" else recuperer(db)
    sys.exit(1 if erreurs else 0)


if __name__ == "__main__":
    main()
