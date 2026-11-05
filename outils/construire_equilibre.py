"""Construit la galerie Équilibre : annonces.json, donnees.bin, les images et les vidéos.

Entrées : sorties Markifact du compte act_807927256273007 (voir le README) :
meta_ads_list_ads (les annonces actives, plus celles qui ont livré depuis
juillet), meta_ads_get_media_details (images et vidéos), meta_ads_get_report
par jour et par annonce depuis juillet, les sources des vidéos (lues avec le
jeton de la Page) et un fichier de compléments pour les vidéos Legacy.

    python3 -I outils/construire_equilibre.py \
        --ads annonces.json annonces_historiques.json --medias medias_*.json \
        --perf perf.json --complements complements.json --sources sources.json \
        --date 2026-11-04

annonces.json (public) décrit chaque annonce : visuel, textes, catégorie de
ciblage, ad set. donnees.bin porte ses chiffres par jour, chiffrés : la page
les lit avec la clé passée dans le lien (#k=...) et calcule l'indice sur la
plage de dates choisie, contre la moyenne de l'ad set, sur le but de l'ad
set : View Content en conversion depuis le 5 octobre, website_schedule avant
(jusqu'au 26 septembre), vues de page pour les ad sets de notoriété. Aucun
montant n'est lisible sans la clé, et la dépense y est en unités relatives.
"""

import argparse
import base64
import gzip
import hashlib
import json
import re
import secrets
import subprocess
import tempfile
import urllib.request
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent / "equilibre"
IMAGES = RACINE / "images"
MINIS = IMAGES / "min"
VIDEOS = RACINE / "videos"
CLE = Path.home() / ".config" / "visuels" / "equilibre.cle"   # jamais dans le dépôt
ADRESSE = "https://coldkendama.github.io/visuels/equilibre/"

PASSAGE_VC = "2026-10-05"     # premiers ad sets optimisés sur View Content
FIN_SCHEDULE = "2026-09-26"   # dernier jour où Meta voit website_schedule (compte classé santé)
METRIQUES = {"vc": "websiteViewContent", "rdv": "websiteAppointmentsScheduled", "lpv": "landingPageViews"}

# Ordre d'affichage des catégories de ciblage et des ad sets.
CIBLAGES = ["Scale", "Marchés rouges", "Local", "Spécialisé", "Notoriété", "Test"]
ORDRE_GROUPES = ["Scale AP", "Scale OP", "Rouges prioritaires AP", "Rouges bulk AP", "Rouges prioritaires OP",
                 "Rouges OP", "Genou DR", "Pédiatrie OP", "Vidéos de notoriété AP", "Test AP", "Test OP"]


def jour(iso, decalage=0):
    return (date.fromisoformat(iso) + timedelta(days=decalage)).isoformat()


def but(r):
    """Le résultat qui juge cette ligne du rapport, ou None (boosts, website_schedule devenu invisible)."""
    g = r["adsetName"].lower()
    if "Engagement" in r["campaignName"]:
        return None
    if r["optimizationGoal"] == "LANDING_PAGE_VIEWS":
        return "lpv"
    if r["optimizationGoal"] == "OFFSITE_CONVERSIONS":
        if "viewcontent" in g:
            return "vc" if r["date"] >= PASSAGE_VC else None
        return "rdv" if r["date"] <= FIN_SCHEDULE else None
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


# Chiffres par jour, chiffrés ------------------------------------------------

def exporter_jours(lignes, fin, montants):
    """Les chiffres par annonce et par jour, que la page recalcule pour la plage choisie.

    Une annonce : [id, but, ad set, campagne, premier jour livré]. Une ligne :
    [annonce, jour, dépense, impressions, clics, résultats, vues de 3 s, ThruPlay],
    les jours comptés depuis le premier jour des données. La dépense est en
    unités relatives (part du total, × 10⁸) : l'indice ne dépend que des
    rapports entre dépenses. Avec --montants, elle est en cents.
    """
    premier = {}
    for r in lignes:
        if r["impressions"]:
            premier[r["adId"]] = min(premier.get(r["adId"], r["date"]), r["date"])
    debut = min(premier.values())
    garder = [(r, b) for r in lignes if r["impressions"] and (b := but(r))]
    total = sum(r["cost"] for r, _ in garder) or 1
    echelle = 100 if montants else 1e8 / total
    rang, annonces, sortie = {}, [], []
    for r, b in sorted(garder, key=lambda x: (x[0]["adId"], x[0]["date"])):
        ad = r["adId"]
        if ad not in rang:
            rang[ad] = len(annonces)
            annonces.append([ad, b, r["adsetId"], r["campaignId"], (date.fromisoformat(premier[ad])
                                                                   - date.fromisoformat(debut)).days])
        elif annonces[rang[ad]][1] != b:
            print(f"  but changeant pour {ad} ({annonces[rang[ad]][1]}, {b}) : garde le premier")
        sortie.append([rang[ad], (date.fromisoformat(r["date"]) - date.fromisoformat(debut)).days,
                       round(r["cost"] * echelle), r["impressions"], r["linkClicks"], r[METRIQUES[b]],
                       r["videoViews"], r["thruPlays"]])
    return {"debut": debut, "fin": fin, "montants": montants, "annonces": annonces, "lignes": sortie}


