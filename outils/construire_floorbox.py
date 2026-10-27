"""Construit floorbox/annonces.json et les images de la galerie FloorBox.

Entrées : les sorties Markifact de meta_ads_list_ads (ad_effective_status
ACTIVE) et de meta_ads_list_media (IMAGE) pour les comptes CA et US.

    python3 outils/construire_floorbox.py \
        --ca-ads ca.json --ca-media ca_media.json \
        --us-ads us.json --us-media us_media.json \
        --depuis 2026-09-28 --date 2026-10-27

Une image 4:5 par annonce (sinon le format le plus proche). Les images
déposées dans floorbox/ajouts/<Section>/ sont ajoutées telles quelles.
"""

import argparse
import json
import re
import subprocess
import urllib.request
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent / "floorbox"
IMAGES = RACINE / "images"
MINIS = IMAGES / "min"
AJOUTS = RACINE / "ajouts"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

MARQUES = {
    "ardex": "Ardex", "laticrete": "Laticrete", "mapei": "Mapei", "rubi": "Rubi",
    "schluter": "Schluter", "fuzion": "Fuzion", "centura": "Centura",
    "p1867": "Planchers 1867", "biyork": "Biyork", "next-floor": "Next Floor",
    "nf": "Next Floor", "armstrong": "Armstrong", "arm": "Armstrong",
    "deals": "Deal Store", "manubric": "Manubric", "dpa": "Toutes les marques",
}

# Ordre d'affichage des sections, par pays.
SECTIONS = ["Brands We Trust", "Schluter", "Planchers", "Deal Store", "Manubric"]


def marque(nom):
    for cle in sorted(MARQUES, key=len, reverse=True):
        if nom == cle or nom.startswith(cle + "-"):
            return MARQUES[cle]
    return ""


def section(annonce):
    nom, campagne = annonce["name"], annonce["campaign_name"]
    if nom.startswith("schluter"):
        return "Schluter"
    if "flooring" in campagne:
        return "Planchers"
    if nom.startswith("deals"):
        return "Deal Store"
    if nom.startswith("manubric"):
        return "Manubric"
    return "Brands We Trust"


def langue(annonce):
    nom, adset = annonce["name"], annonce["adset_name"]
    return "FR" if nom.endswith("-fr") or "-fr-" in adset else "EN"


def choisir_image(annonce, medias):
    """Le hash 4:5 de l'annonce, sinon le plus proche ; la carte fixe d'un DPA."""
    hashes = [i["hash"] for i in annonce.get("creative_asset_feed_spec_images") or []]
    for carte in annonce.get("creative_object_story_spec_template_data_child_attachments") or []:
        if carte.get("static_card") and carte.get("image_hash"):
            hashes.append(carte["image_hash"])
    candidats = [medias[h] for h in hashes if h in medias]
    if not candidats:
        return None
    return min(candidats, key=lambda m: abs(m["height"] / m["width"] - 1.25))


def textes(annonce):
    titres = [t["text"] for t in annonce.get("creative_asset_feed_spec_titles") or []]
    corps = [t["text"] for t in annonce.get("creative_asset_feed_spec_bodies") or []]
    for carte in annonce.get("creative_object_story_spec_template_data_child_attachments") or []:
        if carte.get("static_card") and carte.get("name"):
            titres = [carte["name"]]
    titres = [t for t in titres if "{{" not in t]
    return (titres[0] if titres else ""), (corps[0] if corps else "")


def telecharger(url, cible):
    if cible.exists():
        return
    with urllib.request.urlopen(url, timeout=60) as r:
        cible.write_bytes(r.read())


def miniature(source, cible, largeur=540):
    if cible.exists() and cible.stat().st_mtime >= source.stat().st_mtime:
        return
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "80",
                    "--resampleWidth", str(largeur), str(source), "--out", str(cible)],
                   check=True, capture_output=True)


def slug(texte):
    return re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")


