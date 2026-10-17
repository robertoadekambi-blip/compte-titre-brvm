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
import calendar
import json
import os
import sys
from datetime import datetime, timedelta, timezone

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


def charger_fractionnements():
    """Fractionnements probables reperes par update_cours.py (liste de dicts)."""
    try:
        with open(COURS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [x for x in (data.get("fractionnements") or []) if isinstance(x, dict)]
    except Exception:
        return []


def fractionnement_en_attente(code, state, fractionnements):
    """Vrai si un fractionnement a ete repere sur ce titre mais pas encore confirme
    (ni ignore) dans l'app : les seuils de l'alerte sont alors sur l'ancienne
    echelle de prix, et la comparer au nouveau cours declencherait une fausse alerte."""
    confirmes = state.get("fractionnements") or []
    ignores = state.get("fractionnementsIgnores") or []
    for fr in fractionnements:
        if fr.get("code") != code:
            continue
        date_iso = fr.get("dateISO") or ""
        if (code + "|" + date_iso) in ignores:
            continue
        if any(c.get("code") == code and (c.get("dateISO") or "") >= date_iso for c in confirmes):
            continue
        return True
    return False


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


FUSEAU_UTILISATRICE = timezone(timedelta(hours=1))  # Benin (UTC+1), pas d'heure d'ete


def envoyer(token, titre, corps):
    """Envoie une notification simple ; renvoie True si elle est partie."""
    if not token:
        return False
    try:
        messaging.send(messaging.Message(
            token=token,
            notification=messaging.Notification(title=titre, body=corps),
            webpush=messaging.WebpushConfig(notification=messaging.WebpushNotification(title=titre, body=corps)),
        ))
        return True
    except Exception as e:
        print("ERREUR envoi notification :", e, file=sys.stderr)
        return False


def traiter_priorites(doc, data, state, cours_par_code, token, maintenant=None):
    """Onglet Priorites de l'app : rappel mensuel le jour choisi, et notification quand
    un titre suivi (qui remplit deja toutes les autres conditions) passe sous son prix
    maximum. Le calcul lui-meme est fait par l'app (state.priorites.calcul) ; le robot
    ne fait que comparer et prevenir. Suivi stocke hors de "state" (prioritesNotif)."""
    prio = state.get("priorites") or {}
    calc = prio.get("calcul") or {}
    notif = data.get("prioritesNotif") or {}
    maj = {}
    now = maintenant or datetime.now(FUSEAU_UTILISATRICE)
    try:
        jour = int(prio.get("jourNotif") or 25)
    except (TypeError, ValueError):
        jour = 25
    jour = max(1, min(jour, calendar.monthrange(now.year, now.month)[1]))
    mois = now.strftime("%Y-%m")
    if now.day == jour and notif.get("mois") != mois and prio:
        corps = "Priorite du mois : " + (calc.get("resume") or "ouvre l'onglet Priorites") + \
                ". Ouvre l'onglet Priorites pour le detail et verifie les derniers resultats avant d'acheter."
        if envoyer(token, "Priorites BRVM du mois", corps):
            maj["prioritesNotif.mois"] = mois
            print("Rappel mensuel envoye :", doc.id)
    candidats = calc.get("candidatsPrix") or {}
    deja = set(notif.get("achetables") or [])
    nouveaux = {c for c in deja if c in candidats}
    for code, info in candidats.items():
        cours = (cours_par_code.get(code) or {}).get("cours")
        pm = (info or {}).get("prixMax")
        if cours is None or not pm:
            continue
        if cours <= pm and code not in deja:
            corps = code + " est a " + str(cours) + " F CFA, sous ton prix maximum (" + str(pm) + \
                    " F CFA). Ouvre l'onglet Priorites pour voir s'il passe en tete."
            if envoyer(token, "Titre achetable — " + code, corps):
                nouveaux.add(code)
                print("Notification 'achetable' envoyee :", code, cours, "<=", pm)
        elif cours > pm * 1.02 and code in nouveaux:
            nouveaux.discard(code)  # repasse au-dessus : on previendra a nouveau la prochaine fois
    if nouveaux != deja:
        maj["prioritesNotif.achetables"] = sorted(nouveaux)
    if maj:
        doc.reference.update(maj)


def maintenant_iso():
    """Heure UTC au meme format que l'app (2026-10-17T19:00:05.123Z) : l'app compare
    cette date a celle du dernier rearmement de l'alerte pour garder la bonne version."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def traiter_utilisateur(db, doc, cours_par_code, fractionnements=None):
    fractionnements = fractionnements or []
    data = doc.to_dict() or {}
    state = data.get("state") or {}
    alertes = state.get("alertes") or []
    token = data.get("fcmToken")

    try:
        traiter_priorites(doc, data, state, cours_par_code, token)
    except Exception as e:
        print("ERREUR priorites pour", doc.id, ":", e, file=sys.stderr)

    if not alertes:
        return

    modifie = False
    for a in alertes:
        code = (a.get("code") or "").upper()
        cours_info = cours_par_code.get(code)
        if not cours_info or cours_info.get("cours") is None:
            continue
        if fractionnement_en_attente(code, state, fractionnements):
            print("Alerte", code, "mise en pause : fractionnement a confirmer dans l'app.")
            continue
        cours = cours_info["cours"]
        titre_aff = nom_affiche(code, a.get("titre"))

        seuil_haut = a.get("seuilHaut")
        if seuil_haut is not None and cours >= seuil_haut and not a.get("declencheHaut"):
            a["declencheHaut"] = True
            a["declencheLe"] = maintenant_iso()
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
            a["declencheLe"] = maintenant_iso()
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

    fractionnements = charger_fractionnements()
    db = init_firebase()
    users = db.collection("users").stream()
    nb = 0
    for doc in users:
        traiter_utilisateur(db, doc, cours_par_code, fractionnements)
        nb += 1
    print("Utilisateurs traites :", nb)


if __name__ == "__main__":
    main()
