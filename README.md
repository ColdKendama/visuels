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

## Ajouter des visuels à la main

Déposer les images (jpg, png, webp) dans `floorbox/ajouts/<Section>/`, par
exemple `floorbox/ajouts/Courriels/`. Le nom du sous-dossier devient le titre
de la section, le nom du fichier devient le titre du visuel. Puis relancer
la construction et pousser.

## Mettre à jour depuis Meta

1. Tirer par Markifact, pour chaque compte (CA et US) :
   `meta_ads_list_ads` (`ad_effective_status: ["ACTIVE"]`) et
   `meta_ads_list_media` (`media_type: IMAGE`, `limit: 500`).
2. Construire :

   ```bash
   python3 -I outils/construire_floorbox.py \
     --ca-ads ca.json --ca-media ca_media.json \
     --us-ads us.json --us-media us_media.json \
     --depuis 2026-09-28 --date AAAA-MM-JJ
   ```

   Une image 4:5 par annonce active créée depuis `--depuis` ; les images
   des annonces qui ne roulent plus sont retirées.
3. `git add -A && git commit -m "FloorBox : mise à jour du AAAA-MM-JJ" && git push`
