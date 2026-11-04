"""Construit equilibre/annonces.json, les images et les vidéos de la galerie Équilibre.

Entrées : sorties Markifact du compte act_807927256273007 (voir le README) :
meta_ads_list_ads (les annonces actives, plus celles qui ont livré pendant
les périodes affichées), meta_ads_get_media_details (images et vidéos),
meta_ads_get_report par jour et par annonce depuis juillet, les sources des
vidéos (lues avec le jeton de la Page) et un fichier de compléments pour les
vidéos Legacy.

    python3 -I outils/construire_equilibre.py \
        --ads annonces.json annonces_historiques.json --medias medias_*.json \
        --perf perf.json --complements complements.json --sources sources.json \
        --date 2026-11-04

Chaque annonce est rangée dans sa catégorie de ciblage. L'indice se calcule
par période (les 30 derniers jours et chaque mois) contre la moyenne de son
ad set, sur le but de l'ad set : les View Content en conversion depuis le
5 octobre, website_schedule avant, les vues de page pour les ad sets
optimisés sur les vues de page.
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
VIDEOS = RACINE / "videos"

PASSAGE_VC = "2026-10-05"     # premiers ad sets optimisés sur View Content
FIN_SCHEDULE = "2026-09-26"   # dernier jour où Meta voit website_schedule (compte classé santé)
METRIQUES = {"vc": "websiteViewContent", "rdv": "websiteAppointmentsScheduled", "lpv": "landingPageViews"}
RESULTATS = {"vc": "View Content", "rdv": "rendez-vous", "lpv": "vues de page"}
NOMS_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]

# Ordre d'affichage des catégories de ciblage et des ad sets.
CIBLAGES = ["Scale", "Marchés rouges", "Local", "Spécialisé", "Notoriété", "Test"]
ORDRE_GROUPES = ["Scale AP", "Scale OP", "Rouges prioritaires AP", "Rouges bulk AP", "Rouges prioritaires OP",
                 "Rouges OP", "Genou DR", "Pédiatrie OP", "Vidéos de notoriété AP", "Test AP", "Test OP"]

ATTRIBUTION = 7     # les conversions des 7 derniers jours ne sont pas toutes attribuées
JOURS_MIN = 7       # jours jugés avant un verdict
BUDGET_MIN = 3      # résultats que le budget aurait dû acheter avant de juger (0 sur 3 : p = 0,05)
CLICS_MIN = 15      # clics attendus avant de juger l'accroche
VUES_MIN = 15       # vues de 3 s attendues avant de juger la rétention


def jour(iso, decalage=0):
    return (date.fromisoformat(iso) + timedelta(days=decalage)).isoformat()


def poisson(k, lam, haut):
    """P(X ≤ k), ou P(X ≥ k) si haut, pour X de Poisson de moyenne lam (en log : lam peut valoir des milliers)."""
    if lam <= 0:
        return 1.0
    termes = (math.exp(i * math.log(lam) - lam - math.lgamma(i + 1)) for i in range(int(k) + (0 if haut else 1)))
    bas = min(1.0, sum(termes))
    return max(0.0, 1 - bas) if haut else bas


def but(r, conversion):
    """Le résultat qui juge cette ligne du rapport pour une période, ou None (boosts, ad sets hors période)."""
    g = r["adsetName"].lower()
    if "Engagement" in r["campaignName"]:
        return None
    if r["optimizationGoal"] == "LANDING_PAGE_VIEWS":
        return "lpv"
    if r["optimizationGoal"] == "OFFSITE_CONVERSIONS":
        if conversion == "vc" and "viewcontent" in g:
            return "vc"
        if conversion == "rdv" and "viewcontent" not in g:
            return "rdv"
    return None


def ligne(campagne):
    m = re.search(r"\b(AP|OP|DR)\b", campagne)
    return m.group(1) if m else ""


def ciblage(campagne, adset):
    c, g = campagne.lower(), adset.lower()
    if "notori" in c:
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
    suffixe = " (vues de page)" if g.startswith("lpv") and cib != "Notoriété" else ""
    if cib == "Marchés rouges":
        if "prioritaires" in g:
            return f"Rouges prioritaires {li}"
        return f"Rouges bulk {li}" if "bulk" in g else f"Rouges {li}"
    if cib == "Local":
        m = re.search(r"Lookalike - (.+?) - FR", adset)
        return f"{(m.group(1) if m else adset).strip()} {li}{suffixe}"
    if cib == "Spécialisé":
        return "Genou DR" if "genou" in g else "Pédiatrie OP" if "pédiatrie" in g else f"{adset} {li}"
    if cib == "Notoriété":
        return f"Vidéos de notoriété {li}"
    return f"{cib} {li}{suffixe}"


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


# Périodes -------------------------------------------------------------------

def periodes(debut_donnees, fin):
    """Les 30 derniers jours, puis chaque mois du plus récent au plus ancien.

    Un mois n'apparaît que s'il a au moins 7 jours jugeables en conversion.
    Avant octobre, la conversion est website_schedule, coupée au 26 septembre ;
    à partir d'octobre, View Content, depuis le 5 octobre.
    """
    ferme = jour(fin, -ATTRIBUTION)
    sortie = [{"id": "30j", "libelle": "30 derniers jours", "debut": max(jour(fin, -29), PASSAGE_VC),
               "fin": fin, "fin_conversion": fin, "conversion": "vc", "recent": True}]
    m = date.fromisoformat(fin).replace(day=1)
    while m.isoformat() >= debut_donnees[:8] + "01":
        suivant = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        m_debut, m_fin = max(m.isoformat(), debut_donnees), min((suivant - timedelta(days=1)).isoformat(), fin)
        conv = "vc" if m.isoformat() >= "2026-10-01" else "rdv"
        if conv == "vc":
            m_debut = max(m_debut, PASSAGE_VC)
        fin_conv = min(m_fin, FIN_SCHEDULE) if conv == "rdv" else m_fin
        fin_juge = min(fin_conv, ferme)
        if (date.fromisoformat(fin_juge) - date.fromisoformat(m_debut)).days + 1 >= JOURS_MIN:
            sortie.append({"id": m.isoformat()[:7], "libelle": f"{NOMS_MOIS[m.month - 1].capitalize()} {m.year}",
                           "debut": m_debut, "fin": m_fin, "fin_conversion": fin_conv, "conversion": conv,
                           "recent": False})
        m = (m - timedelta(days=1)).replace(day=1)
    for p in sortie:
        p["fin_juge"] = min(p["fin_conversion"], ferme)
    return sortie


class Cumul:
    """Totaux d'une annonce, d'un ad set ou d'une campagne, et les annonces qui y ont livré."""

    def __init__(self):
        self.m, self.annonces = Counter(), set()

    def ajouter(self, ad, m):
        self.m.update(m)
        self.annonces.add(ad)


