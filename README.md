# Visuels

Galeries des visuels publicitaires en ligne, une par client, servies par
GitHub Pages. Pages non indexées (`noindex`), mais le dépôt est public :
n'y mettre que des visuels déjà diffusés.

- FloorBox : `floorbox/` → https://coldkendama.github.io/visuels/floorbox/

## Sélection « à revoir »

Chaque visuel a un bouton « Sélectionner » et un champ de note ; la barre du
bas envoie la sélection par courriel au propriétaire du script
[`outils/apps-script/Envoi.gs`](outils/apps-script/Envoi.gs), une
application Web Apps Script (« Exécuter en tant que : Moi », « Qui a accès :
Tout le monde »). Son URL `/exec` est la constante `ENVOI` de la page. Un
nouveau client : l'ajouter dans `CLIENTS` du script et redéployer
(« Gérer les déploiements » > modifier > « Nouvelle version », même URL).

## Indice de performance

Le chiffre posé sur chaque visuel compare ses résultats par dollar (achats,
ou demandes de soumission pour les campagnes `askforquote`) à la moyenne de
son ad set, quand au moins deux annonces y ont livré, sinon de sa campagne.
100 = la moyenne. La référence compte toutes les annonces qui ont livré,
actives ou non.

- **Jours fermés seulement** : l'indice s'arrête 7 jours avant la fin des
  données, parce que Meta attribue encore les conversions des 7 derniers
  jours. Le taux de clic (accroche) et la part du budget des 7 derniers jours
  vont jusqu'à la veille.
- **Pas de verdict sans budget** : il faut une dépense qui, à la moyenne du
  groupe, aurait acheté au moins 3 résultats. Sinon « en test » (moins de 7
  jours fermés, verdict 14 jours après la première diffusion) ou « peu
  diffusée ».
- **Niveaux** : 115 et plus performant, 90 à 114 dans la moyenne, sous 90 à
  surveiller, sous 77 sous la moyenne quand la preuve tient (Poisson,
  p ≤ 0,20). Fiabilité élevée à p ≤ 0,05, moyenne à p ≤ 0,20.
- **Aucun montant publié par défaut** (ni dépense, ni nombre d'achats, ni
  coût) : le dépôt est public. `--montants` les ajoute ; ne pas l'activer sans
  l'accord du client.

## Ajouter des visuels à la main

Déposer les images (jpg, png, webp) dans `floorbox/ajouts/<Section>/`, par
exemple `floorbox/ajouts/Courriels/`. Le nom du sous-dossier devient le titre
de la section, le nom du fichier devient le titre du visuel. Puis relancer
la construction et pousser.

## Mettre à jour depuis Meta

1. Tirer par Markifact, pour chaque compte (CA et US) :
   `meta_ads_list_ads` (`ad_effective_status: ["ACTIVE"]`),
   `meta_ads_list_media` (`media_type: IMAGE`, `limit: 500`) et, pour
   l'indice, `meta_ads_get_report` du `--depuis` à la veille
   (`preset: FIXED`), dimensions `date, campaignId, campaignName, objective,
   optimizationGoal, adsetId, adsetName, adId, adName`, métriques `cost,
   impressions, linkClicks, landingPageViews, results, purchases,
   addToCart`, filtre `impressions GREATER_THAN 0`, `limit: 20000`.
2. Construire :

   ```bash
   python3 -I outils/construire_floorbox.py \
     --ca-ads ca.json --ca-media ca_media.json \
     --us-ads us.json --us-media us_media.json \
     --ca-perf perf_ca.json --us-perf perf_us.json \
     --depuis 2026-09-28 --date AAAA-MM-JJ
   ```

   Une image 4:5 par annonce active créée depuis `--depuis` ; les images
   des annonces qui ne roulent plus sont retirées. Sans `--ca-perf` et
   `--us-perf`, la galerie s'affiche sans indice.
3. `git add -A && git commit -m "FloorBox : mise à jour du AAAA-MM-JJ" && git push`
