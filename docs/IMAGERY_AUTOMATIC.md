# Prétraitement automatique des images

Le prétraitement automatique associe le diagnostic de couverture, la sélection
des scènes et la préparation des images optiques compatibles. Le moteur
`preprocess_imagery()` s’utilise depuis Python/Jupyter, le terminal, le registre
de traitements et l’interface graphique.

## Parcours exécuté

1. Lire les scènes, les bandes, leurs unités, la calibration et les masques.
2. Vérifier la zone polygonale et fixer la projection, la résolution et la grille.
3. Compter les pixels de la zone couverts par les emprises, les données présentes
   et les observations utilisables après les masques demandés.
4. Si la couverture est insuffisante et qu’un catalogue est configuré, chercher
   des scènes compatibles, les télécharger dans les limites choisies et mesurer
   leur apport réel à la couverture utile.
5. Retenir une scène suffisante, ou les scènes contributrices à la mosaïque.
6. Recalculer le diagnostic de cette sélection sur la grille initiale et
   appliquer la politique de couverture.
7. Calibrer, masquer, aligner, assembler et découper ; produire les fichiers
   demandés et vérifier que leur couverture correspond au diagnostic.
8. Publier ensemble les sorties, la provenance et le rapport de décision.

Le diagnostic est recalculé pendant chaque exécution. Un diagnostic consulté
auparavant dans la fenêtre ne remplace pas ce contrôle. Les fichiers des scènes
retenues sont contrôlés avant et après les étapes de calcul pour détecter leur
modification pendant l’exécution.

La recommandation cherche une scène suffisante lorsqu’elle existe. Sinon, elle
retient les scènes ayant des pixels utiles. Elle ne constitue pas une
optimisation du nombre minimal d’acquisitions. Toutes les bandes d’un pixel
scientifique proviennent d’une même acquisition.

## Couverture complète, seuil et résultat partiel

`coverage_threshold` est un pourcentage strictement supérieur à zéro et inférieur
ou égal à 100. Il vaut 100 par défaut. `allow_partial` vaut `False` par défaut et
doit être un booléen explicite.

| Couverture utile | Réglage | Résultat |
|---|---|---|
| 100 % | Seuil 100 %, comportement par défaut | Production, `status="complete"`, `threshold_met=True`. |
| 85 % | Seuil 100 %, `allow_partial=False` | Arrêt avec diagnostic, sans production scientifique. |
| 85 % | Seuil 100 %, `allow_partial=True` | Production partielle, `status="partial"`, `threshold_met=False`. |
| 85 % | Seuil 80 %, `allow_partial=False` | Production partielle conforme au seuil, `status="partial"`, `threshold_met=True`. |
| 0 % | Tout seuil et toute valeur de `allow_partial` | Arrêt, sans image artificiellement remplie. |

Une zone ne contenant aucun pixel sous la règle de sélection choisie provoque
également un arrêt. Une résolution plus fine ou `all_touched=True` peut modifier
ce support de calcul. Les pourcentages comptent les cellules de la zone sur la
grille cible ; ce ne sont pas des superficies polygonales pondérées par fractions
de pixels.

Le champ `coverage_status` du diagnostic distingue la
couverture réelle complète de l’atteinte du seuil, porté par `threshold_met`.
Abaisser le seuil ne transforme donc pas une couverture de 85 % en couverture
complète. Les secteurs non couverts restent NoData dans les images produites.

## Python et cellules Jupyter

```python
import cartomize as cm

try:
    produit = cm.preprocess_imagery(
        "donnees/scenes", "resultats/pretraitement_01",
        aoi="donnees/zone_etude.gpkg",
        band_order=["red", "nir"],
        target_crs="EPSG:32733",  # Choisir la projection adaptée à l’étude.
        resolution=30,
        coverage_threshold=100,
        separate_bands=True,
    )
except cm.ImageryCoverageError as erreur:
    print(erreur.report["usable_percent"])
    print(erreur.manifest)          # Rapport du diagnostic conservé.
    print(erreur.diagnostic.gaps)   # Carte des secteurs manquants.
else:
    print(produit.report["status"])
    print(produit.report["selected_scene_ids"])
    image = produit.products[0]["multiband"]
    cm.spectral_indices(image, "resultats/ndvi_01.tif", ["NDVI"])
```

