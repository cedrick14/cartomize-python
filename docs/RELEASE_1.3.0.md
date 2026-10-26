# Cartomize 1.3.0 — modules experts et installation commune

Cette version des sources complète six modules à partir du dépôt `cedrick14/cartomize-python`, dont le point de départ était `ad4d1d7a89557e347b9a322f73c32205807c077a`. L’API utilisée dans les cellules Jupyter, les commandes et la fenêtre de bureau partagent les mêmes fonctions. Aucun appel à QGIS ou ArcGIS n’est requis pour les traitements autonomes.

## Modules complétés

| Module | Changements | Guide |
|---|---|---|
| M01 — Imagerie | Diagnostic exact sur la grille cible : emprise, présence des bandes et données utilisables après masques ; cartes de lacunes ; proposition de scène unique, mosaïque ou acquisitions complémentaires. Résolution des grilles tournées et dates vides contrôlées. | [Diagnostic](IMAGERY_AUDIT.md) |
| M02 — Vecteur | Conservation des grands identifiants entiers ; distinction somme nulle / observations manquantes ; politique explicite des clés nulles ; huit traitements supplémentaires dans le registre. | [Workflows SIG](SIG_WORKFLOWS.md) |
| M03 — Raster | Statistiques zonales en valeurs physiques ou brutes, couverture de toute la zone, préfixes, provenance, calcul par blocs et sélection des frontières indépendante des blocs. Emprises affines réelles ; protection de la source du masque de validité. | [Statistiques zonales](RASTER_STATISTICS.md) |
| M04 — Classification | Classes numériques cohérentes, textes et booléens distincts, grands entiers exacts ; prélèvements corrects sur les grilles tournées ; chargement des modèles antérieurs conservé. | [Classification](CLASSIFICATION.md) |
| M05 — Routage | Raccordement aux segments ou aux sommets ; découpage des arêtes aux positions projetées ; distances de raccordement séparées ; géométrie Point valide pour un trajet de longueur nulle. | [Chaînes et routage](PROCESSING.md) |
| M06 — Installation et interfaces | Cœur utilisable sans Qt, message d’installation de l’option graphique, paramètres de chaînes restaurés sans perte de `None`, choix fermés en français, formulaire zonal accessible, tutoriels et Binder raccordés aux sources du dépôt. | [Jupyter](NOTEBOOKS.md), [interface](WORKBENCH.md) |

Le registre comporte **43 opérateurs**. L’[inventaire expert](EXPERT_PROCEDURES.md) examine séparément **123 procédures** : 11 disponibles dans leur périmètre explicite, 48 partielles et 64 absentes. Il conserve les fonctions vérifiées, les limites, l’ordre proposé pour les extensions et 88 références. Une fonction composable et une procédure experte complète ne sont pas la même unité de comptage.

## Diagnostic avant mosaïque

```python
import cartomize as cm

diagnostic = cm.audit_imagery(
    "donnees/scenes", "resultats/diagnostic_01",
    aoi="zone_etude.gpkg", band_order=["red", "nir"],
)
print(diagnostic.report["usable_percent"])
print(diagnostic.report["recommended_action"])
print(diagnostic.report["recommended_scene_ids"])
```

Un spectre valide doit provenir d’une même scène : les bandes manquantes de plusieurs acquisitions ne sont pas combinées pour inventer un pixel complet. Les trois sorties de diagnostic sont `report.json`, `coverage.tif` et `gaps.tif`. Une absence totale de couverture est un résultat explicite, pas une image scientifique remplie artificiellement.

La fenêtre expose le bouton **Diagnostiquer la couverture** et l’application de la proposition. Le [cours 13](../tutorials/notebooks/13_diagnostic_automatique.ipynb) montre une chaîne Python où une couverture insuffisante interrompt le calcul, puis un cas distinct où deux scènes justifient une mosaïque, suivie du NDVI et des statistiques zonales.

## Changements de comportement à prendre en compte

### Statistiques zonales

`zonal_stats` applique désormais par défaut les facteurs et décalages du raster : `physique = valeur_brute × scale + offset`. Pour reproduire une analyse volontairement réalisée sur les valeurs stockées, déclarer `value_mode="raw"`. Les calculs de superficies de classes conservent leurs codes catégoriels.

Les zones non vides doivent être polygonales. Les géométries vides restent représentées dans le tableau. Les noms de champs de résultats ne peuvent pas écraser des attributs existants ; utiliser `prefix="ndvi_"` ou un autre préfixe.

Avec `include_coverage=True`, `zone_pixels` porte sur la zone entière dans la grille prolongée, `raster_pixels` sur son intersection avec la grille du raster et `count` sur les observations valides. `coverage_percent` vaut `100 × count / zone_pixels`. Une zone sans cellule sélectionnée a une couverture indéfinie (`NaN`), pas 100 %.

Les centres de pixels sur une frontière sont inclus. En mode `all_touched`, les cellules fermées intersectant le polygone dans la fenêtre candidate sont sélectionnées. Ces règles rendent le résultat indépendant du découpage en blocs ; elles ne promettent pas une identité universelle avec les cas limites de rasterisation GDAL. Les statistiques ne sont pas pondérées par les fractions de surface des pixels. Voir les [conventions détaillées](RASTER_STATISTICS.md).

