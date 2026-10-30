# Démonstration Cartomize 1.0 — Scènes, bandes et zone d’étude

## Objectif

Montrer qu’une sélection de scènes téléchargées, de bandes et d’une zone
polygonale suffit à lancer une chaîne de prétraitement cohérente. Le moteur
mesure les couvertures, décide s’il faut retenir une scène ou réaliser une
mosaïque, harmonise les grilles et découpe le résultat sur la zone.

## Installer la livraison exacte

Créer de préférence un environnement réservé à la démonstration avec Python
3.11 ou 3.12. Placer le wheel de la livraison dans le dossier courant.

Sous Windows, dans un terminal :

```powershell
py -3.12 -m venv cartomize-demo
.\cartomize-demo\Scripts\python.exe -m pip install "./cartomize-1.0-20261030-py3-none-any.whl[notebook]"
.\cartomize-demo\Scripts\python.exe -m cartomize gui
```

Adapter `-3.12` à `-3.11` si cette version est installée. Pour l’interface seule,
remplacer `[notebook]` par `[gui]`.

Sous Linux ou macOS :

```bash
python3 -m venv cartomize-demo
./cartomize-demo/bin/python -m pip install "./cartomize-1.0-20261030-py3-none-any.whl[notebook]"
./cartomize-demo/bin/python -m cartomize gui
```

Utiliser **le wheel fourni avec cette livraison**, pas un ancien téléchargement
portant le même numéro. Dans un environnement contenant déjà une autre édition
1.0, pip peut considérer la version comme déjà installée ; créer l’environnement
ci-dessus évite cette confusion. Le suivi de distribution figure dans
[PUBLICATION.md](PUBLICATION.md).

## Préparer les données USGS

1. Télécharger des produits **Landsat Collection 2 Level-2** appropriés à la zone.
2. Extraire les archives avant l’import. Conserver un dossier par acquisition,
   avec les noms d’origine des bandes, les fichiers MTL, QA_PIXEL et QA_RADSAT.
3. Préparer une délimitation polygonale géoréférencée : GeoPackage, GeoJSON ou
   shapefile complet (`.shp`, `.shx`, `.dbf` et `.prj`).
4. Pour une mosaïque de la même acquisition, retenir des scènes compatibles
   provenant de la même date. Si des dates différentes sont indispensables,
   choisir explicitement cette option et expliquer qu’il s’agit d’une
   composition temporelle.

Les produits Sentinel-2 Level-2A reconnus suivent le même principe en conservant
leurs métadonnées et leur masque SCL. Les valeurs de réflectance utilisent la
calibration des produits fournis ; les produits Level-1 nécessitant une correction
atmosphérique doivent être préparés par le processeur adapté.

## Parcours sans code

1. Ouvrir **Prétraitement multispectral**.
2. Conserver **Automatique : contrôler et préparer**.
3. Cliquer **Sélectionner les bandes…**, ou choisir le dossier de scènes puis
   **Analyser les bandes**. Cocher les mêmes rôles spectraux dans les acquisitions
   à combiner, par exemple bleu, vert, rouge et proche infrarouge.
4. Sélectionner le fichier de la **zone d’étude**.
5. Choisir les produits souhaités : multibande scientifique, bandes séparées et,
   si souhaité, composition colorée. Pour les couleurs naturelles, utiliser
   rouge/vert/bleu ; la composition reste séparée des valeurs scientifiques.
6. Choisir un répertoire de sortie et un **nouveau nom de dossier**.
7. Cliquer **Exécuter**. Le diagnostic préalable est facultatif : le moteur
   recalcule toujours la couverture et les décisions pendant l’exécution.
8. Ouvrir les résultats, le rapport et, si nécessaire, la carte des lacunes.

La grille cible reprend les paramètres compatibles des scènes importées. Les
réglages de projection et de résolution restent accessibles pour un besoin
particulier. Les rasters géographiques doivent être associés à un SCR projeté
adapté pour une résolution exprimée en mètres.

## Les situations à montrer

| Entrées | Décision et résultat attendu |
|---|---|
| Une scène couvre toute la zone et déborde autour | Une scène retenue, calibration/masques, découpage au polygone ; aucun assemblage de scènes inutile. |
| Deux scènes complémentaires couvrent ensemble la zone | Sélection des scènes contributrices, grille commune, mosaïque et découpage. |
| Plusieurs scènes sont chargées mais une seule suffit | La scène suffisante est retenue et les autres ne sont pas assemblées inutilement. |
| Les emprises couvrent la zone, avec des nuages ou des pixels invalides | Calcul de la couverture utile après les masques ; les lacunes sont distinguées de l’emprise géométrique. |
| Les scènes fournies laissent une partie de la zone sans données utilisables | Diagnostic et carte des secteurs manquants ; ajout de scènes complémentaires ou choix explicite d’une sortie partielle. |

Le moteur conserve ensemble toutes les bandes d’une même acquisition pour un
pixel de mosaïque. La limite polygonale est appliquée comme masque : les pixels
extérieurs restent NoData, y compris dans les coins du rectangle englobant.

## Même traitement dans Jupyter

Lancer JupyterLab depuis l’environnement de la démonstration :

```powershell
.\cartomize-demo\Scripts\python.exe -m jupyter lab
```

Dans une cellule, adapter uniquement les chemins et les bandes :

```python
import cartomize as cm

resultat = cm.preprocess_imagery(
    r"C:/donnees/scenes",
    r"C:/resultats/pretraitement_01",  # Un dossier qui n’existe pas encore
    aoi=r"C:/donnees/zone_etude.gpkg",
    band_order=["blue", "green", "red", "nir"],
    coverage_threshold=100,
    multiband=True,
    separate_bands=True,
    composition="natural",
)

print(resultat.report["status"])
print(resultat.report["usable_percent"])
print(resultat.report["selected_scene_ids"])
print(resultat.manifest)
```

Pour conserver un diagnostic en cas de lacunes :

```python
try:
    resultat = cm.preprocess_imagery(
        r"C:/donnees/scenes", r"C:/resultats/pretraitement_02",
        aoi=r"C:/donnees/zone_etude.gpkg",
        band_order=["red", "nir"],
    )
except cm.ImageryCoverageError as erreur:
    print("Couverture utile :", erreur.report["usable_percent"])
    print("Rapport :", erreur.manifest)
    print("Lacunes :", erreur.diagnostic.gaps)
```

Pour ouvrir l’interface depuis un notebook local :

```python
fenetre = cm.launch()
```

## Avant la présentation

Le [notebook 22](../tutorials/notebooks/22_demonstration_pretraitement_automatique.ipynb)
fournit une répétition hors ligne de ce parcours, avec scènes et valeurs
explicitement **pédagogiques simulées**. Le générateur
`examples/create_imagery_demo.py` crée les mêmes entrées pour la fenêtre :

```bash
python examples/create_imagery_demo.py demo_complete
python examples/create_imagery_demo.py demo_nuages --gap cloud
python examples/create_imagery_demo.py demo_projections --different-crs
```

Dans la fenêtre, sélectionner `demo_complete/scenes` et
`demo_complete/zone_mosaic.gpkg`, puis exécuter vers un nouveau dossier.
`zone_one_scene.gpkg` permet de montrer le cas où une seule scène suffit.
Ces fichiers ne représentent pas des observations satellitaires réelles.

Installer l’environnement et vérifier les fichiers de données avant la séance.
Conserver les dossiers sources et produire chaque exécution dans un nouveau
dossier. Commencer par un petit secteur permettant d’observer la décision,
le résultat multibande et la différence entre scène complète et mosaïque.