Le résultat `PreprocessedImagery` expose `manifest`, `products`, `diagnostic` et
`report`. Le manifeste `preprocessing.json`, de schéma
`cartomize.imagery.automatic.v1`, contient notamment le statut, le seuil, son
atteinte, les scènes retenues, les acquisitions complémentaires et les chemins
des produits.

Les options de production sont `multiband=True`, `separate_bands=False` et
`composition=None`. Une composition, par exemple `composition="natural"`, est
un produit d’affichage séparé. Au moins une sortie doit être demandée. Les options
de grille, d’interpolation, de dates et de masques sont communes au diagnostic
et à la préparation. `overlap="first"` ou `"last"` définit la priorité spectrale
dans les recouvrements.

Les entrées locales peuvent être des objets `Scene`, un dossier de produits
reconnus, des chemins de bandes ou un manifeste local. Les zones peuvent être
des fichiers vectoriels ou des GeoDataFrame/GeoSeries polygonaux avec un SCR.
Les GeoTIFF personnalisés nécessitent des rôles spectraux et une calibration
correctement décrits ; voir les [entrées multispectrales](IMAGERY_WORKFLOW.md).

## Scènes complémentaires depuis un catalogue

`catalog` accepte un objet Python ou le chemin d’un fichier JSON. Exemple de
configuration, dont l’adresse et la collection sont à remplacer par celles du
fournisseur choisi :

```json
{
  "endpoint": "https://catalogue.example.org/v1",
  "collections": ["collection-optique-l2"],
  "datetime_range": "2026-08-17/2026-08-17",
  "max_items": 10,
  "max_bytes": 1000000000,
  "timeout": 60
}
```

L’accès réseau n’intervient que si les scènes fournies n’atteignent pas le seuil.
La recherche utilise le polygone de la zone reprojeté en longitude/latitude,
avec la limite d’items et l’intervalle de dates configurés. En l’absence d’un
intervalle explicite, la date des scènes locales est utilisée lorsque le mélange
de dates n’est pas autorisé.

Chaque candidate est téléchargée puis réévaluée sur la grille initiale. Elle
doit ajouter des pixels utiles et respecter les bandes, unités, capteur, niveau
et règles de dates. Les incompatibilités et les téléchargements échoués sont
consignés. La recherche s’arrête lorsque le seuil est atteint ou que les limites
sont atteintes. Elle ne garantit pas qu’un fournisseur possède une acquisition
capable de combler chaque lacune.

`max_items` vaut 10 par défaut, au plus 1 000. `max_bytes` vaut un milliard
d’octets par défaut et porte sur les transferts de cette exécution, y compris
les scènes téléchargées ensuite écartées. Un transfert incomplet dont le volume
ne peut pas être établi interrompt les transferts suivants. `timeout` vaut
60 secondes par défaut, au plus 300 par requête ; ce n’est pas un délai global
pour l’ensemble du traitement.

Le raccordement STAC reconnaît les masques des profils optiques pris en charge.
Les correspondances particulières peuvent être déclarées avec `band_mapping`,
`quality_asset`, `quality_kind` et `saturation_asset`. La demande de masquage ne
se désactive jamais silencieusement. Les produits dépourvus de masque nécessitent
un choix explicite `mask_clouds=False` ; cela ne constitue pas une correction
des nuages.