### Jointures et classes

`join_attributes` utilise `null_keys="unmatched"` par défaut. Choisir `"match"` pour apparier explicitement les clés manquantes ou `"error"` pour les refuser. Les identifiants textuels à zéros initiaux demandent un type de colonne adapté lors de la lecture de tableaux, par exemple `table_dtypes={"code": "string"}` dans un opérateur.

En classification, `1` et `1.0` représentent la même classe numérique ; les textes `"1"` et `"01"`, ainsi que le booléen `True`, restent distincts de cette classe. Les nouveaux rapports décrivent l’encodage typé. Les modèles enregistrés avec le format précédent restent chargeables.

### Routage

`shortest_path` utilise désormais `snap="edge"` : les positions sont projetées à l’intérieur des segments les plus proches. Le mode `snap="node"` conserve le raccordement aux sommets. La longueur du trajet porte sur le réseau ; les distances entre les positions demandées et leurs projections sont enregistrées séparément.

Deux positions raccordées au même point produisent une géométrie **Point**, une longueur nulle et `route_status="coincident"`. Les traitements suivants doivent donc accepter ce type pour ce cas. Les trajets ordinaires restent des LineString. Les restrictions de circulation, sens uniques et coûts de temps ne sont pas inférés.

### Dates et résolution

Une date d’acquisition vide devient inconnue. Plusieurs scènes de dates inconnues ou différentes exigent un choix explicite `allow_mixed_dates=True`. La normalisation des dates ne justifie pas leur mélange scientifique.

À SCR inchangé, la résolution par défaut conserve les longueurs des axes affines natifs, y compris pour une image tournée. En reprojection, elle utilise la grille proposée par GDAL à partir de la transformation réelle. Une résolution explicite permet de fixer la grille de l’étude ; un pixel plus petit n’ajoute pas de détail observé.

## Installation depuis ces sources

Depuis la racine du dépôt et dans un environnement activé :

```bash
# API, sans dépendance graphique
python -m pip install -e .

# Interface de bureau
python -m pip install -e ".[gui]"
python -m cartomize gui

# Parcours Jupyter, en utilisant les mêmes sources
python -m pip install -r tutorials/requirements.txt
python -m jupyterlab tutorials/notebooks
```

Pour ouvrir la fenêtre depuis un notebook local, installer `.[notebook]`, redémarrer le noyau puis appeler `cm.launch()`. Le guide [Jupyter](NOTEBOOKS.md) explique les chemins, les noyaux et Conda. La publication d’une version sur PyPI constitue une étape distincte de la mise à disposition du code GitHub.

## Validation de cette version

Validation locale du **26 octobre 2026**, sous **Linux / Python 3.12.14**. Le [rapport machine](VALIDATION_1.3.0.json) conserve les versions des dépendances, le périmètre et l’empreinte de la wheel testée.

| Contrôle | Résultat |
|---|---|
| Suite complète | **626 réussis, 2 ignorés**, aucun échec ; 628 tests collectés. |
| Jupyter | **12 notebooks autonomes**, cours 00 à 10 et 13 ; **73 cellules de code exécutées**, un noyau réel neuf par cours. |
| Édition HTML | 14 cours exportés ; cela inclut les sorties historiques des deux cours privés, sans prétendre les avoir réexécutés. |
| Construction | Wheel et archive source 1.3.0 construites ; Twine strict et contrôle des modules, ressources et métadonnées réussis. |
| Installation isolée | Wheel installée avec `gui` dans un environnement neuf ; dépendances cohérentes, import depuis `site-packages`, hors de la copie du dépôt. |
| Calculs depuis le paquet installé | NDVI, tampon de 200 m, diagnostic d’imagerie et statistiques calibrées ; couverture de référence **5 pixels valides sur 8, soit 62,5 %**. |
| Interface installée | 20 pages, trois thèmes, exports PDF/PNG/SVG, sauvegarde/réouverture et noyau de console vérifiés. |
| Contrat API et fenêtre | API importable sans Qt ; erreur d’installation explicite à l’ouverture sans l’option graphique ; vraie cellule Jupyter rendue avec événements Qt actifs. |
| Revue du formulaire zonal | Fenêtre 1440 × 940, tailles de texte 11–16 et styles Windows/Fusion sous Linux : boutons de fichiers visibles et aucune barre de défilement horizontale. |

Les essais graphiques utilisent Qt en mode hors écran. Ces résultats locaux ne remplacent pas les jobs Windows, Linux et QGIS du dépôt ; leurs résultats sont associés aux commits dans [GitHub Actions](https://github.com/cedrick14/cartomize-python/actions). Les tests de chaque module et les scripts de reproduction sont inclus dans les sources.

Les essais nécessitant CUDA, QGIS natif ou ArcPy dépendent de leurs environnements. Les cours 11 et 12 exigent le jeu privé `Tuto.zip`. Le parcours autonome ne vérifie pas la disponibilité de Binder ou d’un fournisseur STAC distant.
