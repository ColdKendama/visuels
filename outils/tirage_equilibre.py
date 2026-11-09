"""Mise à jour quotidienne de la galerie Équilibre : dit quoi tirer par Markifact, puis construit.

Les annonces et les médias déjà vus restent en cache (~/.cache/visuels/equilibre/) : chaque
jour, il ne faut tirer que les annonces actives, le rapport, et ce qui est nouveau. On relance
le script après chaque tirage ; il dit la prochaine chose à tirer (code de sortie 2), ou
construit la galerie quand tout y est (code 0). Code 3 : un problème qui demande un humain.

    python3 -I outils/tirage_equilibre.py              # dossier du jour : ~/.cache/visuels/equilibre/tirage-AAAA-MM-JJ
    python3 -I outils/tirage_equilibre.py --sans-videos   # construire même si des vidéos n'ont pas pu être tirées

Fichiers que le tirage dépose dans le dossier du jour (noms exacts) :
    actives.json            meta_ads_list_ads, annonces actives (voir les entrées imprimées)
    perf.json               meta_ads_get_report, du 2026-07-01 à la veille
    historiques_*.json      meta_ads_list_ads des identifiants demandés
    medias_*.json           meta_ads_get_media_details des hashes et vidéos demandés
    complements.json        {story_id: {"video_id": ...}} pour une vidéo Legacy (meta_ads_get_ad_creative)
    sources.json            {video_id: url} : le champ source des vidéos demandées (meta_ads_get_graph_data)
"""

