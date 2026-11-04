# Visuels

Galeries des visuels publicitaires en ligne, une par client, servies par
GitHub Pages. Pages non indexées (`noindex`), mais le dépôt est public :
n'y mettre que des visuels déjà diffusés.

- FloorBox : `floorbox/` → https://coldkendama.github.io/visuels/floorbox/
- Équilibre : `equilibre/` → https://coldkendama.github.io/visuels/equilibre/
  (lecture seule, sans sélection ; voir la section Équilibre plus bas)

Les sections qui suivent, jusqu'à « Équilibre », décrivent la galerie
FloorBox.

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

## Équilibre

Galerie en lecture seule (ni sélection ni envoi), une carte par annonce
active du compte `act_807927256273007`, publications boostées exclues
(campagne `MOF - Engagement`). Chaque annonce est rangée par **catégorie de
ciblage**, déduite du nom de campagne et d'ad set : Scale, Marchés rouges,
Local, Spécialisé (Genou, Pédiatrie), Notoriété, Test ; puis par ad set.

### Indice : le but de l'ad set décide du résultat

Même calcul que FloorBox (résultats par dollar contre l'ad set, 100 = la
moyenne, budget testé d'au moins 3 résultats, Poisson, pas de rouge sans
preuve), avec le résultat qui suit l'optimisation de l'ad set :

- **Conversion** (`OFFSITE_CONVERSIONS` sur un ad set `ViewContent`) : les
  `websiteViewContent`, étape 4 du formulaire de rendez-vous. Jours fermés
  seulement (7 jours retirés pour l'attribution). Accroche = taux de clic
  sur le lien contre l'ad set.
- **Notoriété** (`LANDING_PAGE_VIEWS`) : les `landingPageViews`, sans délai
  d'attribution, jusqu'à la veille. Arrêt sur la vidéo (vues de 3 s sur
  impressions) et rétention (ThruPlay sur vues de 3 s) contre l'ad set.
- Les ad sets `Schedule` (événement restreint depuis la catégorie santé) et
  les boosts n'entrent ni dans l'indice ni dans la référence.
- « En test » : moins de 7 jours jugés ; verdict 14 jours après la première
  diffusion en conversion, 7 jours en notoriété.
- Le grand format montre le **même visuel dans ses autres groupes** (même
  hash d'image, même vidéo ou même fichier Legacy).
- Aucun montant publié par défaut ; `--montants` les ajoute.

### Mettre à jour depuis Meta

1. Tirer par Markifact (connexion Meta `63ab1d5f-…`) :
   - `meta_ads_list_ads` : `campaign_effective_status`,
     `adset_effective_status` et `ad_effective_status` à `["ACTIVE"]`,
     `include_creative: true`, `limit: 500` → `annonces.json` ;
   - `meta_ads_get_media_details` : les hashes d'images (60 au plus par
     appel) et les `video_id` (**10 au plus par appel**, au-delà l'appel
     expire) → `medias_*.json` ;
   - pour une annonce Legacy vidéo (ni image ni vidéo dans la liste) :
     `meta_ads_get_ad_creative` donne le `video_id`, à mettre dans
     `complements.json` sous l'identifiant de publication
     (`creative_effective_object_story_id`), puis ses détails comme
     ci-dessus ;
   - `meta_ads_get_report` du 2026-10-05 (premiers ad sets `ViewContent`) à
     la veille, `preset: FIXED`, dimensions `date, campaignId, campaignName,
     optimizationGoal, adsetId, adsetName, adId, adName`, métriques `cost,
     impressions, linkClicks, landingPageViews, websiteViewContent,
     videoViews, thruPlays`, filtre `impressions GREATER_THAN 0`,
     `limit: 20000` → `perf.json`.
2. Construire (les liens d'images Meta expirent en quelques jours :
   construire le jour du tirage) :

   ```bash
   python3 -I outils/construire_equilibre.py --ads annonces.json \
     --medias medias_*.json --perf perf.json --complements complements.json \
     --date AAAA-MM-JJ
   ```

3. `git add -A && git commit -m "Équilibre : mise à jour du AAAA-MM-JJ" && git push`
