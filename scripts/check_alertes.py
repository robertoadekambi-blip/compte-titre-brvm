"""
Verifie les alertes de prix de chaque utilisateur (stockees dans Firestore,
sous state.alertes) par rapport aux cours du jour (cours-auto.json, deja
regenere par update_cours.py dans la meme execution), et envoie une
notification push (Firebase Cloud Messaging) a chaque alerte franchie.

Une alerte franchie est marquee comme telle dans Firestore (declencheHaut /
declencheBas) pour ne jamais se redeclencher tant que l'utilisatrice ne l'a
pas reouverte et reenregistree dans l'app (ce qui la reamme).

Necessite le paquet pip "firebase-admin" et une variable d'environnement
FIREBASE_SERVICE_ACCOUNT contenant le JSON complet de la cle de compte de
service (jamais commite dans le depot : fournie via un secret GitHub Actions).
"""
import json
import os
import sys

import firebase_admin
from firebase_admin import credentials, firestore, messaging

COURS_FILE = "cours-auto.json"


def charger_cours():
    try:
        with open(COURS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("tickers", {})
    except Exception as e:
        print("ERREUR : impossible de lire", COURS_FILE, ":", e, file=sys.stderr)
        return {}


def init_firebase():
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if not raw:
        print("ERREUR : variable FIREBASE_SERVICE_ACCOUNT absente.", file=sys.stderr)
        sys.exit(1)
    cred = credentials.Certificate(json.loads(raw))
    firebase_admin.initialize_app(cred)
    return firestore.client()


def nom_affiche(code, titre_stocke):
    return titre_stocke or code


def construire_message(token, code, titre, cours, seuil, sens):
    verbe = "a dépassé" if sens == "haut" else "est descendu à"
    titre_notif = "Alerte BRVM — " + (titre or code)
    corps = (titre or code) + " " + verbe + " " + str(cours) + " F CFA (seuil : " + str(seuil) + " F CFA)."
    return messaging.Message(
        token=token,
        notification=messaging.Notification(title=titre_notif, body=corps),
        webpush=messaging.WebpushConfig(
            notification=messaging.WebpushNotification(title=titre_notif, body=corps)
        ),
    )


def traiter_utilisateur(db, doc, cours_par_code):
    data = doc.to_dict() or {}
    state = data.get("state") or {}
    alertes = state.get("alertes") or []
    token = data.get("fcmToken")

    if not alertes:
        return

    modifie = False
    for a in alertes:
        code = (a.get("code") or "").upper()
        cours_info = cours_par_code.get(code)
        if not cours_info or cours_info.get("cours") is None:
            continue
        cours = cours_info["cours"]
        titre_aff = nom_affiche(code, a.get("titre"))

        seuil_haut = a.get("seuilHaut")
        if seuil_haut is not None and cours >= seuil_haut and not a.get("declencheHaut"):
            a["declencheHaut"] = True
            modifie = True
            if token:
                try:
                    messaging.send(construire_message(token, code, titre_aff, cours, seuil_haut, "haut"))
                    print("Notification envoyee (haut) :", code, cours, ">=", seuil_haut)
                except Exception as e:
                    print("ERREUR envoi notification (haut) pour", code, ":", e, file=sys.stderr)

        seuil_bas = a.get("seuilBas")
        if seuil_bas is not None and cours <= seuil_bas and not a.get("declencheBas"):
            a["declencheBas"] = True
            modifie = True
            if token:
                try:
                    messaging.send(construire_message(token, code, titre_aff, cours, seuil_bas, "bas"))
                    print("Notification envoyee (bas) :", code, cours, "<=", seuil_bas)
                except Exception as e:
                    print("ERREUR envoi notification (bas) pour", code, ":", e, file=sys.stderr)

    if modifie:
        doc.reference.update({"state.alertes": alertes})
        print("Alertes mises a jour pour l'utilisateur", doc.id)


def main():
    cours_par_code = charger_cours()
    if not cours_par_code:
        print("Pas de cours disponibles, on arrete ici sans erreur.", file=sys.stderr)
        return

    db = init_firebase()
    users = db.collection("users").stream()
    nb = 0
    for doc in users:
        traiter_utilisateur(db, doc, cours_par_code)
        nb += 1
    print("Utilisateurs traites :", nb)


if __name__ == "__main__":
    main()
