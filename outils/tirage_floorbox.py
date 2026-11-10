"""Mise à jour quotidienne de la galerie FloorBox : dit quoi tirer par Markifact, puis construit.

Même principe que tirage_equilibre.py : les annonces et les images déjà vues restent en cache
(~/.cache/visuels/floorbox/), et chaque jour il ne faut tirer, pour chaque compte (CA et US),
que les annonces actives, le rapport, et ce qui est nouveau. On relance le script après chaque
tirage ; il dit la prochaine chose à tirer (code 2), ou construit la galerie quand tout y est
(code 0). Code 3 : un problème qui demande un humain.

    python3 -I outils/tirage_floorbox.py

Fichiers que le tirage dépose dans le dossier du jour (noms exacts, x = ca ou us) :
    x_actives.json          meta_ads_list_ads, annonces actives
    x_perf.json             meta_ads_get_report, du 2026-09-28 à la veille (avec purchases)
    x_soum.json             meta_ads_get_graph_data, demandes de soumission par annonce et par jour
    x_historiques_*.json    meta_ads_list_ads des identifiants demandés
    x_medias_*.json         meta_ads_get_media_details des hashes demandés
"""

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("floorbox", ICI / "construire_floorbox.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

CACHE = Path.home() / ".cache" / "visuels" / "floorbox"
CONNEXION = "63ab1d5f-e045-49f8-9f53-00779cad1271"   # Meta par chrystopher_c.a@hotmail.fr, la seule qui voit FloorBox
COMPTES = {"CA": "act_681027176176924", "US": "act_1418004975723866"}
DEPUIS = "2026-09-28"      # annonces montrées : créées depuis cette date (les plus anciennes ne sont pas de Cardigan)
STATUTS = ["ACTIVE", "PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED", "ARCHIVED", "WITH_ISSUES", "DELETED",
           "DISAPPROVED", "PENDING_REVIEW", "IN_PROCESS"]


def lire(p, defaut):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else defaut


def ecrire(p, d):
    Path(p).write_text(json.dumps(d, ensure_ascii=False))


def stop(code, *lignes):
    print("\n".join(l for l in lignes if l))
    sys.exit(code)


def entree(op, donnees):
    return f"  {op} : {json.dumps(donnees, ensure_ascii=False)}"


def images_de(fichier):
    """Les images d'un fichier de médias : get_media_details ({"images": [...]}) ou list_media ([...])."""
    d = lire(fichier, [])
    liste = d.get("images") or [] if isinstance(d, dict) else d
    return [{**i, "hash": i.get("hash") or i.get("image_hash")} for i in liste if i.get("hash") or i.get("image_hash")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=date.today().isoformat())
    args = p.parse_args()
    veille = (date.fromisoformat(args.date) - timedelta(days=1)).isoformat()
    if not F.CLE.exists():
        stop(3, f"PROBLÈME : la clé {F.CLE} manque. Une nouvelle clé casserait le lien déjà envoyé : rien de fait.")
    travail = CACHE / f"tirage-{args.date}"
    travail.mkdir(parents=True, exist_ok=True)
    print(f"Dossier du jour : {travail}")

    # 1. Les tirages de base, par compte.
    demandes = []
    for pays, compte in COMPTES.items():
        x = pays.lower()
        if not (travail / f"{x}_actives.json").exists():
            demandes.append(entree(f"meta_ads_list_ads → {x}_actives.json", {
                "connection_id": CONNEXION, "account": compte, "ad_effective_status": ["ACTIVE"],
                "include_creative": True, "limit": 1000}))
        pf = lire(travail / f"{x}_perf.json", None)
        if not (isinstance(pf, list) and pf and "purchases" in pf[0]):   # absent, ou tiré sans purchases
            demandes.append(entree(f"meta_ads_get_report → {x}_perf.json", {
                "connection_id": CONNEXION, "accounts": [compte],
                "date_range": {"preset": "FIXED", "start": DEPUIS, "end": veille},
                "dimensions": ["date", "campaignId", "campaignName", "optimizationGoal", "adsetId", "adsetName",
                               "adId", "adName"],
                "metrics": ["cost", "impressions", "linkClicks", "results", "purchases"],
                "filters": [{"field": "impressions", "operator": "GREATER_THAN", "value": "0"}],
                "limit": 20000}))
        if not (travail / f"{x}_soum.json").exists():
            filtre = json.dumps([{"field": "action_type", "operator": "IN", "value": [F.SOUMISSION]}], separators=(",", ":"))
            plage = json.dumps({"since": DEPUIS, "until": veille}, separators=(",", ":"))
            demandes.append(entree(f"meta_ads_get_graph_data → {x}_soum.json", {
                "connection_id": CONNEXION, "account": compte,
                "path": f"{compte}/insights?level=ad&fields=ad_id,conversions&time_increment=1&limit=5000"
                        f"&filtering={filtre}&time_range={plage}"}))
    if demandes:
        stop(2, "À TIRER (gros résultats : get_file_url puis curl -o dans le dossier du jour) :", *demandes)

    # 2. Le cache, enrichi de ce qui a été tiré aujourd'hui.
    annonces = lire(CACHE / "annonces.json", {})
    medias = lire(CACHE / "medias.json", {"CA": {}, "US": {}})
    actives, perf = {}, {}
    for pays in COMPTES:
        x = pays.lower()
        actives[pays] = lire(travail / f"{x}_actives.json", [])
        perf[pays] = lire(travail / f"{x}_perf.json", [])
        if not isinstance(actives[pays], list) or not isinstance(perf[pays], list) or not perf[pays]:
            stop(3, f"PROBLÈME : {x}_actives.json ou {x}_perf.json n'est pas une liste (ou le rapport est vide).")
        fin = max(r["date"] for r in perf[pays])
        if fin != veille:
            stop(3, f"PROBLÈME : le rapport {pays} s'arrête au {fin}, pas à la veille ({veille}). Rien de construit.")
        if len(perf[pays]) >= 20000:
            stop(3, f"PROBLÈME : le rapport {pays} touche la limite de 20 000 lignes.")
        soum = lire(travail / f"{x}_soum.json", {})
        lignes_soum = soum.get("data") if isinstance(soum, dict) else None
        if not isinstance(lignes_soum, list) or not lignes_soum:
            stop(3, f"PROBLÈME : {x}_soum.json n'a pas de liste « data » (réponse de Graph attendue).")
        if (soum.get("paging") or {}).get("next") or len(lignes_soum) >= 5000:
            stop(3, f"PROBLÈME : {x}_soum.json a une page suivante ; il manquerait des demandes de soumission.")
        if max(r["date_start"] for r in lignes_soum) != veille:
            stop(3, f"PROBLÈME : les soumissions {pays} s'arrêtent au {max(r['date_start'] for r in lignes_soum)}, "
                    f"pas à la veille ({veille}). Rien de construit.")
        for f in [travail / f"{x}_actives.json"] + sorted(travail.glob(f"{x}_historiques*.json")):
            for a in lire(f, []):
                annonces[a["id"]] = {**a, "_pays": pays, "_tire": args.date}
        for f in sorted(travail.glob(f"{x}_medias*.json")):
            for i in images_de(f):
                medias[pays][i["hash"]] = {**i, "_tire": args.date}
    CACHE.mkdir(parents=True, exist_ok=True)
    ecrire(CACHE / "annonces.json", annonces)
    ecrire(CACHE / "medias.json", medias)

    # 3. Les annonces du rapport qui ne sont plus actives et pas encore en cache.
    historiques, demandes = {}, []
    for pays, compte in COMPTES.items():
        ids_actifs = {a["id"] for a in actives[pays]}
        historiques[pays] = sorted({r["adId"] for r in perf[pays] if r["impressions"]} - ids_actifs)
        a_tirer = [i for i in historiques[pays] if i not in annonces]
        for n, k in enumerate(range(0, len(a_tirer), 150), 1):
            demandes.append(entree(f"meta_ads_list_ads → {pays.lower()}_historiques_{n}.json", {
                "connection_id": CONNEXION, "account": compte, "ad_effective_status": STATUTS,
                "filters": [{"field": "ad_id", "operator": "IN_LIST", "value": ",".join(a_tirer[k:k + 150])}],
                "include_creative": True, "limit": 500}))
    if demandes:
        stop(2, "À TIRER : annonces qui ont livré mais ne sont pas en cache :", *demandes)

    # 4. Les images des annonces montrées : détails manquants, et liens frais pour tout fichier à télécharger.
    demandes, attendues = [], 0
    for pays, compte in COMPTES.items():
        livrees = {r["adId"] for r in perf[pays] if r["impressions"]}
        montrer = [a for a in actives[pays] if a["created_time"][:10] >= DEPUIS]
        montrer += [annonces[i] for i in historiques[pays] if annonces[i]["created_time"][:10] >= DEPUIS and i in livrees]
        manquants = set()
        for a in montrer:
            hs = F.hashes_annonce(a)
            manquants |= {h for h in hs if h not in medias[pays]}
            candidats = [medias[pays][h] for h in hs if h in medias[pays]]
            if a["effective_status"] == "ACTIVE" and a in actives[pays] and hs:
                attendues += 1
            if candidats and not manquants & set(hs):
                img = F.E.image_principale(candidats, a["name"])
                if not (F.IMAGES / f"{img['hash']}.jpg").exists() and img.get("_tire") != args.date:
                    manquants.add(img["hash"])
        h = sorted(manquants)
        for n, k in enumerate(range(0, len(h), 60), 1):
            demandes.append(entree(f"meta_ads_get_media_details → {pays.lower()}_medias_{n}.json",
                                   {"connection_id": CONNEXION, "account": compte, "image_hashes": h[k:k + 60]}))
    if demandes:
        stop(2, "À TIRER : détails d'images (un petit résultat revient en ligne : le recopier tel quel) :", *demandes)

    # 5. Construire avec le cache.
    cmd = [sys.executable, "-I", str(ICI / "construire_floorbox.py")]
    for pays in COMPTES:
        x = pays.lower()
        ecrire(travail / f"_{x}_historiques.json", [annonces[i] for i in historiques[pays]])
        ecrire(travail / f"_{x}_medias.json", [{**m, "image_hash": h} for h, m in medias[pays].items()])
        cmd += [f"--{x}-ads", str(travail / f"{x}_actives.json"), str(travail / f"_{x}_historiques.json"),
                f"--{x}-medias", str(travail / f"_{x}_medias.json"), f"--{x}-perf", str(travail / f"{x}_perf.json"),
                f"--{x}-soum", str(travail / f"{x}_soum.json")]
    cmd += ["--depuis", DEPUIS, "--date", args.date]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sortie = "\n".join(l for l in r.stdout.splitlines() if "lien complet" not in l)
    if r.returncode:
        stop(3, "PROBLÈME : la construction a échoué.", sortie, r.stderr[-3000:])
    g = lire(F.RACINE / "annonces.json", {})
    en_ligne = sum(a["actif"] for a in g.get("annonces", []))
    if g.get("fin") != veille or g.get("mise_a_jour") != args.date or en_ligne != attendues:
        stop(3, f"PROBLÈME : construction incohérente (fin {g.get('fin')}, mise à jour {g.get('mise_a_jour')}, "
                f"{en_ligne} annonces en ligne pour {attendues} actives avec visuel). Ne pas pousser.", sortie)

    # Le ménage : les dossiers de tirage de plus de 14 jours.
    limite = (date.fromisoformat(args.date) - timedelta(days=14)).isoformat()
    for d in CACHE.glob("tirage-*"):
        if d.is_dir() and d.name[len("tirage-"):] < limite:
            shutil.rmtree(d)

    print(sortie)
    print(f"PRÊT : galerie construite au {args.date} (chiffres jusqu'au {veille}), {en_ligne} annonces en ligne.")


if __name__ == "__main__":
    main()