Les URL d’assets doivent être accessibles. L’authentification privée et la
signature d’URL propres à un fournisseur ne sont pas créées automatiquement.
Les détails d’import sont décrits dans [Scènes STAC](PROCESSING.md#scènes-stac-et-capteurs-supplémentaires).

Pour démarrer sans scène locale, passer `scenes=[]` avec `catalog`, `band_order`,
`target_crs` projeté et `resolution` explicites. Cela permet aussi de produire
un diagnostic géoréférencé exact si aucune candidate n’est utilisable.

## Terminal

```bash
cartomize preprocess-imagery donnees/scenes resultats/automatique_01 --aoi donnees/zone.gpkg --bands red,nir --crs EPSG:32733 --resolution 30
```

Ajouter `--catalog catalogue.json` pour rechercher des compléments seulement
si nécessaire. Une recherche sans scène locale utilise explicitement `-` :

```bash
cartomize preprocess-imagery - resultats/catalogue_01 --aoi donnees/zone.gpkg --bands red,nir --crs EPSG:32733 --resolution 30 --catalog catalogue.json
```

`--coverage-threshold 95` modifie le seuil. `--allow-partial` permet explicitement
une production non vide inférieure à ce seuil. `--separate-bands`,
`--without-multiband` et `--rgb natural` définissent les sorties. Les autres
réglages sont accessibles avec `cartomize preprocess-imagery --help`.

En cas de succès, la commande écrit le rapport JSON sur la sortie standard et
retourne le code 0. Une couverture insuffisante retourne le code 2 et un objet
JSON sur la sortie d’erreur : `error`, `message`, `diagnostic`, `coverage`, `gaps`,
`report` et `workflow`. Les autres erreurs d’entrée sont également signalées
avec un code non nul.

## Registre, chaînes et production cartographique

L’opérateur `imagery.preprocess` expose le manifeste comme produit `primary`.
Pour un calcul raster suivant, utiliser le produit nommé `multiband` :

```python
plan = cm.processing_plan([
    {"id": "images", "operation": "imagery.preprocess", "parameters": {
        "sources": "donnees/scenes", "aoi": "donnees/zone.gpkg",
        "band_order": ["red", "nir"], "coverage_threshold": 100,
    }},
    {"id": "ndvi", "operation": "indices", "parameters": {
        "source": "@images:multiband", "indices": ["NDVI"],
    }},
])
cm.run_plan(plan, "resultats/chaine_01")
```

Les produits nommés sont `audit`, `coverage`, `gaps`, `preparation` et, selon les
sorties demandées, `multiband`, `source_index`, `composition`, `report` et
`band_1`, `band_2`, etc. `@images` seul désigne le manifeste, pas une image.

`plan_cartography(data_kind="scenes", aoi=...)` crée cette préparation
automatique avant la composition, les indices, la classification ou les étapes
utilisant `@scientific`. `cartographic_workflow(..., aoi=...)` applique la même
politique avant le rendu des cartes. Les deux acceptent `coverage_threshold`,
`allow_partial` et `catalog`. Sans zone d’étude, ils conservent la préparation
sur l’étendue des scènes, sans affirmation de couverture d’un territoire.

Le rapport d’un plan conserve un résumé `imagery_preprocessing` par étape et
`coverage_status="partial"` dès qu’une préparation automatique a une couverture
partielle. Les taux ne sont pas moyennés entre des zones différentes. Le document
cartographique et les chemins de ses couches restent réouvrables après publication.

Les appels explicites `prepare_imagery()` et `process_imagery()` restent les
opérations de préparation à réglages manuels. `audit_imagery()` reste utilisable
pour un diagnostic seul. Le mode automatique de la fenêtre appelle
`preprocess_imagery()` ; son mode manuel conserve les réglages explicites.

## Sorties, refus et annulation

La destination scientifique doit être un nouveau dossier. En cas de couverture
insuffisante, `ImageryCoverageError` conserve les cartes et rapports dans un
dossier voisin, par exemple `automatique_01_diagnostic`, ou un nom numéroté si
ce dossier existe déjà. La destination scientifique n’est pas publiée et les
étapes dépendantes ne sont pas exécutées.

Le diagnostic contient `report.json`, `coverage.tif`, `gaps.tif` et
`preprocessing.json`. Les acquisitions brutes téléchargées et retenues sont
conservées dans `acquisitions` lorsqu’elles existent, avec des chemins corrigés,
pour permettre leur réutilisation. Aucune image prétraitée n’est présentée
comme achevée dans ce dossier. Les sources locales restent inchangées.

Cette conservation fonctionne aussi à travers les dossiers temporaires d’un
opérateur, d’un plan ou d’une production cartographique. Une annulation arrête
les calculs et transferts de manière coopérative ; les dossiers partiels en
cours ne sont pas publiés. Un rapport diagnostic antérieur reste conservé.

## Références dans le dépôt

- [Moteur automatique](../src/cartomize/imagery_automatic.py).
- [Import et téléchargement STAC](../src/cartomize/catalogs.py).
- [Diagnostic exact et conventions](IMAGERY_AUDIT.md).
- [Tests du moteur et des catalogues](../tests/test_imagery_automatic.py).
- [Tests API, terminal, registre, plans et cartes](../tests/test_imagery_automatic_interfaces.py).
- [Tests de la fenêtre](../tests/test_desktop_imagery_automatic.py).
