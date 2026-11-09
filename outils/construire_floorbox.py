"""Construit la galerie FloorBox : annonces.json, donnees.bin et les images.

Entrées : sorties Markifact des comptes FloorBox CA (act_681027176176924) et US
(act_1418004975723866), connexion Meta 63ab1d5f (voir le README) :
meta_ads_list_ads (les annonces actives, puis celles qui ont livré sans l'être),
meta_ads_list_media (IMAGE) et meta_ads_get_report par jour et par annonce.

    python3 -I outils/construire_floorbox.py \
        --ca-ads ca_actives.json ca_historiques.json --ca-medias ca_medias.json --ca-perf ca_perf.json \
        --us-ads us_actives.json us_historiques.json --us-medias us_medias.json --us-perf us_perf.json \
        --depuis 2026-09-28 --date 2026-11-09

annonces.json (public) décrit les annonces créées depuis --depuis : visuel, textes, pays,
campagne (section), marque, langue, et la carte du visuel (les copies d'un même visuel
partagent une carte). donnees.bin porte les chiffres par annonce et par jour, chiffrés :
la page les lit avec la clé passée dans le lien (#k=...) et calcule l'indice sur la plage
de dates choisie (achats, ou demandes de soumission pour les campagnes askforquote, par
dollar, chaque copie contre son ad set, puis additionnées). Aucun montant n'est lisible
sans la clé, et la dépense y est en unités relatives.
"""

import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import secrets
import tempfile
import urllib.request
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("equilibre", ICI / "construire_equilibre.py")
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)          # chiffrer, image_principale, sips : les mêmes que pour Équilibre

RACINE = ICI.parent / "floorbox"
IMAGES = RACINE / "images"
MINIS = IMAGES / "min"
CLE = Path.home() / ".config" / "visuels" / "floorbox.cle"   # jamais dans le dépôt
ADRESSE = "https://coldkendama.github.io/visuels/floorbox/"

MARQUES = {
    "ardex": "Ardex", "laticrete": "Laticrete", "mapei": "Mapei", "rubi": "Rubi",
    "schluter": "Schluter", "fuzion": "Fuzion", "centura": "Centura",
    "p1867": "Planchers 1867", "biyork": "Biyork", "next-floor": "Next Floor",
    "nf": "Next Floor", "armstrong": "Armstrong", "arm": "Armstrong",
    "deals": "Deal Store", "manubric": "Manubric", "dpa": "Toutes les marques",
}
SECTIONS = ["Brands We Trust", "Schluter", "Planchers", "Deal Store", "Manubric"]   # ordre d'affichage, par pays
PAYS = ["CA", "US"]


def jour(iso, decalage=0):
    return (date.fromisoformat(iso) + timedelta(days=decalage)).isoformat()


def but(r):
    """Le résultat de la ligne : demandes de soumission (askforquote) ou achats."""
    return "soum" if "quote" in r["campaignName"].lower() else "achat"


def marque(nom):
    for cle in sorted(MARQUES, key=len, reverse=True):
        if nom == cle or nom.startswith(cle + "-"):
            return MARQUES[cle]
    return ""


def section(annonce):
    nom, campagne = annonce["name"], annonce["campaign_name"]
    if nom.startswith("schluter"):
        return "Schluter"
    if "flooring" in campagne or nom.startswith(("arm-", "nf-")):
        return "Planchers"
    if nom.startswith("deals"):
        return "Deal Store"
    if nom.startswith("manubric"):
        return "Manubric"
    return "Brands We Trust"


def langue(annonce):
    nom, adset = annonce["name"], annonce["adset_name"]
    return "FR" if nom.endswith("-fr") or "-fr-" in adset else "EN"


def hashes_annonce(a):
    """Les images que l'annonce déclare : feed, carte fixe d'un DPA, image du lien."""
    h = [i["hash"] for i in a.get("creative_asset_feed_spec_images") or []]
    for carte in a.get("creative_object_story_spec_template_data_child_attachments") or []:
        if carte.get("static_card") and carte.get("image_hash"):
            h.append(carte["image_hash"])
    if a.get("creative_object_story_spec_link_data_image_hash"):
        h.append(a["creative_object_story_spec_link_data_image_hash"])
    return h


def textes(a):
    titres = [t["text"] for t in a.get("creative_asset_feed_spec_titles") or []]
    corps = [t["text"] for t in a.get("creative_asset_feed_spec_bodies") or []]
    for carte in a.get("creative_object_story_spec_template_data_child_attachments") or []:
        if carte.get("static_card") and carte.get("name"):
            titres = [carte["name"]]
    titres = [t for t in titres if "{{" not in t]
    return (titres[0] if titres else ""), (corps[0] if corps else "")


