# Visuels

Galeries des visuels publicitaires en ligne, une par client, servies par
GitHub Pages. Pages non indexées (`noindex`), mais le dépôt est public :
n'y mettre que des visuels déjà diffusés.

- FloorBox : `floorbox/` → https://coldkendama.github.io/visuels/floorbox/
  (sélection des visuels à revoir ; voir la section FloorBox)
- Équilibre : `equilibre/` → https://coldkendama.github.io/visuels/equilibre/
  (lecture seule, sans sélection ; voir la section Équilibre plus bas)

Les deux galeries partagent la même mécanique depuis le 2026-11-09 :
sélecteur de dates à la Google Analytics, filtres en menus déroulants,
chiffres par annonce et par jour chiffrés dans le dépôt (la clé voyage dans
le lien, après le `#`), indice recalculé dans la page, une carte par visuel.

## FloorBox

Comptes Meta CA `act_681027176176924` et US `act_1418004975723866`, connexion
Markifact `63ab1d5f-…` (la seule qui les voit). Les annonces montrées sont
celles **créées depuis le 2026-09-28** (les plus anciennes ne sont pas de
Cardigan), en ligne ou qui ont livré pendant les dates choisies. Sections :
pays, puis campagne (Brands We Trust, Schluter, Planchers, Deal Store,
Manubric). Filtres : statut, pays, langue, campagne, tri.

### Sélection « à revoir »

Chaque visuel a un bouton « Sélectionner » et un champ de note ; la barre du
bas envoie la sélection par courriel au propriétaire du script
[`outils/apps-script/Envoi.gs`](outils/apps-script/Envoi.gs), une
application Web Apps Script (« Exécuter en tant que : Moi », « Qui a accès :
Tout le monde »). Son URL `/exec` est la constante `ENVOI` de la page. Un
nouveau client : l'ajouter dans `CLIENTS` du script et redéployer
(« Gérer les déploiements » > modifier > « Nouvelle version », même URL). La
sélection est gardée dans le navigateur par carte (l'identifiant Meta le plus
petit de ses copies, stable d'un jour à l'autre).

### Indice de performance

Le chiffre posé sur chaque visuel compare ses **ventes + demandes de
soumission** par dollar à la moyenne de son ad set, quand au moins deux
annonces y ont livré, sinon de sa campagne, sur les dates choisies. 100 = la
moyenne. Les deux événements comptent dans **toutes** les campagnes (décision
de Chrysto du 2026-11-10) : avant, une campagne d'achat ne comptait que ses
ventes et une campagne `askforquote` que ses soumissions, et 21 visuels sur
125 étaient jugés sur 30 jours au lieu de 27. Ventes = métrique `purchases`
du rapport Markifact ; soumissions = `offsite_conversion.fb_pixel_custom.AskForQuote`
du champ `conversions` des insights Graph (le rapport Markifact ne l'a pas :
`customPixelEvents` additionne tous les événements personnalisés). Dans les
campagnes `askforquote`, ce champ égale le « résultat » de Meta (vérifié le
2026-11-10 : 121 contre 123 au Canada, 40 contre 40 aux États-Unis). La référence compte toutes les
annonces qui ont livré, actives ou non, y compris celles d'avant le
2026-09-28.

- **Une carte par visuel** : une annonce relancée sous le même nom dans une
  autre campagne (Armstrong et Next Floor aux États-Unis) se réunit avec sa
  copie quand les images de l'une sont toutes dans l'autre ; chaque copie est
  comparée à son ad set, puis résultats obtenus et attendus s'additionnent.
  Les versions FR et EN, et les formats static et collection d'une même
  image, restent séparés (la langue est un filtre, le format est un test).
- **Jours fermés seulement** : l'indice s'arrête 7 jours avant la fin des
  données, parce que Meta attribue encore les conversions des 7 derniers
  jours. Le taux de clic (accroche) et la part du budget vont jusqu'à la
  veille.
- **Pas de verdict sans budget** : il faut une dépense qui, à la moyenne du
  groupe, aurait acheté au moins 3 résultats. Sinon « en test » (moins de 7
  jours jugés, verdict 14 jours après la première diffusion), « trop court »,
  « peu diffusé » ou « période courte ».
- **Niveaux** : 115 et plus performant, 90 à 114 dans la moyenne, sous 90 à
  surveiller, sous 77 sous la moyenne quand la preuve tient (Poisson,
  p ≤ 0,20). Fiabilité élevée à p ≤ 0,05, moyenne à p ≤ 0,20.
- **L'image montrée** : la plus proche du 4:5, avec la même règle
  qu'Équilibre à égalité (`image_principale`).
- **Aucun montant publié par défaut** : la dépense chiffrée est en unités
  relatives. `--montants` la passe en cents ; ne pas l'activer sans l'accord
  du client.
