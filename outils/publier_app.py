"""Publie la galerie Équilibre dans l'app web de Cardigan, après le push de GitHub Pages.

La tâche du matin le lance une fois Pages en ligne. Il envoie à l'app les fichiers exacts
que Pages sert (index.html, annonces.json, donnees.bin, les médias nouveaux), puis vérifie
que l'app et Pages servent la même chose, octet pour octet.

    python3 -I outils/publier_app.py              # publier, puis vérifier contre Pages
    python3 -I outils/publier_app.py --verifier   # vérifier seulement

Réglages hors dépôt (le dépôt est public) :
    ~/.config/visuels/app.url     l'adresse de l'app, une ligne
    ~/.config/visuels/app.jeton   le jeton de publication, une ligne (le même que dans l'app)

Code 0 : « APP À JOUR » (ou « APP SAUTÉE » : réglages absents, Pages seul est publié).
Code 4 : « APP PAS À JOUR » : Pages est à jour, l'app ne l'est pas. Ne jamais annuler Pages pour ça.
Le jeton et la clé des chiffres partent dans les requêtes (HTTPS), jamais à l'écran.
"""

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
CLIENT = "equilibre"
RACINE = ICI.parent / CLIENT
REGLAGES = Path.home() / ".config" / "visuels"
CLE = REGLAGES / f"{CLIENT}.cle"                  # la même que construire_equilibre.py
PAGES = f"https://coldkendama.github.io/visuels/{CLIENT}/"
FICHIERS = ("index.html", "annonces.json", "donnees.bin")
AGENT = "visuels-publier-app/1"


class Echec(Exception):
    pass


def stop(code, *lignes):
    print("\n".join(l for l in lignes if l))
    sys.exit(code)


def sha(octets):
    return hashlib.sha256(octets).hexdigest()


def requete(methode, url, jeton=None, corps=None, entetes=None, essais=3):
    """Un appel HTTP ; réessaie deux fois une coupure ou une erreur 5xx (l'app dort parfois)."""
    for essai in range(1, essais + 1):
        req = urllib.request.Request(url, data=corps, method=methode)
        req.add_header("User-Agent", AGENT)
        req.add_header("Accept", "application/json")
        if jeton:
            req.add_header("Authorization", f"Bearer {jeton}")
        for k, v in (entetes or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:800].decode("utf-8", "replace")
            if e.code < 500 or essai == essais:
                raise Echec(f"{methode} {urllib.parse.urlsplit(url).path} : HTTP {e.code} {detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if essai == essais:
                raise Echec(f"{methode} {urllib.parse.urlsplit(url).path} : {e}")
        time.sleep(5 * essai)


def api(methode, url, jeton, donnees=None, brut=None, entetes=None):
    if donnees is not None:
        brut = json.dumps(donnees).encode()
        entetes = {"Content-Type": "application/json", **(entetes or {})}
    reponse = requete(methode, url, jeton, brut, entetes)
    try:
        return json.loads(reponse or b"{}")
    except json.JSONDecodeError:
        raise Echec(f"{methode} {urllib.parse.urlsplit(url).path} : réponse qui n'est pas du JSON "
                    "(redirection vers la connexion ?)")


def lire_reglage(chemin, nom):
    p = Path(chemin).expanduser()
    if not p.exists():
        stop(0, f"APP SAUTÉE : {p} manque ({nom}). GitHub Pages seul est publié.")
    valeur = p.read_text().strip()
    if not valeur:
        stop(4, f"APP PAS À JOUR : {p} est vide ({nom}).")
    return valeur


def medias_locaux():
    """Tous les médias du dossier de Pages, au chemin que la page leur donne."""
    chemins = {}
    if (RACINE / "logo.png").is_file():
        chemins["logo.png"] = RACINE / "logo.png"
    for dossier in ("images", "videos"):
        for f in sorted((RACINE / dossier).rglob("*")):
            if f.is_file() and not f.name.startswith("."):
                chemins[f.relative_to(RACINE).as_posix()] = f
    return chemins


def publier(base, jeton, source):
    medias = medias_locaux()
    empreintes = {c: sha(f.read_bytes()) for c, f in medias.items()}
    manquants = api("POST", f"{base}/medias/manquants", jeton, {"medias": empreintes})["manquants"]
    for chemin in manquants:
        api("PUT", f"{base}/medias/{urllib.parse.quote(chemin)}", jeton, brut=medias[chemin].read_bytes(),
            entetes={"Content-Type": "application/octet-stream", "X-Sha256": empreintes[chemin]})

    page, annonces, donnees = ((RACINE / f).read_bytes() for f in FICHIERS)
    cle = base64.urlsafe_b64encode(bytes.fromhex(CLE.read_text().strip())).decode().rstrip("=")
    recu = api("POST", f"{base}/tirages", jeton, {
        "page": page.decode("utf-8"), "annonces": annonces.decode("utf-8"),
        "donnees": base64.b64encode(donnees).decode(), "cle": cle, "source": source})
    attendu = {"page": sha(page), "annonces": sha(annonces), "donnees": sha(donnees)}
    if recu.get("sha") != attendu:
        raise Echec("l'app n'a pas reçu les fichiers tels quels (empreintes différentes).")
    return recu, len(manquants), len(medias)


def verifier(base, jeton):
    """Compare l'app et GitHub Pages en ligne, fichier par fichier. Renvoie la liste des écarts."""
    app = api("GET", f"{base}/tirages/dernier", jeton)
    nc = secrets.token_hex(4)
    pages = {
        "page": sha(requete("GET", f"{PAGES}?nc={nc}")),
        "annonces": sha(requete("GET", f"{PAGES}annonces.json?nc={nc}")),
        "donnees": sha(requete("GET", f"{PAGES}donnees.bin?nc={nc}")),
    }
    ecarts = [nom for nom, s in pages.items() if app["sha"].get(nom) != s]
    return app, ecarts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verifier", action="store_true", help="comparer l'app et Pages sans rien publier")
    p.add_argument("--app", help="adresse de l'app (sinon ~/.config/visuels/app.url)")
    p.add_argument("--jeton", default=str(REGLAGES / "app.jeton"), help="fichier du jeton")
    p.add_argument("--source", default="tirage_equilibre")
    a = p.parse_args()

    adresse = a.app or lire_reglage(REGLAGES / "app.url", "l'adresse de l'app")
    jeton = lire_reglage(a.jeton, "le jeton de publication")
    base = f"{adresse.rstrip('/')}/api/clients/{CLIENT}"
    if not a.verifier and not CLE.exists():
        stop(4, f"APP PAS À JOUR : la clé des chiffres manque ({CLE}).")

    try:
        if not a.verifier:
            recu, envoyes, total = publier(base, jeton, a.source)
            print(f"Tirage {recu['id']} reçu par l'app : mise à jour du {recu['mise_a_jour']}, chiffres jusqu'au "
                  f"{recu['fin']}, {recu['nb_annonces']} annonces, {envoyes} média(s) envoyé(s) sur {total}.")
        app, ecarts = verifier(base, jeton)
    except Echec as e:
        stop(4, f"APP PAS À JOUR : {e}")

    if ecarts:
        stop(4, f"APP PAS À JOUR : l'app (tirage {app['id']} du {app['mise_a_jour']}) et GitHub Pages "
                f"diffèrent sur : {', '.join(ecarts)}.")
    print(f"APP À JOUR : tirage {app['id']} du {app['mise_a_jour']}, identique à GitHub Pages "
          f"(page, annonces.json, donnees.bin), {app['medias']} médias dans l'app.")


if __name__ == "__main__":
    main()
