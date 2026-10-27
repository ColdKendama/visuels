"""Construit floorbox/annonces.json et les images de la galerie FloorBox.

Entrées : les sorties Markifact de meta_ads_list_ads (ad_effective_status
ACTIVE) et de meta_ads_list_media (IMAGE) pour les comptes CA et US, et,
pour l'indice de performance, meta_ads_get_report par jour et par annonce
(voir le README).

    python3 outils/construire_floorbox.py \
        --ca-ads ca.json --ca-media ca_media.json \
        --us-ads us.json --us-media us_media.json \
        --ca-perf perf_ca.json --us-perf perf_us.json \
        --depuis 2026-09-28 --date 2026-10-27

Une image 4:5 par annonce (sinon le format le plus proche). Les images
déposées dans floorbox/ajouts/<Section>/ sont ajoutées telles quelles.
"""

import argparse
import json
import math
import re
import subprocess
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta
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

# Indice de performance. Les conversions des 7 derniers jours ne sont pas
# toutes attribuées : l'indice s'arrête 7 jours avant la fin des données.
ATTRIBUTION = 7
BUDGET_MIN = 3      # résultats que le budget aurait dû acheter avant de juger (0 sur 3 : p = 0,05)
CLICS_MIN = 15      # clics attendus avant de juger l'accroche


def poisson(k, lam, haut):
    """P(X ≤ k), ou P(X ≥ k) si haut, pour X de Poisson de moyenne lam."""
    bas = sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(int(k) + (0 if haut else 1)))
    return 1 - bas if haut else bas


class Cumul:
    """Totaux d'une annonce, d'un ad set ou d'une campagne, et les annonces qui y ont livré."""

    def __init__(self):
        self.m, self.annonces = Counter(), set()

    def ajouter(self, ad, m):
        self.m.update(m)
        self.annonces.add(ad)


def performance(fichier, fin, montants):
    """Indice par annonce : résultats par dollar contre la moyenne de son ad set.

    fichier : meta_ads_get_report, dimensions date + campagne + ad set + annonce.
    La référence est l'ad set (même audience, même budget) quand au moins deux
    annonces y ont livré, sinon la campagne ; elle compte toutes les annonces
    qui ont livré, actives ou non. Renvoie ({ad_id: perf}, date fermée).
    """
    ferme = (date.fromisoformat(fin) - timedelta(days=ATTRIBUTION)).isoformat()
    recent = (date.fromisoformat(fin) - timedelta(days=ATTRIBUTION - 1)).isoformat()
    # Par fenêtre : tout (jusqu'à fin), ferme (jusqu'à la date fermée), recent (7 derniers jours).
    cumuls = defaultdict(Cumul)
    premier, campagne, groupe = {}, {}, {}
    for r in json.loads(Path(fichier).read_text()):
        if r["date"] > fin or not r["impressions"]:
            continue
        ad, c, g = r["adId"], r["campaignId"], r["adsetId"]
        m = Counter({k: r[k] for k in ("cost", "impressions", "linkClicks", "results")})
        campagne[ad], groupe[ad] = (c, r["campaignName"]), g
        premier[ad] = min(premier.get(ad, r["date"]), r["date"])
        fenetres = ["tout"] + (["ferme"] if r["date"] <= ferme else []) + (["recent"] if r["date"] >= recent else [])
        for fen in fenetres:
            for cle in (("ad", ad), ("groupe", g), ("campagne", c)):
                cumuls[(fen,) + cle].ajouter(ad, m)

    def reference(fen, ad):
        g = cumuls[(fen, "groupe", groupe[ad])]
        return (g, "groupe") if len(g.annonces) > 1 else (cumuls[(fen, "campagne", campagne[ad][0])], "campagne")

    sortie = {}
    for ad, (c, nom_campagne) in campagne.items():
        f, t = cumuls[("ferme", "ad", ad)].m, cumuls[("tout", "ad", ad)].m
        ref_c, niveau_ref = reference("ferme", ad)
        ref, ct = ref_c.m, reference("tout", ad)[0].m
        p = {"resultat": "demandes de soumission" if "quote" in nom_campagne.lower() else "achats",
             "en_ligne": premier[ad], "reference": niveau_ref,
             "nb_reference": len(ref_c.annonces) if niveau_ref == "groupe" else None}

        # Conversion, sur les jours fermés.
        attendus = f["cost"] * ref["results"] / ref["cost"] if ref["results"] else 0
        if attendus >= BUDGET_MIN:
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
        else:
            jours = (date.fromisoformat(ferme) - date.fromisoformat(premier[ad])).days + 1
            if jours < ATTRIBUTION:
                vers = date.fromisoformat(premier[ad]) + timedelta(days=2 * ATTRIBUTION)
                p.update(statut="test", verdict_vers=vers.isoformat())
            else:
                p.update(statut="peu")

        # Accroche : le CTR lien n'attend pas l'attribution, il se lit jusqu'à la fin.
        if t["impressions"]:
            ctr, ctr_moy = t["linkClicks"] / t["impressions"], ct["linkClicks"] / ct["impressions"]
            p.update(ctr=round(ctr * 100, 2), ctr_moy=round(ctr_moy * 100, 2))
            if t["impressions"] * ctr_moy >= CLICS_MIN:
                ratio = ctr / ctr_moy
                p["accroche"] = "forte" if ratio >= 1.15 else "moyenne" if ratio >= 0.85 else "faible"

        # Ce que Meta lui confie dans son ensemble, quand il y a un choix à faire.
        g = cumuls[("recent", "groupe", groupe[ad])]
        if len(g.annonces) > 1 and g.m["cost"]:
            p["part_7j"] = round(cumuls[("recent", "ad", ad)].m["cost"] / g.m["cost"] * 100)

        if montants:
            p.update(depense=round(f["cost"]), resultats=int(f["results"]),
                     cout=round(f["cost"] / f["results"], 2) if f["results"] else None,
                     cout_moy=round(ref["cost"] / ref["results"], 2) if ref["results"] else None)
        sortie[ad] = p
    return sortie, ferme


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