- Clé des chiffres : `~/.config/visuels/floorbox.cle`, jamais dans le dépôt.
  Le script imprime le lien complet ; sans la clé, la page ne montre que les
  annonces en ligne, sans indice.

### Mise à jour quotidienne (depuis le 2026-11-10)

Une tâche planifiée de l'app Claude (`floorbox-galerie-quotidienne`, chaque
matin, après celle d'Équilibre) tire, construit et pousse **sans attendre de
go** (accord de Chrysto du 2026-11-09). Elle passe par
`outils/tirage_floorbox.py`, sur le modèle de `tirage_equilibre.py` : cache
des annonces et des images par compte dans `~/.cache/visuels/floorbox/`
(hors dépôt), code 2 pour dire quoi tirer (fichiers `ca_…` et `us_…` dans le
dossier du jour ; par compte, chaque jour : annonces actives, rapport avec
`purchases`, soumissions par Graph), code 0 « PRÊT » une fois construit et
vérifié (rapport et soumissions jusqu'à la veille, autant d'annonces en
ligne que d'actives avec visuel), code 3 pour bloquer (clé absente, rapport
incomplet, soumissions sur plus d'une page, construction incohérente).

```bash
python3 -I outils/tirage_floorbox.py
```

### Mettre à jour depuis Meta (à la main, tout le tirage)

1. Tirer par Markifact, pour chaque compte (CA et US), avec
   `connection_id: 63ab1d5f-e045-49f8-9f53-00779cad1271` (les gros
   résultats reviennent en `file_id` : `get_file_url`, puis `curl`) :
   - `meta_ads_list_ads` (`ad_effective_status: ["ACTIVE"]`,
     `include_creative: true`, `limit: 1000`) → `ca_actives.json` ;
   - `meta_ads_get_report` du 2026-09-28 à la veille (`preset: FIXED`),
     dimensions `date, campaignId, campaignName, optimizationGoal, adsetId,
     adsetName, adId, adName`, métriques `cost, impressions, linkClicks,
     results, purchases`, filtre `impressions GREATER_THAN 0`, `limit: 20000` →
     `ca_perf.json` ;
   - `meta_ads_get_graph_data`, `path` =
     `act_…/insights?level=ad&fields=ad_id,conversions&time_increment=1&limit=5000&filtering=[{"field":"action_type","operator":"IN","value":["offsite_conversion.fb_pixel_custom.AskForQuote"]}]&time_range={"since":"2026-09-28","until":"<veille>"}`
     → `ca_soum.json` (une seule page : `limit=5000` ; le script refuse une
     réponse qui a une page suivante) ;
   - les annonces du rapport qui ne sont pas actives : `meta_ads_list_ads`
     avec un filtre `ad_id IN_LIST` et tous les statuts →
     `ca_historiques.json` ;
   - `meta_ads_list_media` (`media_type: IMAGE`, `limit: 500`) →
     `ca_medias.json` (le script dit quelle annonce n'a pas son image).
2. Construire (les liens d'images Meta expirent en quelques jours :
   construire le jour du tirage) :

   ```bash
   python3 -I outils/construire_floorbox.py \
     --ca-ads ca_actives.json ca_historiques.json --ca-medias ca_medias.json --ca-perf ca_perf.json \
     --ca-soum ca_soum.json \
     --us-ads us_actives.json us_historiques.json --us-medias us_medias.json --us-perf us_perf.json \
     --us-soum us_soum.json \
     --depuis 2026-09-28 --date AAAA-MM-JJ
   ```

3. `git add -A floorbox && git commit -m "FloorBox : mise à jour du AAAA-MM-JJ" && git push`

## Équilibre

Galerie en lecture seule (ni sélection ni envoi) du compte
`act_807927256273007`, publications boostées exclues (campagne
`MOF - Engagement`). Un **sélecteur de dates à la Google Analytics**
(raccourcis, calendrier de deux mois, champs de début et de fin) : la page
recalcule l'indice pour n'importe quelle plage depuis juillet. Les autres
filtres (statut, section, format, tri) sont des menus déroulants.

**Quatre sections, rien d'autre** (décision de Chrysto du 2026-11-09, pour
que le designer voie vite ce qui marche sans ouvrir de discussion sur les
ciblages) : **AP, OP, DR**, d'après la ligne dans le nom de campagne, et
**Notoriété AP** à part. Scale, marchés rouges, local, pédiatrie et test
vont dans leur ligne ; aucun nom d'ad set n'apparaît, ni dans la page ni dans
`annonces.json`.

**Une carte par visuel** et par section, pas par annonce : les copies d'un
même visuel dans plusieurs ad sets se réunissent. Deux annonces vont
ensemble quand les médias de l'une sont tous dans l'autre (images par hash,
vidéos par titre et durée, car une vidéo téléversée deux fois change
d'identifiant) : une copie avec un format ajouté après coup suit, mais deux
créas différentes qui partagent une image égarée restent séparées. Le script
range chaque annonce dans sa carte (`carte`). Une carte s'affiche si l'une
de ses copies a livré pendant la plage (ou, si la plage finit hier, si l'une
est en ligne).

**L'image montrée** : la plus proche du 4:5 ; à égalité, celle téléversée
avec la version 9:16 de l'annonce (à deux jours près), puis celle dont le nom
de fichier partage des mots avec le nom de l'annonce, puis la plus récente.
Des annonces locales traînent en tête de leur liste une image d'une autre
ville, copiée d'une autre annonce, que Meta prend pour vignette : avant le
2026-11-09, la galerie montrait cette image-là.

### Indice : chaque copie contre son public, puis on additionne

Même calcul que FloorBox (résultats par dollar, 100 = la moyenne, budget
testé d'au moins 3 résultats, Poisson, pas de rouge sans preuve), par carte :
chaque copie est comparée à son ad set (à sa campagne quand elle y est
seule), ce qui donne ses résultats attendus ; l'indice de la carte est la
somme des résultats obtenus sur la somme des attendus. Un visuel n'est donc
ni avantagé ni pénalisé par l'endroit où Meta le diffuse. Le résultat suit
l'optimisation de l'ad set :

- **Conversion** (`OFFSITE_CONVERSIONS`) : à partir du 5 octobre, les
  `websiteViewContent` (étape 4 du formulaire de rendez-vous) des ad sets
  `ViewContent` ; avant, les `websiteAppointmentsScheduled`
  (website_schedule) des ad sets `Schedule`, **coupés au 26 septembre** :
  Meta n'en voit plus aucun à partir du 27 (compte classé santé), dépense et
  résultats de ces jours-là sont retirés. Jours fermés seulement (7 jours
  retirés pour l'attribution). Accroche = taux de clic sur le lien contre
  l'ad set.
- Une plage qui n'a pas 7 jours jugeables pour un but (les 7 derniers jours,
  ou du 27 septembre au 4 octobre en conversion) donne « Période courte ».
  Sur une plage qui finit avant hier, une annonce arrivée dans ses 7 derniers
  jours jugés est « trop courte ». Le calendrier marque d'un point orange les
  jours où la conversion n'est pas jugée.
- **Notoriété AP : l'attention** (option A choisie par Chrysto le
  2026-11-09). Les ad sets optimisent sur les vues de page, mais Meta égalise
  justement ce coût (3,42 à 3,92 vues par dollar du 10 octobre au 8 novembre),
  ce qui ne dit rien au designer. L'indice est donc les **vues complètes (ou
  15 s, ThruPlay) pour 100 impressions**, contre **toutes les vidéos du
  compte** sur les mêmes dates (3 vidéos de notoriété ne font pas une
  référence), sans délai d'attribution, jusqu'à la veille. Verdict à partir de
  2 000 impressions et 7 jours. Le détail : arrêt (vues de 3 s sur
  impressions, le début accroche-t-il ?) et rétention (ThruPlay sur vues de
  3 s, la suite tient-elle ?), contre les mêmes vidéos du compte. Les vues de
  page par dollar restent affichées pour info, en indice contre l'ad set.
- Les ad sets `Schedule` (événement restreint depuis la catégorie santé) et
  les boosts n'entrent ni dans l'indice ni dans la référence.
- « En test » : moins de 7 jours jugés ; verdict 14 jours après la première
  diffusion en conversion, 7 jours en notoriété.
- La part du budget d'une carte se lit contre sa section (« 21 % du budget
  Notoriété AP »), sur les 7 derniers jours ou toute la plage passée.