import argparse
import glob
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("construire", ICI / "construire_equilibre.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

CACHE = Path.home() / ".cache" / "visuels" / "equilibre"
COMPTE = "act_807927256273007"
CONNEXION = "63ab1d5f-e045-49f8-9f53-00779cad1271"   # Meta par chrystopher_c.a@hotmail.fr
PAGE = "624700294315387"
DEBUT = "2026-07-01"
STATUTS = ["ACTIVE", "PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED", "ARCHIVED", "WITH_ISSUES", "DELETED",
           "DISAPPROVED", "PENDING_REVIEW", "IN_PROCESS"]


def lire(p, defaut):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else defaut


def ecrire(p, d):
    Path(p).write_text(json.dumps(d, ensure_ascii=False))


def stop(code, *lignes):
    print("\n".join(lignes))
    sys.exit(code)


def entree(op, donnees):
    return f"  {op} : {json.dumps(donnees, ensure_ascii=False)}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--sans-videos", action="store_true", help="construire sans les vidéos qu'on n'a pas pu tirer")
    args = p.parse_args()
    veille = (date.fromisoformat(args.date) - timedelta(days=1)).isoformat()
    if not C.CLE.exists():
        stop(3, f"PROBLÈME : la clé {C.CLE} manque. Une nouvelle clé casserait le lien déjà envoyé : rien de fait.")
    travail = CACHE / f"tirage-{args.date}"
    travail.mkdir(parents=True, exist_ok=True)
    print(f"Dossier du jour : {travail}")

    # 1. Les deux tirages de base.
    manque = [f for f in ("actives.json", "perf.json") if not (travail / f).exists()]
    if manque:
        stop(2, "À TIRER (gros résultats : get_file_url puis curl -o dans le dossier du jour) :",
             entree("meta_ads_list_ads → actives.json", {
                 "connection_id": CONNEXION, "account": COMPTE, "campaign_effective_status": ["ACTIVE"],
                 "adset_effective_status": ["ACTIVE"], "ad_effective_status": ["ACTIVE"],
                 "include_creative": True, "limit": 500}) if "actives.json" in manque else "",
             entree("meta_ads_get_report → perf.json", {
                 "connection_id": CONNEXION, "accounts": [COMPTE],
                 "date_range": {"preset": "FIXED", "start": DEBUT, "end": veille},
                 "dimensions": ["date", "campaignId", "campaignName", "optimizationGoal", "adsetId", "adsetName",
                                "adId", "adName"],
                 "metrics": ["cost", "impressions", "linkClicks", "landingPageViews", "websiteViewContent",
                             "websiteAppointmentsScheduled", "videoViews", "thruPlays"],
                 "filters": [{"field": "impressions", "operator": "GREATER_THAN", "value": "0"}],
                 "limit": 20000}) if "perf.json" in manque else "")

    actives = lire(travail / "actives.json", [])
    perf = lire(travail / "perf.json", [])
    if not isinstance(actives, list) or not isinstance(perf, list) or not perf:
        stop(3, "PROBLÈME : actives.json ou perf.json n'est pas une liste (ou le rapport est vide).")
    fin = max(r["date"] for r in perf)
    if fin != veille:
        stop(3, f"PROBLÈME : le rapport s'arrête au {fin}, pas à la veille ({veille}). Rien de construit.")
    if len(perf) >= 20000:
        stop(3, "PROBLÈME : le rapport touche la limite de 20 000 lignes : le couper en deux plages.")

    # 2. Le cache, enrichi de ce qui a été tiré aujourd'hui.
    CACHE.mkdir(parents=True, exist_ok=True)
    annonces = lire(CACHE / "annonces.json", {})
    medias = lire(CACHE / "medias.json", {"images": {}, "videos": {}})
    complements = lire(CACHE / "complements.json", {})
    for f in [travail / "actives.json"] + sorted(travail.glob("historiques_*.json")):
        for a in lire(f, []):
            annonces[a["id"]] = {**a, "_tire": args.date}
    for f in sorted(travail.glob("medias_*.json")):
        d = lire(f, {})
        for i in d.get("images") or []:
            medias["images"][i["hash"]] = {**i, "_tire": args.date}
        for v in d.get("videos") or []:
            medias["videos"][str(v["id"])] = {**v, "_tire": args.date}
    complements.update(lire(travail / "complements.json", {}))
    ecrire(CACHE / "annonces.json", annonces)
    ecrire(CACHE / "medias.json", medias)
    ecrire(CACHE / "complements.json", complements)

    # 3. Les annonces à montrer : les actives, et celles qui ont livré (hors boosts).
    ids_actifs = [a["id"] for a in actives if "Engagement" not in a["campaign_name"]]
    livrees = {r["adId"] for r in perf if r["impressions"] and C.but(r)}
    historiques = sorted(livrees - set(ids_actifs))
    a_tirer = [i for i in historiques if i not in annonces]
    if a_tirer:
        lots = [a_tirer[k:k + 150] for k in range(0, len(a_tirer), 150)]
        stop(2, f"À TIRER : {len(a_tirer)} annonces qui ont livré mais ne sont pas en cache, "
                f"en {len(lots)} appel(s), fichiers historiques_1.json, historiques_2.json... :",
             *[entree(f"meta_ads_list_ads → historiques_{n}.json", {
                 "connection_id": CONNEXION, "account": COMPTE, "ad_effective_status": STATUTS,
                 "filters": [{"field": "ad_id", "operator": "IN_LIST", "value": ",".join(l)}],
                 "include_creative": True, "limit": 500}) for n, l in enumerate(lots, 1)])
    montrer = [annonces[i] for i in ids_actifs] + [annonces[i] for i in historiques]

    # 4. Les vidéos Legacy (ni image ni vidéo dans l'annonce) : la vidéo vient de la créa.
    legacy = [a for a in montrer if not any(C.empreinte_brute(a)) and not a.get("creative_image_url")
              and (a.get("creative_effective_object_story_id") or "") not in complements]
    if legacy:
        stop(2, "À TIRER : vidéos Legacy sans vidéo connue. Pour chacune, meta_ads_get_ad_creative donne le "
                "video_id ; écrire complements.json = {\"<creative_effective_object_story_id>\": {\"video_id\": \"...\"}} :",
             *[f"  annonce {a['id']} ({a['name']}), créa {a.get('creative_id')}, "
               f"publication {a.get('creative_effective_object_story_id')}" for a in legacy])

    # 5. Les médias : détails manquants, et liens frais pour tout fichier à télécharger.
    hashes, vids = set(), set()
    for a in montrer:
        h, v = C.empreinte_brute(a)
        hashes |= h
        vids |= v
        x = complements.get(a.get("creative_effective_object_story_id") or "", {}).get("video_id")
        if x:
            vids.add(str(x))
    manquants_h = {h for h in hashes if h not in medias["images"]}
    manquants_v = {v for v in vids if v not in medias["videos"]}
    perimes_a = set()
    for a in montrer:
        fmt, ms, _ = C.medias_annonce(a, medias["images"], medias["videos"], complements)
        for cle, _url in ms:
            if (C.IMAGES / (C.slug(cle) + ".jpg")).exists():
                continue
            if cle in medias["images"] and medias["images"][cle].get("_tire") != args.date:
                manquants_h.add(cle)
            elif cle in medias["videos"] and medias["videos"][cle].get("_tire") != args.date:
                manquants_v.add(cle)
            elif fmt == "Image" and a.get("creative_image_url") and a.get("_tire") != args.date:
                perimes_a.add(a["id"])      # image Legacy : le lien vient de l'annonce
    if perimes_a:
        perimes_a = sorted(perimes_a)
        stop(2, "À TIRER : annonces Legacy dont l'image est nouvelle et le lien périmé (fichier historiques_frais.json) :",
             entree("meta_ads_list_ads → historiques_frais.json", {
                 "connection_id": CONNEXION, "account": COMPTE, "ad_effective_status": STATUTS,
                 "filters": [{"field": "ad_id", "operator": "IN_LIST", "value": ",".join(perimes_a)}],
                 "include_creative": True, "limit": 500}))
    if manquants_h or manquants_v:
        h, v = sorted(manquants_h), sorted(manquants_v)
        lots = [("image_hashes", h[k:k + 60]) for k in range(0, len(h), 60)] + \
               [("video_ids", v[k:k + 10]) for k in range(0, len(v), 10)]      # 10 vidéos au plus, sinon l'appel expire
        stop(2, f"À TIRER : détails de {len(h)} images et {len(v)} vidéos, en {len(lots)} appel(s), "
                "fichiers medias_1.json, medias_2.json... (un petit résultat revient en ligne : le recopier tel quel) :",
             *[entree(f"meta_ads_get_media_details → medias_{n}.json",
                      {"connection_id": CONNEXION, "account": COMPTE, champ: l}) for n, (champ, l) in enumerate(lots, 1)])

    # 6. Les vidéos affichées qui ne sont pas encore dans la galerie : leur fichier MP4.
    sources = {p.stem: "local" for p in C.VIDEOS.glob("*.mp4")}
    sources.update(lire(travail / "sources.json", {}))
    a_jouer = set()
    for a in montrer:
        fmt, ms, _ = C.medias_annonce(a, medias["images"], medias["videos"], complements)
        if fmt == "Vidéo" and ms[0][0] not in sources:
            a_jouer.add(ms[0][0])
    if a_jouer and not args.sans_videos:
        stop(2, "À TIRER : le fichier des vidéos nouvelles, un appel par vidéo, réponses réunies dans "
                "sources.json = {\"<video_id>\": \"<source>\"} (si un appel échoue, relancer avec --sans-videos) :",
             *[entree("meta_ads_get_graph_data", {"connection_id": CONNEXION, "path": f"{v}?fields=source",
                                                  "page_id": PAGE}) for v in sorted(a_jouer)])

    # 7. Construire avec le cache.
    ecrire(travail / "_historiques.json", [annonces[i] for i in historiques])
    ecrire(travail / "_medias.json", {"images": list(medias["images"].values()),
                                      "videos": list(medias["videos"].values())})
    ecrire(travail / "_complements.json", complements)
    ecrire(travail / "_sources.json", sources)
    r = subprocess.run([sys.executable, "-I", str(ICI / "construire_equilibre.py"),
                        "--ads", str(travail / "actives.json"), str(travail / "_historiques.json"),
                        "--medias", str(travail / "_medias.json"), "--perf", str(travail / "perf.json"),
                        "--complements", str(travail / "_complements.json"),
                        "--sources", str(travail / "_sources.json"), "--date", args.date],
                       capture_output=True, text=True)
    sortie = "\n".join(l for l in r.stdout.splitlines() if "lien complet" not in l)
    if r.returncode:
        stop(3, "PROBLÈME : la construction a échoué.", sortie, r.stderr[-3000:])
    g = lire(C.RACINE / "annonces.json", {})
    en_ligne = sum(a["actif"] for a in g.get("annonces", []))
    if g.get("fin") != veille or g.get("mise_a_jour") != args.date or en_ligne != len(ids_actifs):
        stop(3, f"PROBLÈME : construction incohérente (fin {g.get('fin')}, mise à jour {g.get('mise_a_jour')}, "
                f"{en_ligne} annonces en ligne pour {len(ids_actifs)} actives). Ne pas pousser.", sortie)

    # Le ménage : les dossiers de tirage de plus de 14 jours.
    limite = (date.fromisoformat(args.date) - timedelta(days=14)).isoformat()
    for d in CACHE.glob("tirage-*"):
        if d.is_dir() and d.name[len("tirage-"):] < limite:
            shutil.rmtree(d)

    print(sortie)
    print(f"PRÊT : galerie construite au {args.date} (chiffres jusqu'au {veille}), {en_ligne} annonces en ligne"
          + (f", {len(a_jouer)} vidéo(s) sans fichier" if a_jouer else "") + ".")


if __name__ == "__main__":
    main()