def annonces_meta(pays, fichier_ads, fichier_medias, depuis, perfs):
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
        entree = {
            "id": f"{pays.lower()}-{a['name']}", "nom": a["name"],
            "pays": pays, "section": section(a), "marque": marque(a["name"]),
            "langue": langue(a), "titre": titre, "texte": corps,
            "depuis": a["created_time"][:10], "image": f"images/{fichier}",
            "mini": f"images/min/{fichier}",
        }
        if perfs is not None:
            entree["perf"] = perfs.get(a["id"], {"statut": "test"})
        sortie.append(entree)
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
            "id": fichier[:-4], "nom": rel.as_posix(),
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
    p.add_argument("--ca-perf", help="meta_ads_get_report par jour et par annonce, compte CA")
    p.add_argument("--us-perf", help="idem, compte US")
    p.add_argument("--depuis", required=True, help="date de création minimale, AAAA-MM-JJ")
    p.add_argument("--date", default=date.today().isoformat(), help="date de mise à jour affichée")
    p.add_argument("--fin", help="dernier jour des données de performance (défaut : la veille de --date)")
    p.add_argument("--montants", action="store_true",
                   help="publier aussi dépense, résultats et coût par résultat (dépôt public !)")
    args = p.parse_args()

    MINIS.mkdir(parents=True, exist_ok=True)
    AJOUTS.mkdir(parents=True, exist_ok=True)
    fin = args.fin or (date.fromisoformat(args.date) - timedelta(days=1)).isoformat()
    perf_ca = perf_us = periode = None
    if args.ca_perf and args.us_perf:
        perf_ca, ferme = performance(args.ca_perf, fin, args.montants)
        perf_us, _ = performance(args.us_perf, fin, args.montants)
        periode = {"debut": args.depuis, "ferme": ferme, "fin": fin}
    annonces = (annonces_meta("CA", args.ca_ads, args.ca_media, args.depuis, perf_ca)
                + annonces_meta("US", args.us_ads, args.us_media, args.depuis, perf_us)
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

    sortie = {"mise_a_jour": args.date, "annonces": annonces}
    if periode:
        sortie["performance"] = periode
    (RACINE / "annonces.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=1))
    print(f"{len(annonces)} visuels : "
          f"{sum(a['pays'] == 'CA' for a in annonces)} CA, "
          f"{sum(a['pays'] == 'US' for a in annonces)} US, "
          f"{sum(a['pays'] == '' for a in annonces)} ajouts")
    if periode:
        statuts = Counter(a["perf"]["statut"] for a in annonces if "perf" in a)
        niveaux = Counter(a["perf"]["niveau"] for a in annonces if a.get("perf", {}).get("niveau"))
        print(f"indice au {periode['ferme']} : {statuts['juge']} jugés {dict(niveaux)}, "
              f"{statuts['test']} en test, {statuts['peu']} peu diffusés")


if __name__ == "__main__":
    main()
