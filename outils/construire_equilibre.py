"""Construit equilibre/annonces.json et les images de la galerie Équilibre.

Entrées : sorties Markifact du compte act_807927256273007 (voir le README) :
meta_ads_list_ads (les trois statuts à ACTIVE, include_creative),
meta_ads_get_media_details (images et vidéos, un ou plusieurs fichiers),
meta_ads_get_report par jour et par annonce pour l'indice, et un fichier de
compléments pour les annonces Legacy dont la vidéo n'est pas exposée.

    python3 -I outils/construire_equilibre.py \
        --ads annonces.json --medias medias_*.json --perf perf.json \
        --complements complements.json --date 2026-11-04

Chaque annonce est rangée dans sa catégorie de ciblage et jugée sur le but
de son ad set : les View Content pour les ad sets de conversion, les vues de
page pour les ad sets optimisés sur les vues de page (notoriété).
"""

import argparse
import json
import math
import re
import subprocess
import tempfile
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent / "equilibre"
IMAGES = RACINE / "images"
MINIS = IMAGES / "min"

# Le but d'un ad set décide du résultat qui sert à l'indice.
BUTS = {
    "conversion": {"resultat": "View Content", "metrique": "websiteViewContent", "attribution": True},
    "notoriete": {"resultat": "vues de page", "metrique": "landingPageViews", "attribution": False},
}

# Ordre d'affichage des catégories de ciblage.
CIBLAGES = ["Scale", "Marchés rouges", "Local", "Spécialisé", "Notoriété", "Test"]
ORDRE_GROUPES = ["Scale AP", "Scale OP", "Rouges prioritaires AP", "Rouges bulk AP", "Rouges OP",
                 "Genou DR", "Pédiatrie OP", "Vidéos de notoriété AP"]

ATTRIBUTION = 7     # les View Content des 7 derniers jours ne sont pas toutes attribuées
JOURS_MIN = 7       # jours jugés avant un verdict
BUDGET_MIN = 3      # résultats que le budget aurait dû acheter avant de juger (0 sur 3 : p = 0,05)
CLICS_MIN = 15      # clics attendus avant de juger l'accroche
VUES_MIN = 15       # vues de 3 s attendues avant de juger la rétention


def poisson(k, lam, haut):
    """P(X ≤ k), ou P(X ≥ k) si haut, pour X de Poisson de moyenne lam (en log : lam peut valoir des milliers)."""
    if lam <= 0:
        return 1.0
    termes = (math.exp(i * math.log(lam) - lam - math.lgamma(i + 1)) for i in range(int(k) + (0 if haut else 1)))
    bas = min(1.0, sum(termes))
    return max(0.0, 1 - bas) if haut else bas


def but(r):
    """Le but de l'ad set d'une ligne du rapport, ou None (Schedule restreint, publications boostées)."""
    if r["optimizationGoal"] == "LANDING_PAGE_VIEWS" and "Engagement" not in r["campaignName"]:
        return "notoriete"
    if r["optimizationGoal"] == "OFFSITE_CONVERSIONS" and "viewcontent" in r["adsetName"].lower():
        return "conversion"
    return None


def ligne(campagne):
    m = re.search(r"\b(AP|OP|DR)\b", campagne)
    return m.group(1) if m else ""


def ciblage(campagne, adset):
    c, g = campagne.lower(), adset.lower()
    if g.startswith("lpv") or "notori" in c:
        return "Notoriété"
    if "rouges" in g or "marchés rouges" in c:
        return "Marchés rouges"
    if " local " in c:
        return "Local"
    if "leads - scale" in c:
        return "Scale"
    if "leads - test" in c:
        return "Test"
    if "genou" in g or "pédiatrie" in g or " dr " in c:
        return "Spécialisé"
    return "Autre"