def niveau_ratio(ratio):
    return "forte" if ratio >= 1.15 else "moyenne" if ratio >= 0.85 else "faible"


def performance(lignes, p, fin, premier, montants):
    """Indice par annonce sur la période p : résultats par dollar contre la moyenne de son ad set.

    La référence est l'ad set quand au moins deux annonces y ont livré, sinon
    la campagne (même but) ; elle compte toutes les annonces qui ont livré,
    actives ou non. En conversion, l'indice s'arrête 7 jours avant la fin des
    données. Renvoie {ad_id: perf}.
    """
    ferme, recent = jour(fin, -ATTRIBUTION), jour(fin, -(ATTRIBUTION - 1))
    cumuls, infos = defaultdict(Cumul), {}
    for r in lignes:
        if not (p["debut"] <= r["date"] <= p["fin"]) or not r["impressions"]:
            continue
        b = but(r, p["conversion"])
        if b is None or (b != "lpv" and r["date"] > p["fin_conversion"]):
            continue
        ad, g, c = r["adId"], r["adsetId"], (r["campaignId"], b)
        m = Counter({"cost": r["cost"], "impressions": r["impressions"], "linkClicks": r["linkClicks"],
                     "results": r[METRIQUES[b]], "videoViews": r["videoViews"], "thruPlays": r["thruPlays"]})
        infos[ad] = (b, g, c)
        juge = b == "lpv" or r["date"] <= ferme
        fenetres = ["tout"] + (["juge"] if juge else []) + (["recent"] if p["recent"] and r["date"] >= recent else [])
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
        perf = {"but": "notoriete" if b == "lpv" else "conversion", "resultat": RESULTATS[b],
                "reference": niveau_ref, "nb_reference": len(ref_c.annonces) if niveau_ref == "groupe" else None}

        # Le but, sur les jours jugés.
        fin_juge = p["fin"] if b == "lpv" else p["fin_juge"]
        depart = max(premier[ad], p["debut"])
        jours = (date.fromisoformat(fin_juge) - date.fromisoformat(depart)).days + 1
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
            perf.update(statut="juge", indice=round(indice), niveau=niveau, preuve=preuve)
        elif jours < JOURS_MIN and p["recent"]:
            delai = JOURS_MIN + (0 if b == "lpv" else ATTRIBUTION)
            perf.update(statut="test", verdict_vers=jour(depart, delai))
        elif jours < JOURS_MIN:
            perf.update(statut="court")     # arrivée en fin de période
        else:
            perf.update(statut="peu")

        # Ce qui se lit sans attendre l'attribution, jusqu'à la fin de la période.
        if t["impressions"] and ct["impressions"]:
            if b != "lpv":
                ctr, ctr_moy = t["linkClicks"] / t["impressions"], ct["linkClicks"] / ct["impressions"]
                perf.update(ctr=round(ctr * 100, 2), ctr_moy=round(ctr_moy * 100, 2))
                if ctr_moy and t["impressions"] * ctr_moy >= CLICS_MIN:
                    perf["accroche"] = niveau_ratio(ctr / ctr_moy)
            elif t["videoViews"] and ct["videoViews"]:
                arret, arret_moy = t["videoViews"] / t["impressions"], ct["videoViews"] / ct["impressions"]
                ret, ret_moy = t["thruPlays"] / t["videoViews"], ct["thruPlays"] / ct["videoViews"]
                perf.update(arret=round(arret * 100, 1), arret_moy=round(arret_moy * 100, 1),
                            retention=round(ret * 100, 1), retention_moy=round(ret_moy * 100, 1))
                if t["impressions"] * arret_moy >= VUES_MIN:
                    perf["accroche"] = niveau_ratio(arret / arret_moy)
                if ret_moy and t["videoViews"] >= VUES_MIN:
                    perf["tenue"] = niveau_ratio(ret / ret_moy)

        # Ce que Meta lui confie dans son ad set : les 7 derniers jours, ou toute la période passée.
        fen = "recent" if p["recent"] else "tout"
        cg = cumuls[(fen, "groupe", g)]
        if len(cg.annonces) > 1 and cg.m["cost"]:
            perf["part"] = round(cumuls[(fen, "ad", ad)].m["cost"] / cg.m["cost"] * 100)

        if montants:
            perf.update(depense=round(f["cost"]), resultats=int(f["results"]),
                        cout=round(f["cost"] / f["results"], 2) if f["results"] else None,
                        cout_moy=round(ref["cost"] / ref["results"], 2) if ref["results"] else None)
        sortie[ad] = perf
    return sortie


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
    """Préférer le 4:5, puis le carré, puis un format inconnu, le 9:16 en dernier."""
    t = (titre or "").lower()
    if "portrait" in t or "4x5" in t or "4_5" in t:
        return 0
    if "square" in t or "1x1" in t or "carre" in t:
        return 1
    if "stor" in t or "9x16" in t:
        return 3
    return 2


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
        return "Vidéo", [(str(v["id"]), v["thumbnail_url"])], round(float(v.get("length") or 0))
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