def cle_de_lecture():
    """La clé qui chiffre les chiffres par jour : hors du dépôt, la même d'une construction à l'autre."""
    if not CLE.exists():
        CLE.parent.mkdir(parents=True, exist_ok=True)
        CLE.write_text(secrets.token_hex(32) + "\n")
        CLE.chmod(0o600)
        print(f"  NOUVELLE CLÉ dans {CLE} : les liens envoyés avant ne montrent plus les indices")
    return bytes.fromhex(CLE.read_text().strip())


def chiffrer(clair, cle):
    """AES-256-CBC par openssl, le vecteur d'initialisation en tête ; la page déchiffre par WebCrypto."""
    iv = secrets.token_bytes(16)
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-K", cle.hex(), "-iv", iv.hex()],
                       input=clair, capture_output=True, check=True)
    return iv + r.stdout


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
                   help="meta_ads_list_ads : les annonces actives, puis celles qui ont livré depuis juillet")
    p.add_argument("--medias", required=True, nargs="+", help="meta_ads_get_media_details (images, vidéos)")
    p.add_argument("--perf", required=True, help="meta_ads_get_report par jour et par annonce")
    p.add_argument("--complements", help="{story_id: {video_id}} pour les vidéos Legacy")
    p.add_argument("--sources", help="{video_id: url} : le champ source de chaque vidéo, lu avec le jeton de la Page")
    p.add_argument("--date", default=date.today().isoformat(), help="date de mise à jour affichée")
    p.add_argument("--fin", help="dernier jour des données de performance (défaut : la veille de --date)")
    p.add_argument("--montants", action="store_true",
                   help="mettre la dépense en cents et l'afficher, avec résultats et coût (à éviter sans l'accord du client)")
    args = p.parse_args()

    MINIS.mkdir(parents=True, exist_ok=True)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    fin = args.fin or jour(args.date, -1)
    images, videos = charger_medias(args.medias)
    complements = json.loads(Path(args.complements).read_text()) if args.complements else {}
    sources = json.loads(Path(args.sources).read_text()) if args.sources else {}

    # Les chiffres par jour, que la page recalcule pour la plage choisie.
    lignes = [r for r in json.loads(Path(args.perf).read_text()) if r["date"] <= fin]
    jours = exporter_jours(lignes, fin, args.montants)
    livrees = {a[0] for a in jours["annonces"]}

    # Annonces : les actives, et toutes celles qui ont livré depuis le début des données.
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
        if not actif and ad not in livrees:
            continue
        e = entree_annonce(a, actif, images, videos, complements, sources, manquantes)
        if e:
            annonces.append(e)
    absentes = livrees - set(toutes)
    if absentes:
        print(f"  {len(absentes)} annonces du rapport sans créa tirée (comptent dans les moyennes) : "
              f"{sorted(absentes)[:5]}...")
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

    # Chiffré : le dépôt est public, la clé ne voyage que dans le lien.
    cle = cle_de_lecture()
    chiffre = chiffrer(gzip.compress(json.dumps(jours, separators=(",", ":")).encode(), mtime=0), cle)
    (RACINE / "donnees.bin").write_bytes(chiffre)
    sortie = {"mise_a_jour": args.date, "debut": jours["debut"], "fin": fin,
              "version": hashlib.sha256(chiffre).hexdigest()[:12], "annonces": annonces}
    (RACINE / "annonces.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=1))

    buts = Counter(a[1] for a in jours["annonces"])
    print(f"{len(annonces)} annonces dans la galerie, dont {sum(a['actif'] for a in annonces)} actives")
    print(f"  {len(jours['lignes'])} lignes par jour du {jours['debut']} au {fin}, {len(jours['annonces'])} annonces "
          f"({buts['vc']} View Content, {buts['rdv']} website_schedule, {buts['lpv']} vues de page), "
          f"{len(chiffre) // 1024} Ko chiffrés")
    print(f"  lien complet : {ADRESSE}#k={base64.urlsafe_b64encode(cle).decode().rstrip('=')}")


if __name__ == "__main__":
    main()