def groupe(campagne, adset):
    """Nom court de l'ad set, lisible par le client."""
    cib, li, g = ciblage(campagne, adset), ligne(campagne), adset.lower()
    if cib == "Marchés rouges":
        if "prioritaires" in g:
            return "Rouges prioritaires AP"
        return "Rouges bulk AP" if "bulk" in g else f"Rouges {li}"
    if cib == "Local":
        m = re.search(r"Lookalike - (.+?) - FR", adset)
        return f"{m.group(1) if m else adset} {li}"
    if cib == "Spécialisé":
        return "Genou DR" if "genou" in g else "Pédiatrie OP" if "pédiatrie" in g else f"{adset} {li}"
    if cib == "Notoriété":
        return f"Vidéos de notoriété {li}"
    return f"{cib} {li}"


def concept(nom):
    """Le nom d'annonce sans date, ligne, format ni suffixe de marché rouge."""
    n = nom.replace("​", "").strip()
    test = n.startswith("Test - ")
    precedent = None
    while n != precedent:
        precedent = n
        n = re.sub(r" - MR( bulk| prioritaires)?$", "", n)
        n = re.sub(r"^(Test|Legacy) - ", "", n)
        n = re.sub(r" - Legacy - ", " - ", n)
        n = re.sub(r"^(\d{8}|\d{6}|\d{4}-\d{2}) - ", "", n)
        n = re.sub(r"^(AP|OP|DR) - ", "", n)
        n = re.sub(r"^(Image|Video|Vidéo|Carrousel) - ", "", n)
        n = re.sub(r" - (Image|Video|Vidéo|Carrousel)$", "", n)
    n = n.replace("Notoriete", "Notoriété")
    return n + (" (copie test)" if test else "")


class Cumul:
    """Totaux d'une annonce, d'un ad set ou d'une campagne, et les annonces qui y ont livré."""

    def __init__(self):
        self.m, self.annonces = Counter(), set()

    def ajouter(self, ad, m):
        self.m.update(m)
        self.annonces.add(ad)


def niveau_ratio(ratio):
    return "forte" if ratio >= 1.15 else "moyenne" if ratio >= 0.85 else "faible"


