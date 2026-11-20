"""Le rapport d'Équilibre tiré par mois donne les mêmes lignes que d'un seul tenant.

    python3 -I outils/test_tirage_equilibre.py                         # sur des données fictives
    python3 -I outils/test_tirage_equilibre.py --reel DOSSIER UNIQUE.json

Le second compare les perf_AAAA-MM.json d'un vrai dossier de tirage à un rapport d'un seul
tenant tiré le même jour (mêmes entrées, du 2026-07-01 à la veille). Il n'imprime que des
comptes, aucun chiffre du client, et n'écrit rien dans le vrai cache.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("tirage", Path(__file__).resolve().parent / "tirage_equilibre.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


def rapport_unique(fin, renommer=None):
    """Un faux rapport d'un seul tenant, du DEBUT à fin : trois annonces par jour."""
    lignes, d = [], date.fromisoformat(T.DEBUT)
    while d <= date.fromisoformat(fin):
        for n in range(3):
            lignes.append({"date": d.isoformat(), "campaignId": f"c{n % 2}", "campaignName": f"AP - Scale {n % 2}",
                           "optimizationGoal": "OFFSITE_CONVERSIONS", "adsetId": f"s{n}",
                           "adsetName": (renommer or {}).get(f"s{n}", f"Ensemble {n} - ViewContent"),
                           "adId": f"a{n}", "adName": f"Annonce {n}", "cost": round(1.37 * d.day + n, 2),
                           "impressions": 100 + d.day, "linkClicks": n, "landingPageViews": 0,
                           "websiteViewContent": d.day % 4, "websiteAppointmentsScheduled": 0,
                           "videoViews": 0, "thruPlays": 0})
        d += timedelta(days=1)
    return lignes


def deposer(travail, unique, mois=None):
    """Coupe un rapport d'un seul tenant en perf_AAAA-MM.json, comme le ferait le tirage par mois."""
    for m, debut, fin in T.tranches(T.DEBUT, max(r["date"] for r in unique)):
        if mois is None or m in mois:
            T.ecrire(travail / f"perf_{m}.json", [r for r in unique if debut <= r["date"] <= fin])


def trier(lignes):
    return sorted(lignes, key=lambda r: (r["date"], r["adId"]))


class Tranches(unittest.TestCase):
    def test_mois_complets_puis_la_veille(self):
        self.assertEqual(T.tranches("2026-07-01", "2026-11-19"), [
            ("2026-07", "2026-07-01", "2026-07-31"), ("2026-08", "2026-08-01", "2026-08-31"),
            ("2026-09", "2026-09-01", "2026-09-30"), ("2026-10", "2026-10-01", "2026-10-31"),
            ("2026-11", "2026-11-01", "2026-11-19")])

    def test_fin_d_annee_et_fevrier(self):
        self.assertEqual(T.tranches("2026-12-15", "2027-03-01"), [
            ("2026-12", "2026-12-15", "2026-12-31"), ("2027-01", "2027-01-01", "2027-01-31"),
            ("2027-02", "2027-02-01", "2027-02-28"), ("2027-03", "2027-03-01", "2027-03-01")])

    def test_entrees_identiques_au_rapport_unique_sauf_les_dates(self):
        e = T.entrees_rapport("2026-11-01", "2026-11-19")
        self.assertEqual(e["date_range"], {"preset": "FIXED", "start": "2026-11-01", "end": "2026-11-19"})
        self.assertEqual(e["limit"], 20000)
        self.assertEqual(e["filters"], [{"field": "impressions", "operator": "GREATER_THAN", "value": "0"}])