- Le calcul vit dans la page (`equilibre/index.html`, fonctions `calculer`
  et `perfCarte`) ; le script ne fait que préparer les chiffres.

### Chiffres par jour : chiffrés, la clé dans le lien

- `annonces.json` (public) ne porte que la description des annonces :
  visuel, textes, section, carte, aucun chiffre ni nom d'ad set.
- `donnees.bin` porte les chiffres par annonce et par jour (dépense,
  impressions, clics, résultats, vues de 3 s, ThruPlay), compressés puis
  chiffrés en AES-256 : illisibles dans le dépôt. La dépense y est en unités
  relatives (part du total), l'indice ne dépendant que des rapports ; avec
  `--montants`, elle passe en cents et la page affiche dépense, résultats et
  coût (pas sans l'accord du client).
- La clé est dans `~/.config/visuels/equilibre.cle`, **jamais dans le
  dépôt**. Elle voyage dans le lien, après le `#` (`.../equilibre/#k=...`),
  partie que le navigateur n'envoie pas au serveur. Le script imprime le lien
  complet à chaque construction. Sans clé (ou avec une mauvaise), la page
  montre les annonces actives, sans indice ni dates.
- Une clé perdue ou supprimée : le script en crée une nouvelle, et les liens
  déjà envoyés ne montrent plus les indices. Renvoyer le nouveau lien.
- L'adresse garde aussi les dates choisies (`p=mois-dernier`, ou `du=` et
  `au=`) : un lien copié rouvre la même vue.