def performance(fichier, fin, montants):
    """Indice par annonce : résultats par dollar contre la moyenne de son ad set.

    Le résultat dépend du but de l'ad set (BUTS). La référence est l'ad set
    quand au moins deux annonces y ont livré, sinon la campagne (même but) ;
    elle compte toutes les annonces qui ont livré, actives ou non. En
    conversion, l'indice s'arrête 7 jours avant la fin des données.
    Renvoie ({ad_id: perf}, date fermée).
    """
    ferme = (date.fromisoformat(fin) - timedelta(days=ATTRIBUTION)).isoformat()
    recent = (date.fromisoformat(fin) - timedelta(days=ATTRIBUTION - 1)).isoformat()
    cumuls = defaultdict(Cumul)
    premier, infos = {}, {}
    for r in json.loads(Path(fichier).read_text()):
        b = but(r)
        if b is None or r["date"] > fin or not r["impressions"]:
            continue
        ad, g = r["adId"], r["adsetId"]
        c = (r["campaignId"], b)
        m = Counter({"cost": r["cost"], "impressions": r["impressions"], "linkClicks": r["linkClicks"],
                     "results": r[BUTS[b]["metrique"]], "videoViews": r["videoViews"], "thruPlays": r["thruPlays"]})
        infos[ad] = (b, g, c)
        premier[ad] = min(premier.get(ad, r["date"]), r["date"])
        juge = not BUTS[b]["attribution"] or r["date"] <= ferme
        fenetres = ["tout"] + (["juge"] if juge else []) + (["recent"] if r["date"] >= recent else [])
        for fen in fenetres:
            for cle in (("ad", ad), ("groupe", g), ("campagne", c)):
                cumuls[(fen,) + cle].ajouter(ad, m)

    def reference(fen, ad):
        _, g, c = infos[ad]
        cg = cumuls[(fen, "groupe", g)]
        return (cg, "groupe") if len(cg.annonces) > 1 else (cumuls[(fen, "campagne", c)], "campagne")

    sortie = {}
    for ad, (b, g, c) in infos.items():
        f, t = cumuls[("juge", "ad", ad)].m, cumuls[("tout", "ad", ad)].m
        ref_c, niveau_ref = reference("juge", ad)
        ref, ct = ref_c.m, reference("tout", ad)[0].m
        p = {"but": b, "resultat": BUTS[b]["resultat"], "en_ligne": premier[ad], "reference": niveau_ref,
             "nb_reference": len(ref_c.annonces) if niveau_ref == "groupe" else None}

        # Le but, sur les jours jugés.
        fin_juge = ferme if BUTS[b]["attribution"] else fin
        jours = (date.fromisoformat(fin_juge) - date.fromisoformat(premier[ad])).days + 1
        attendus = f["cost"] * ref["results"] / ref["cost"] if ref["results"] and ref["cost"] else 0
        if jours >= JOURS_MIN and attendus >= BUDGET_MIN:
            indice = f["results"] / attendus * 100
            pval = poisson(f["results"], attendus, haut=indice >= 100)
            preuve = "Confirmé" if pval <= 0.05 else "Probable" if pval <= 0.20 else "À confirmer"
            if indice >= 115:
                niveau = "vert"
            elif indice >= 90:
                niveau = "neutre"
            elif indice >= 77 or pval > 0.20:   # pas de rouge sans preuve
                niveau = "orange"
            else:
                niveau = "rouge"
            p.update(statut="juge", indice=round(indice), niveau=niveau, preuve=preuve)
        elif jours < JOURS_MIN:
            delai = JOURS_MIN + (ATTRIBUTION if BUTS[b]["attribution"] else 0)
            vers = date.fromisoformat(premier[ad]) + timedelta(days=delai)
            p.update(statut="test", verdict_vers=vers.isoformat())
        else:
            p.update(statut="peu")

        # Ce qui se lit sans attendre l'attribution, jusqu'à la fin des données.
        if t["impressions"] and ct["impressions"]:
            if b == "conversion":
                # Accroche : le taux de clic sur le lien.
                ctr, ctr_moy = t["linkClicks"] / t["impressions"], ct["linkClicks"] / ct["impressions"]
                p.update(ctr=round(ctr * 100, 2), ctr_moy=round(ctr_moy * 100, 2))
                if ctr_moy and t["impressions"] * ctr_moy >= CLICS_MIN:
                    p["accroche"] = niveau_ratio(ctr / ctr_moy)
            elif t["videoViews"] and ct["videoViews"]:
                # Notoriété : arrêt sur la vidéo (vues de 3 s), puis rétention (ThruPlay).
                arret, arret_moy = t["videoViews"] / t["impressions"], ct["videoViews"] / ct["impressions"]
                ret, ret_moy = t["thruPlays"] / t["videoViews"], ct["thruPlays"] / ct["videoViews"]
                p.update(arret=round(arret * 100, 1), arret_moy=round(arret_moy * 100, 1),
                         retention=round(ret * 100, 1), retention_moy=round(ret_moy * 100, 1))
                if t["impressions"] * arret_moy >= VUES_MIN:
                    p["accroche"] = niveau_ratio(arret / arret_moy)
                if ret_moy and t["videoViews"] >= VUES_MIN:
                    p["tenue"] = niveau_ratio(ret / ret_moy)

        # Ce que Meta lui confie dans son ad set, quand il y a un choix à faire.
        cg = cumuls[("recent", "groupe", g)]
        if len(cg.annonces) > 1 and cg.m["cost"]:
            p["part_7j"] = round(cumuls[("recent", "ad", ad)].m["cost"] / cg.m["cost"] * 100)

        if montants:
            p.update(depense=round(f["cost"]), resultats=int(f["results"]),
                     cout=round(f["cost"] / f["results"], 2) if f["results"] else None,
                     cout_moy=round(ref["cost"] / ref["results"], 2) if ref["results"] else None)
        sortie[ad] = p
    return sortie, ferme


# Médias -------------------------------------------------------------------

def charger_medias(fichiers):
    images, videos = {}, {}
    for fichier in fichiers:
        d = json.loads(Path(fichier).read_text())
        for i in d.get("images") or []:
            images[i["hash"]] = i
        for v in d.get("videos") or []:
            videos[str(v["id"])] = v
    return images, videos