def preparer_video(video_id, url):
    """Télécharge la vidéo une fois (MP4 720p que Meta sert à la Page), avec l'index en tête pour la lecture en continu."""
    cible = VIDEOS / f"{video_id}.mp4"
    if not cible.exists():
        with tempfile.TemporaryDirectory() as tmp:
            brut = Path(tmp) / "brut.mp4"
            with urllib.request.urlopen(url, timeout=120) as r:
                brut.write_bytes(r.read())
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(brut), "-c", "copy",
                            "-movflags", "+faststart", str(cible)], check=True)
    return f"videos/{cible.name}"


def entree_annonce(a, actif, images, videos, complements, sources, manquantes):
    fmt, medias, duree = medias_annonce(a, images, videos, complements)
    if not medias:
        print(f"  sans visuel, ignorée : {a['name']}")
        return None
    fichiers = [preparer(cle, url) for cle, url in medias]
    titre, corps = textes(a)
    e = {
        "id": a["id"], "nom": a["name"].replace("​", ""), "concept": concept(a["name"]),
        "ligne": ligne(a["campaign_name"]), "ciblage": ciblage(a["campaign_name"], a["adset_name"]),
        "groupe": groupe(a["campaign_name"], a["adset_name"]), "actif": actif,
        "format": fmt, "titre": titre, "texte": corps, "depuis": a["created_time"][:10],
        "image": fichiers[0][0], "mini": fichiers[0][1], "visuel": medias[0][0],
        "lien": a.get("preview_shareable_link") or "",
    }
    if duree:
        e["duree"] = duree
    if fmt == "Vidéo":
        if medias[0][0] in sources:
            e["video"] = preparer_video(medias[0][0], sources[medias[0][0]])
        else:
            manquantes.add(medias[0][0])
    if fmt == "Carrousel" and len(fichiers) > 1:
        e["cartes"] = [{"image": i, "mini": m} for i, m in fichiers]
    return e


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ads", required=True, nargs="+",
                   help="meta_ads_list_ads : les annonces actives, puis celles qui ont livré pendant les périodes")
    p.add_argument("--medias", required=True, nargs="+", help="meta_ads_get_media_details (images, vidéos)")
    p.add_argument("--perf", required=True, help="meta_ads_get_report par jour et par annonce")
    p.add_argument("--complements", help="{story_id: {video_id}} pour les vidéos Legacy")
    p.add_argument("--sources", help="{video_id: url} : le champ source de chaque vidéo, lu avec le jeton de la Page")
    p.add_argument("--date", default=date.today().isoformat(), help="date de mise à jour affichée")
    p.add_argument("--fin", help="dernier jour des données de performance (défaut : la veille de --date)")
    p.add_argument("--montants", action="store_true",
                   help="publier aussi dépense, résultats et coût par résultat (dépôt public !)")
    args = p.parse_args()

    MINIS.mkdir(parents=True, exist_ok=True)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    fin = args.fin or jour(args.date, -1)
    images, videos = charger_medias(args.medias)
    complements = json.loads(Path(args.complements).read_text()) if args.complements else {}
    sources = json.loads(Path(args.sources).read_text()) if args.sources else {}

    # Indice par période.
    lignes = [r for r in json.loads(Path(args.perf).read_text()) if r["date"] <= fin]
    premier = {}
    for r in lignes:
        if r["impressions"]:
            premier[r["adId"]] = min(premier.get(r["adId"], r["date"]), r["date"])
    liste_periodes = periodes(min(premier.values()), fin)
    perfs = {pe["id"]: performance(lignes, pe, fin, premier, args.montants) for pe in liste_periodes}

    # Annonces : les actives, et toutes celles qui ont un indice dans une période.
    toutes = {}
    for i, fichier in enumerate(args.ads):
        for a in json.loads(Path(fichier).read_text()):
            if "Engagement" in a["campaign_name"]:
                continue    # publications boostées : hors galerie (décision du 2026-11-04)
            actif = i == 0 and a["effective_status"] == "ACTIVE"
            if a["id"] not in toutes or actif:
                toutes[a["id"]] = (a, actif)
    annonces, manquantes = [], set()
    for ad, (a, actif) in toutes.items():
        par_periode = {pid: pp[ad] for pid, pp in perfs.items() if ad in pp}
        if actif and "30j" not in par_periode:
            par_periode["30j"] = {"statut": "test", "but": "notoriete" if "notori" in a["campaign_name"].lower()
                                  else "conversion"}
        if not par_periode:
            continue
        e = entree_annonce(a, actif, images, videos, complements, sources, manquantes)
        if e:
            e["perfs"] = par_periode
            annonces.append(e)
    absentes = {ad for pp in perfs.values() for ad in pp} - set(toutes)
    if absentes:
        print(f"  {len(absentes)} annonces du rapport sans créa tirée : {sorted(absentes)[:5]}...")
    if manquantes:
        print(f"  {len(manquantes)} vidéos sans fichier (affiche seulement) : {','.join(sorted(manquantes))}")

    ordre_c = {c: i for i, c in enumerate(CIBLAGES)}
    ordre_g = {g: i for i, g in enumerate(ORDRE_GROUPES)}
    annonces.sort(key=lambda a: a["depuis"], reverse=True)
    annonces.sort(key=lambda a: (ordre_c.get(a["ciblage"], 99), ordre_g.get(a["groupe"], 50), a["groupe"]))

    # Les fichiers qui ne servent plus quittent la galerie.
    garder = {Path(x).name for a in annonces
              for x in [a["image"], a["mini"]] + [c[k] for c in a.get("cartes", []) for k in ("image", "mini")]}
    for dossier in (IMAGES, MINIS):
        for f in dossier.glob("*.jpg"):
            if f.name not in garder:
                f.unlink()
    garder_videos = {Path(a["video"]).name for a in annonces if a.get("video")}
    for f in VIDEOS.glob("*.mp4"):
        if f.name not in garder_videos:
            f.unlink()

    sortie = {"mise_a_jour": args.date, "fin": fin, "periodes": liste_periodes, "annonces": annonces}
    (RACINE / "annonces.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=1))
    print(f"{len(annonces)} annonces, dont {sum(a['actif'] for a in annonces)} actives")
    for pe in liste_periodes:
        st = Counter(a["perfs"][pe["id"]]["statut"] for a in annonces if pe["id"] in a["perfs"])
        nv = Counter(a["perfs"][pe["id"]].get("niveau") for a in annonces
                     if a["perfs"].get(pe["id"], {}).get("niveau"))
        print(f"  {pe['libelle']} ({pe['debut']} au {pe['fin_juge']}, {RESULTATS[pe['conversion']]}) : "
              f"{sum(st.values())} visuels, {st['juge']} jugés {dict(nv)}, {st['test']} en test, "
              f"{st['court']} trop courts, {st['peu']} peu diffusés")


if __name__ == "__main__":
    main()