def preparer(cle, url):
    """Télécharge le visuel une fois, en JPEG de 1350 px au plus, avec sa miniature de 540 px."""
    fichier = cle + ".jpg"
    image, mini = IMAGES / fichier, MINIS / fichier
    if not image.exists():
        with tempfile.TemporaryDirectory() as tmp:
            brut = Path(tmp) / "brut"
            with urllib.request.urlopen(url, timeout=60) as r:
                brut.write_bytes(r.read())
            E.sips(brut, image, "-s", "formatOptions", "85", "-Z", "1350")
    if not mini.exists() or mini.stat().st_mtime < image.stat().st_mtime:
        E.sips(image, mini, "-s", "formatOptions", "80", "--resampleWidth", "540")
    return f"images/{fichier}", f"images/min/{fichier}"


def cle_de_lecture():
    """La clé qui chiffre les chiffres par jour : hors du dépôt, la même d'une construction à l'autre."""
    if not CLE.exists():
        CLE.parent.mkdir(parents=True, exist_ok=True)
        CLE.write_text(secrets.token_hex(32) + "\n")
        CLE.chmod(0o600)
        print(f"  NOUVELLE CLÉ dans {CLE} : les liens envoyés avant ne montrent plus les indices")
    return bytes.fromhex(CLE.read_text().strip())


def exporter_jours(lignes, fin, montants):
    """Les chiffres par annonce et par jour, que la page recalcule pour la plage choisie.

    Une annonce : [id, but, ad set, campagne, premier jour livré]. Une ligne :
    [annonce, jour, dépense, impressions, clics, résultats], les jours comptés depuis le
    premier jour des données. La dépense est en unités relatives (part du total, × 10⁸) :
    l'indice ne dépend que des rapports entre dépenses d'un même compte. Avec --montants,
    elle est en cents (CAD au Canada, USD aux États-Unis).
    """
    lignes = [r for r in lignes if r["impressions"]]
    premier = {}
    for r in lignes:
        premier[r["adId"]] = min(premier.get(r["adId"], r["date"]), r["date"])
    debut = min(premier.values())
    total = sum(r["cost"] for r in lignes) or 1
    echelle = 100 if montants else 1e8 / total
    rang, annonces, sortie = {}, [], []
    for r in sorted(lignes, key=lambda x: (x["adId"], x["date"])):
        ad = r["adId"]
        if ad not in rang:
            rang[ad] = len(annonces)
            annonces.append([ad, but(r), r["adsetId"], r["campaignId"],
                             (date.fromisoformat(premier[ad]) - date.fromisoformat(debut)).days])
        sortie.append([rang[ad], (date.fromisoformat(r["date"]) - date.fromisoformat(debut)).days,
                       round(r["cost"] * echelle), r["impressions"], r["linkClicks"], r["results"]])
    return {"debut": debut, "fin": fin, "montants": montants, "annonces": annonces, "lignes": sortie}


def cartes_par_visuel(entrees, empreintes):
    """Une carte par visuel : deux annonces vont ensemble quand elles portent le même nom dans le
    même pays et la même campagne, et que les images de l'une sont toutes dans l'autre (une annonce
    relancée dans une nouvelle campagne, par exemple). Les versions FR et EN, et les formats
    static et collection d'une même image, restent séparés : la langue est un filtre, et le format
    est un test. La carte prend l'identifiant le plus petit de ses copies, stable d'un jour à
    l'autre (la sélection du client y reste attachée)."""
    parent = list(range(len(entrees)))

    def racine(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(entrees)):
        for j in range(i + 1, len(entrees)):
            a, b = entrees[i], entrees[j]
            if (a["pays"], a["section"], a["nom"]) == (b["pays"], b["section"], b["nom"]) and (
                    empreintes[i] <= empreintes[j] or empreintes[j] <= empreintes[i]):
                parent[racine(i)] = racine(j)
    groupes = {}
    for i, e in enumerate(entrees):
        groupes.setdefault(racine(i), []).append(e["id"])
    for i, e in enumerate(entrees):
        e["carte"] = min(groupes[racine(i)])