def annonces_meta(pays, fichier_ads, fichier_medias, depuis):
    medias = {m["image_hash"]: m for m in json.loads(Path(fichier_medias).read_text())}
    sortie = []
    for a in json.loads(Path(fichier_ads).read_text()):
        if a["effective_status"] != "ACTIVE" or a["created_time"][:10] < depuis:
            continue
        image = choisir_image(a, medias)
        if image is None:
            print(f"  sans visuel fixe, ignorée : {pays} {a['name']}")
            continue
        fichier = f"{pays.lower()}-{a['name']}.jpg"
        telecharger(image["url"], IMAGES / fichier)
        miniature(IMAGES / fichier, MINIS / fichier)
        titre, corps = textes(a)
        sortie.append({
            "pays": pays, "section": section(a), "marque": marque(a["name"]),
            "langue": langue(a), "titre": titre, "texte": corps,
            "depuis": a["created_time"][:10], "image": f"images/{fichier}",
            "mini": f"images/min/{fichier}",
        })
    return sortie


def ajouts():
    """Images déposées à la main dans ajouts/<Section>/ (ou ajouts/ directement)."""
    sortie = []
    for chemin in sorted(AJOUTS.rglob("*")):
        if chemin.suffix.lower() not in EXTENSIONS:
            continue
        rel = chemin.relative_to(AJOUTS)
        sect = rel.parts[0] if len(rel.parts) > 1 else "Autres visuels"
        fichier = "ajout-" + slug(str(rel.with_suffix(""))) + ".jpg"
        miniature(chemin, MINIS / fichier)
        sortie.append({
            "pays": "", "section": sect, "marque": "", "langue": "",
            "titre": chemin.stem.replace("-", " ").replace("_", " "), "texte": "",
            "depuis": date.fromtimestamp(chemin.stat().st_mtime).isoformat(),
            "image": f"ajouts/{rel.as_posix()}", "mini": f"images/min/{fichier}",
        })
    return sortie


def main():
    p = argparse.ArgumentParser()
    for opt in ("--ca-ads", "--ca-media", "--us-ads", "--us-media"):
        p.add_argument(opt, required=True)
    p.add_argument("--depuis", required=True, help="date de création minimale, AAAA-MM-JJ")
    p.add_argument("--date", default=date.today().isoformat(), help="date de mise à jour affichée")
    args = p.parse_args()

    MINIS.mkdir(parents=True, exist_ok=True)
    AJOUTS.mkdir(parents=True, exist_ok=True)
    annonces = (annonces_meta("CA", args.ca_ads, args.ca_media, args.depuis)
                + annonces_meta("US", args.us_ads, args.us_media, args.depuis)
                + ajouts())

    # Par pays, section et marque ; les plus récentes d'abord dans chaque marque.
    ordre_sect = {s: i for i, s in enumerate(SECTIONS)}
    annonces.sort(key=lambda a: a["depuis"], reverse=True)
    annonces.sort(key=lambda a: (a["pays"] == "", a["pays"], ordre_sect.get(a["section"], 99),
                                 a["marque"]))
    # Les fichiers d'annonces qui ne roulent plus quittent la galerie.
    garder = {Path(a["image"]).name for a in annonces} | {Path(a["mini"]).name for a in annonces}
    for dossier in (IMAGES, MINIS):
        for f in dossier.glob("*.jpg"):
            if f.name not in garder:
                f.unlink()

    (RACINE / "annonces.json").write_text(json.dumps(
        {"mise_a_jour": args.date, "annonces": annonces}, ensure_ascii=False, indent=1))
    print(f"{len(annonces)} visuels : "
          f"{sum(a['pays'] == 'CA' for a in annonces)} CA, "
          f"{sum(a['pays'] == 'US' for a in annonces)} US, "
          f"{sum(a['pays'] == '' for a in annonces)} ajouts")


if __name__ == "__main__":
    main()