def rang_video(titre):
    """Préférer le 4:5, puis le carré, puis le 9:16, d'après le nom du fichier."""
    t = (titre or "").lower()
    if "portrait" in t or "4x5" in t or "4_5" in t:
        return 0
    if "square" in t or "1x1" in t or "carre" in t:
        return 1
    if "stor" in t or "9x16" in t:
        return 2
    return 3


def medias_annonce(a, images, videos, complements):
    """(format, [(cle, url)], durée) : le visuel affiché d'abord, puis les cartes d'un carrousel."""
    cartes = [c["image_hash"] for c in a.get("creative_object_story_spec_link_data_child_attachments") or []
              if c.get("image_hash")]
    if cartes:
        return "Carrousel", [(h, images[h]["url"]) for h in cartes if h in images], None
    vids = [str(v["video_id"]) for v in a.get("creative_asset_feed_spec_videos") or []]
    extra = complements.get(a.get("creative_effective_object_story_id") or "", {})
    if not vids and extra.get("video_id"):
        vids = [str(extra["video_id"])]
    vids = [v for v in vids if v in videos]
    if vids:
        v = videos[min(vids, key=lambda i: rang_video(videos[i].get("title")))]
        return "Vidéo", [(v["id"], v["thumbnail_url"])], round(float(v.get("length") or 0))
    hashes = [i["hash"] for i in a.get("creative_asset_feed_spec_images") or []]
    if a.get("creative_object_story_spec_link_data_image_hash"):
        hashes.append(a["creative_object_story_spec_link_data_image_hash"])
    candidats = [images[h] for h in hashes if h in images]
    if candidats:
        i = min(candidats, key=lambda m: abs(m["height"] / m["width"] - 1.25))
        return "Image", [(i["hash"], i["url"])], None
    if a.get("creative_image_url"):
        # Annonce Legacy : l'image entière, clé = le fichier Meta (le même pour les copies).
        cle = Path(a["creative_image_url"].split("?")[0]).stem
        return "Image", [(cle, a["creative_image_url"])], None
    return None, [], None


def textes(a):
    titres = [t["text"] for t in a.get("creative_asset_feed_spec_titles") or []] or [a.get("creative_title") or ""]
    corps = [t["text"] for t in a.get("creative_asset_feed_spec_bodies") or []] or [a.get("creative_body") or ""]
    cartes = a.get("creative_object_story_spec_link_data_child_attachments") or []
    if cartes and cartes[0].get("name"):
        titres = [cartes[0]["name"]]
    titres = [t for t in titres if t and "{{" not in t]
    return (titres[0] if titres else ""), (corps[0] if corps else "")


def slug(texte):
    return re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")


def sips(source, cible, *options):
    subprocess.run(["sips", "-s", "format", "jpeg", *options, str(source), "--out", str(cible)],
                   check=True, capture_output=True)


def preparer(cle, url):
    """Télécharge le visuel une fois, en JPEG de 1350 px au plus, avec sa miniature de 540 px."""
    fichier = slug(cle) + ".jpg"
    image, mini = IMAGES / fichier, MINIS / fichier
    if not image.exists():
        with tempfile.TemporaryDirectory() as tmp:
            brut = Path(tmp) / "brut"
            with urllib.request.urlopen(url, timeout=60) as r:
                brut.write_bytes(r.read())
            sips(brut, image, "-s", "formatOptions", "85", "-Z", "1350")
    if not mini.exists() or mini.stat().st_mtime < image.stat().st_mtime:
        sips(image, mini, "-s", "formatOptions", "80", "--resampleWidth", "540")
    return f"images/{fichier}", f"images/min/{fichier}"