def main():
    p = argparse.ArgumentParser()
    for pays in PAYS:
        x = pays.lower()
        p.add_argument(f"--{x}-ads", required=True, nargs="+",
                       help="meta_ads_list_ads : les annonces actives, puis celles qui ont livré sans l'être")
        p.add_argument(f"--{x}-medias", required=True, help="meta_ads_list_media (IMAGE)")
        p.add_argument(f"--{x}-perf", required=True, help="meta_ads_get_report par jour et par annonce")
    p.add_argument("--depuis", required=True, help="date de création minimale des annonces montrées, AAAA-MM-JJ")
    p.add_argument("--date", default=date.today().isoformat(), help="date de mise à jour affichée")
    p.add_argument("--fin", help="dernier jour des données de performance (défaut : la veille de --date)")
    p.add_argument("--montants", action="store_true",
                   help="mettre la dépense en cents et l'afficher, avec résultats et coût (à éviter sans l'accord du client)")
    args = p.parse_args()

    MINIS.mkdir(parents=True, exist_ok=True)
    fin = args.fin or jour(args.date, -1)

    lignes, annonces, empreintes = [], [], []
    for pays in PAYS:
        x = pays.lower()
        lignes += [r for r in json.loads(Path(getattr(args, f"{x}_perf")).read_text()) if r["date"] <= fin]
        medias = {}
        for m in json.loads(Path(getattr(args, f"{x}_medias")).read_text()):
            medias[m["image_hash"]] = {**m, "hash": m["image_hash"]}
        toutes = {}
        for i, fichier in enumerate(getattr(args, f"{x}_ads")):
            for a in json.loads(Path(fichier).read_text()):
                actif = i == 0 and a["effective_status"] == "ACTIVE"
                if a["id"] not in toutes or actif:
                    toutes[a["id"]] = (a, actif)
        livrees_pays = {r["adId"] for r in lignes if r["impressions"]}
        for ad, (a, actif) in toutes.items():
            if a["created_time"][:10] < args.depuis or not (actif or ad in livrees_pays):
                continue
            hs = hashes_annonce(a)
            candidats = [medias[h] for h in hs if h in medias]
            if not candidats:
                print(f"  sans visuel fixe, ignorée : {pays} {a['name']}")
                continue
            img = E.image_principale(candidats, a["name"])
            image, mini = preparer(img["hash"], img["url"])
            titre, corps = textes(a)
            annonces.append({
                "id": a["id"], "nom": a["name"], "pays": pays, "section": section(a), "marque": marque(a["name"]),
                "langue": langue(a), "actif": actif, "titre": titre, "texte": corps,
                "depuis": a["created_time"][:10], "image": image, "mini": mini,
                "lien": a.get("preview_shareable_link") or "",
            })
            empreintes.append(frozenset(hs))
    cartes_par_visuel(annonces, empreintes)
    jours = exporter_jours(lignes, fin, args.montants)

    ordre = {s: i for i, s in enumerate(SECTIONS)}
    annonces.sort(key=lambda a: a["depuis"], reverse=True)
    annonces.sort(key=lambda a: (PAYS.index(a["pays"]), ordre.get(a["section"], 99), a["marque"]))

    # Les fichiers qui ne servent plus quittent la galerie.
    garder = {Path(x).name for a in annonces for x in (a["image"], a["mini"])}
    for dossier in (IMAGES, MINIS):
        for f in dossier.glob("*.jpg"):
            if f.name not in garder:
                f.unlink()

    # Chiffré : le dépôt est public, la clé ne voyage que dans le lien.
    cle = cle_de_lecture()
    chiffre = E.chiffrer(gzip.compress(json.dumps(jours, separators=(",", ":")).encode(), mtime=0), cle)
    (RACINE / "donnees.bin").write_bytes(chiffre)
    sortie = {"mise_a_jour": args.date, "debut": jours["debut"], "fin": fin,
              "version": hashlib.sha256(chiffre).hexdigest()[:12], "annonces": annonces}
    (RACINE / "annonces.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=1))

    cartes = Counter((a["pays"], a["carte"]) for a in annonces)
    print(f"{len(annonces)} annonces, {len(cartes)} visuels, dont "
          f"{len({a['carte'] for a in annonces if a['actif']})} en ligne")
    for pays in PAYS:
        for s in SECTIONS:
            c = {a["carte"] for a in annonces if (a["pays"], a["section"]) == (pays, s)}
            if c:
                print(f"  {pays} {s} : {len(c)} visuels")
    print(f"  {len(jours['lignes'])} lignes par jour du {jours['debut']} au {fin}, {len(chiffre) // 1024} Ko chiffrés")
    print(f"  lien complet : {ADRESSE}#k={base64.urlsafe_b64encode(cle).decode().rstrip('=')}")


if __name__ == "__main__":
    main()