### Mise à jour quotidienne (depuis le 2026-11-10)

Une tâche planifiée de l'app Claude (`equilibre-galerie-quotidienne`, chaque
matin) tire les chiffres par Markifact, construit et pousse **sans attendre
de go** (accord de Chrysto du 2026-11-09). Elle passe par
`outils/tirage_equilibre.py`, qui garde en cache
(`~/.cache/visuels/equilibre/`, hors dépôt) les annonces et les médias déjà
vus : chaque jour, il ne faut tirer que les annonces actives, le rapport, et
ce qui est nouveau.

```bash
python3 -I outils/tirage_equilibre.py
```

Le script dit quoi tirer, avec les entrées Markifact exactes (code 2), dans
le dossier du jour `~/.cache/visuels/equilibre/tirage-AAAA-MM-JJ/` ; on y
dépose le résultat sous le nom indiqué et on relance. Quand tout y est, il
construit et vérifie (code 0, « PRÊT ») : rapport jusqu'à la veille, autant
d'annonces en ligne que d'actives. Code 3 : rien n'est construit ou rien ne
doit être poussé (clé absente, rapport incomplet, construction incohérente).
Une image ou une vidéo nouvelle à télécharger exige un lien tiré le jour
même : le script redemande ses détails si le cache est plus vieux. Les
dossiers de tirage de plus de 14 jours sont effacés.

### Mettre à jour depuis Meta (à la main, tout le tirage)

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
   - pour que les vidéos jouent : `meta_ads_get_graph_data`, `path:
     "<video_id>?fields=source"` avec `page_id: "624700294315387"` (le jeton
     de la Page ; celui de l'utilisateur ne renvoie pas `source`), un appel
     par vidéo affichée (le paramètre `ids` est refusé depuis la v26) →
     `sources.json` (`{video_id: url}`). C'est le MP4 720p que Meta diffuse,
     avec le son, 1 à 2 Mo par vidéo ; le lien expire en quelques jours. Une
     vidéo déjà dans `equilibre/videos/` n'en a pas besoin : `{video_id:
     "local"}` suffit, le script ne la retélécharge pas ;
   - les gros résultats Markifact reviennent en `file_id` : `get_file_url`,
     puis `curl` dans un dossier de travail ;
   - `meta_ads_get_report` du 2026-07-01 à la veille, `preset: FIXED`,
     dimensions `date, campaignId, campaignName, optimizationGoal, adsetId,
     adsetName, adId, adName`, métriques `cost, impressions, linkClicks,
     landingPageViews, websiteViewContent, websiteAppointmentsScheduled,
     videoViews, thruPlays`, filtre `impressions GREATER_THAN 0`,
     `limit: 20000` → `perf.json` (environ 10 500 lignes au 2026-11-03) ;
   - les annonces du rapport qui ne sont plus actives : `meta_ads_list_ads`
     avec un filtre `ad_id IN_LIST` (les identifiants séparés par des
     virgules) et `ad_effective_status` à tous les statuts (`PAUSED`,
     `ADSET_PAUSED`, `CAMPAIGN_PAUSED`, `ARCHIVED`, `WITH_ISSUES`...) →
     `annonces_historiques.json`, puis leurs images et vidéos comme
     ci-dessus.
2. Construire (les liens d'images Meta expirent en quelques jours :
   construire le jour du tirage ; `openssl` doit être installé) :

   ```bash
   python3 -I outils/construire_equilibre.py \
     --ads annonces.json annonces_historiques.json \
     --medias medias_*.json --perf perf.json --complements complements.json \
     --sources sources.json --date AAAA-MM-JJ
   ```

   Écrit `equilibre/annonces.json` et `equilibre/donnees.bin`, et imprime
   le lien complet. Les vidéos vont dans `equilibre/videos/` (une par
   `video_id`, remuxée par `ffmpeg` pour démarrer sans attendre la fin du
   téléchargement) et jouent dans le grand format. Sans `--sources`, une
   vidéo garde son affiche et le lien d'aperçu Meta.

3. `git add -A && git commit -m "Équilibre : mise à jour du AAAA-MM-JJ" && git push`