def annonces_meta(fichier_ads, images, videos, complements, perfs):
    sortie = []
    for a in json.loads(Path(fichier_ads).read_text()):
        if a["effective_status"] != "ACTIVE":
            continue
        cib = ciblage(a["campaign_name"], a["adset_name"])
        if "Engagement" in a["campaign_name"]:
            continue    # publications boostées : hors galerie (décision du 2026-11-04)
        fmt, medias, duree = medias_annonce(a, images, videos, complements)
        if not medias:
            print(f"  sans visuel, ignorée : {a['name']}")
            continue
        fichiers = [preparer(cle, url) for cle, url in medias]
        titre, corps = textes(a)
        entree = {
            "id": a["id"], "nom": a["name"].replace("​", ""), "concept": concept(a["name"]),
            "ligne": ligne(a["campaign_name"]), "ciblage": cib, "groupe": groupe(a["campaign_name"], a["adset_name"]),
            "format": fmt, "titre": titre, "texte": corps, "depuis": a["created_time"][:10],
            "image": fichiers[0][0], "mini": fichiers[0][1], "visuel": medias[0][0],
            "lien": a.get("preview_shareable_link") or "",
        }
        if duree:
            entree["duree"] = duree
        if fmt == "Carrousel" and len(fichiers) > 1:
            entree["cartes"] = [{"image": i, "mini": m} for i, m in fichiers]
        if perfs is not None:
            entree["perf"] = perfs.get(a["id"], {"statut": "test"})
        sortie.append(entree)
    return sortie


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ads", required=True, help="meta_ads_list_ads, annonces actives")
    p.add_argument("--medias", required=True, nargs="+", help="meta_ads_get_media_details (images, vidéos)")
    p.add_argument("--perf", help="meta_ads_get_report par jour et par annonce")
    p.add_argument("--complements", help="{story_id: {video_id}} pour les vidéos Legacy")
    p.add_argument("--date", default=date.today().isoformat(), help="date de mise à jour affichée")
    p.add_argument("--fin", help="dernier jour des données de performance (défaut : la veille de --date)")
    p.add_argument("--montants", action="store_true",
                   help="publier aussi dépense, résultats et coût par résultat (dépôt public !)")
    args = p.parse_args()

    MINIS.mkdir(parents=True, exist_ok=True)
    fin = args.fin or (date.fromisoformat(args.date) - timedelta(days=1)).isoformat()
    images, videos = charger_medias(args.medias)
    complements = json.loads(Path(args.complements).read_text()) if args.complements else {}
    perfs = periode = None
    if args.perf:
        perfs, ferme = performance(args.perf, fin, args.montants)
        debut = min(json.loads(Path(args.perf).read_text()), key=lambda r: r["date"])["date"]
        periode = {"debut": debut, "ferme": ferme, "fin": fin}
    annonces = annonces_meta(args.ads, images, videos, complements, perfs)

    ordre_c = {c: i for i, c in enumerate(CIBLAGES)}
    ordre_g = {g: i for i, g in enumerate(ORDRE_GROUPES)}
    annonces.sort(key=lambda a: a["depuis"], reverse=True)
    annonces.sort(key=lambda a: (ordre_c.get(a["ciblage"], 99), ordre_g.get(a["groupe"], 50), a["groupe"]))

    # Les fichiers des annonces qui ne roulent plus quittent la galerie.
    garder = {Path(x).name for a in annonces
              for x in [a["image"], a["mini"]] + [c[k] for c in a.get("cartes", []) for k in ("image", "mini")]}
    for dossier in (IMAGES, MINIS):
        for f in dossier.glob("*.jpg"):
            if f.name not in garder:
                f.unlink()

    sortie = {"mise_a_jour": args.date, "annonces": annonces}
    if periode:
        sortie["performance"] = periode
    (RACINE / "annonces.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=1))
    par_cib = Counter(a["ciblage"] for a in annonces)
    print(f"{len(annonces)} visuels : " + ", ".join(f"{c} {par_cib[c]}" for c in CIBLAGES if par_cib[c]))
    if periode:
        statuts = Counter(a["perf"]["statut"] for a in annonces)
        niveaux = Counter(a["perf"]["niveau"] for a in annonces if a["perf"].get("niveau"))
        print(f"conversion jugée au {periode['ferme']}, notoriété au {periode['fin']} : "
              f"{statuts['juge']} jugés {dict(niveaux)}, {statuts['test']} en test, {statuts['peu']} peu diffusés")


if __name__ == "__main__":
    main()