class Reunion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        racine = Path(self.tmp.name)
        self.cache = racine / "perf"
        self.jour1, self.jour2 = racine / "tirage-2026-11-20", racine / "tirage-2026-11-21"
        self.jour1.mkdir()
        self.jour2.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_premier_jour_tout_a_tirer_avec_les_entrees_exactes(self):
        lignes, a_tirer = T.rapport(self.jour1, self.cache, "2026-11-19", "2026-11-20")
        self.assertEqual(lignes, [])
        self.assertEqual(a_tirer, [(m, T.entrees_rapport(d, f)) for m, d, f in T.tranches(T.DEBUT, "2026-11-19")])

    def test_les_mois_reunis_donnent_le_rapport_unique(self):
        unique = rapport_unique("2026-11-19")
        deposer(self.jour1, unique)
        lignes, a_tirer = T.rapport(self.jour1, self.cache, "2026-11-19", "2026-11-20")
        self.assertEqual(a_tirer, [])
        self.assertEqual(lignes, trier(unique))
        self.assertEqual(sorted(p.stem for p in self.cache.glob("*.json")),
                         ["2026-07", "2026-08", "2026-09", "2026-10"])   # novembre reste ouvert

    def test_le_lendemain_seul_le_mois_ouvert_se_retire(self):
        deposer(self.jour1, rapport_unique("2026-11-19"))
        T.rapport(self.jour1, self.cache, "2026-11-19", "2026-11-20")
        lignes, a_tirer = T.rapport(self.jour2, self.cache, "2026-11-20", "2026-11-21")
        self.assertEqual(a_tirer, [("2026-11", T.entrees_rapport("2026-11-01", "2026-11-20"))])
        # Un ad set renommé : le rapport d'un seul tenant donnerait le nouveau nom à tous les jours.
        unique = rapport_unique("2026-11-20", renommer={"s1": "Ensemble 1 - Renommé"})
        deposer(self.jour2, unique, mois={"2026-11"})
        lignes, a_tirer = T.rapport(self.jour2, self.cache, "2026-11-20", "2026-11-21")
        self.assertEqual(a_tirer, [])
        self.assertEqual(lignes, trier(unique))

    def test_un_mois_ferme_a_8_jours_de_la_veille(self):
        unique = rapport_unique("2026-12-07")
        deposer(self.jour1, unique, mois={"2026-11", "2026-12"})
        T.rapport(self.jour1, self.cache, "2026-12-07", "2026-12-08")
        self.assertFalse((self.cache / "2026-11.json").exists())   # le 30 novembre peut encore bouger
        unique = rapport_unique("2026-12-08")
        deposer(self.jour2, unique, mois={"2026-11", "2026-12"})
        T.rapport(self.jour2, self.cache, "2026-12-08", "2026-12-09")
        self.assertTrue((self.cache / "2026-11.json").exists())

    def test_un_cache_tire_avec_d_autres_entrees_se_retire(self):
        self.cache.mkdir()
        e = T.entrees_rapport("2026-07-01", "2026-07-31")
        T.ecrire(self.cache / "2026-07.json", {"entrees": {**e, "metrics": ["cost"]}, "tire": "2026-11-01",
                                               "lignes": rapport_unique("2026-07-31")})
        _, a_tirer = T.rapport(self.jour1, self.cache, "2026-11-19", "2026-11-20")
        self.assertIn(("2026-07", e), a_tirer)

    def test_un_mois_incomplet_bloque(self):
        deposer(self.jour1, rapport_unique("2026-11-18"), mois={"2026-11"})
        with self.assertRaises(SystemExit) as fin:
            T.rapport(self.jour1, self.cache, "2026-11-19", "2026-11-20")
        self.assertEqual(fin.exception.code, 3)

    def test_la_limite_de_lignes_bloque(self):
        ligne = rapport_unique("2026-07-01")[0]
        T.ecrire(self.jour1 / "perf_2026-07.json", [{**ligne, "date": "2026-07-31"}] * T.LIMITE)
        with self.assertRaises(SystemExit) as fin:
            T.rapport(self.jour1, self.cache, "2026-11-19", "2026-11-20")
        self.assertEqual(fin.exception.code, 3)


def comparer_reel(dossier, fichier_unique):
    """Les mois d'un vrai dossier, réunis, contre un rapport d'un seul tenant : 0 si identiques."""
    unique = json.loads(Path(fichier_unique).read_text())
    veille = max(r["date"] for r in unique)
    with tempfile.TemporaryDirectory() as tmp:
        lendemain = (date.fromisoformat(veille) + timedelta(days=1)).isoformat()
        reunies, a_tirer = T.rapport(Path(dossier), Path(tmp), veille, lendemain)
    if a_tirer:
        print(f"Mois manquants dans {dossier} : {', '.join(m for m, _ in a_tirer)}")
        return 1
    cle = lambda r: (r["date"], r["adId"])
    a, b = {cle(r): r for r in reunies}, {cle(r): r for r in unique}
    print(f"Par mois : {len(reunies)} lignes ({len(a)} clés date + annonce). "
          f"D'un seul tenant : {len(unique)} lignes ({len(b)} clés), du {min(r['date'] for r in unique)} au {veille}.")
    seulement_mois, seulement_unique = a.keys() - b.keys(), b.keys() - a.keys()
    differentes = {k: sorted(c for c in a[k] if a[k][c] != b[k].get(c)) for k in a.keys() & b.keys()
                   if a[k] != b[k]}
    print(f"Seulement par mois : {len(seulement_mois)}. Seulement d'un seul tenant : {len(seulement_unique)}. "
          f"Lignes différentes : {len(differentes)}.")
    for k, champs in sorted(differentes.items())[:20]:
        print(f"  {k[0]} annonce {k[1]} : {', '.join(champs)}")
    identiques = not (seulement_mois or seulement_unique or differentes) and len(reunies) == len(unique)
    print("IDENTIQUES" if identiques else "DIFFÉRENTS")
    return 0 if identiques else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--reel":
        sys.exit(comparer_reel(sys.argv[2], sys.argv[3]))
    unittest.main()
