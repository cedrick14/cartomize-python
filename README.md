# Cartomize

Cartomize associe une bibliothèque Python, une interface graphique et des commandes pour le traitement géospatial et la production cartographique.

Cette édition consolidée porte le numéro **1.0** et réunit tous les modules déjà terminés, jusqu’à **G12 — Zones tampons et anneaux de distance**. La bibliothèque, les cellules Jupyter, les commandes du terminal et l’interface de bureau appellent les mêmes traitements. Voir la [présentation de l’édition](docs/RELEASE_1.0.md) et le [parcours de démonstration](docs/DEMONSTRATION_1.0.md).

## Installation

Python 3.11 ou 3.12 est recommandé pour l’interface. QGIS et ArcGIS Pro ne sont pas nécessaires au fonctionnement de Cartomize ; seules les passerelles natives les utilisent.

Créer un environnement Python :

```bash
python -m venv .venv
```

Activer l’environnement sous Windows :

```powershell
.venv\Scripts\Activate.ps1
```

Sous Linux ou macOS :

```bash
source .venv/bin/activate
```

### API Python et cellules Jupyter

Installer la bibliothèque depuis PyPI :

```bash
python -m pip install --upgrade pip
python -m pip install --index-url https://pypi.org/simple "cartomize==1.0"
```

Les fonctions s’utilisent directement dans un script ou une cellule :

```python
import cartomize as cm
print(cm.__version__)
resultat = cm.preprocess_imagery(
    "donnees/scenes", "resultats/preparation_01", aoi="zone_etude.gpkg",
    band_order=["red", "nir"], coverage_threshold=100.0,
)
print(resultat.report["status"], resultat.report["usable_percent"])
```

Qt est facultatif pour ces calculs. Pour installer Jupyter et les composants de l’interface locale :

```bash
python -m pip install --index-url https://pypi.org/simple "cartomize[notebook]==1.0"
python -m jupyter lab
```

Les notebooks et les données synthétiques de démonstration sont fournis dans la [livraison GitHub](https://github.com/cedrick14/cartomize-python/releases/latest). Le [guide Jupyter](docs/NOTEBOOKS.md) explique le choix du noyau et l’installation dans un environnement existant.

### Interface de bureau sans code

Installer puis ouvrir l’interface :

```bash
python -m pip install --index-url https://pypi.org/simple "cartomize[gui]==1.0"
python -m cartomize gui
```

La commande `cartomize-desktop` ouvre également la fenêtre. Elle réunit un explorateur, un catalogue de traitements, une carte centrale, les paramètres et une console Python.

Depuis Python, après installation de l’option graphique :

```python
import cartomize as cm
fenetre = cm.launch()
```

Pour ouvrir cette fenêtre depuis un notebook local, installer l’option `cartomize[notebook]==1.0` avec la commande ci-dessus, redémarrer le noyau puis appeler `cm.launch()`. Les notebooks distants peuvent utiliser l’API sans ouvrir de fenêtre native.

L’espace de travail dynamique de **Cartomize 1.0**, construction **2026103001**, est publié sur [PyPI](https://pypi.org/project/cartomize/1.0/#files) et dans la [livraison GitHub](https://github.com/cedrick14/cartomize-python/releases/tag/cartomize-1.0-2026103001) depuis le 30 octobre 2026. La version publique reste `1.0` ; le paquet installé doit indiquer `Build: 2026103001`. La sélection par l’index PyPI et l’installation isolée du wheel publié ont été vérifiées séparément ; les [preuves de publication](docs/PUBLICATION.md) et le [rapport de validation](docs/VALIDATION_DYNAMIC_1.0.json) en précisent les résultats. Pour remplacer une installation antérieure portant déjà le numéro `1.0`, utiliser une réinstallation explicite :

```bash
python -m pip install --index-url https://pypi.org/simple --force-reinstall --no-cache-dir "cartomize[notebook]==1.0"
```

Le [guide de démonstration](docs/DEMONSTRATION_1.0.md) donne également les commandes d’installation du wheel téléchargé et la vérification de sa construction.

## Espace de travail

L’explorateur ouvre les fichiers locaux et les projets Cartomize. Le catalogue classe les 21 pages de traitement par domaine et propose une recherche. Par défaut, les paramètres sont à droite de la carte et les résultats s’ouvrent dans des onglets intégrés.

Les panneaux et les vues de résultat se détachent, se redimensionnent, s’agrandissent et se réancrent. Pendant le déplacement d’une barre de titre, des repères indiquent les positions disponibles et l’emplacement retenu. Les panneaux peuvent aussi être regroupés en onglets. **F11** agrandit la vue centrale, **Échap** rétablit la disposition ou annule un déplacement ; **Affichage → Rétablir la disposition** retrouve l’organisation initiale. Les valeurs des formulaires et l’état des cartes sont conservés. Voir le [guide de l’espace dynamique](docs/DYNAMIC_WORKSPACE.md).

Le panneau inférieur réunit la console Python, les journaux, les données chargées et le diagnostic de l’environnement. La console utilise un processus distinct pour permettre l’interruption du code sans fermer l’application. Les thèmes Clair, Sombre et Système, la taille du texte et la disposition des panneaux sont mémorisés.

Les cartes proposent zoom, déplacement, valeurs de pixels, légendes, métadonnées et comparaison avec emprises liées. Les descriptions longues sont repliées dans **Aide** ; les unités, contrôles et messages de traitement restent visibles. Les projets enregistrés dans l’ancienne disposition restent lisibles.

## Fonctionnalités

| Domaine | Opérations |
|---|---|
| Préparation multispectrale | Diagnostic de couverture et de lacunes, proposition de scènes, calibration, masques QA/SCL, mosaïque, assemblage multibande, extraction, composition colorée, export des bandes |
| Raster | 18 indices spectraux, calculatrice, reclassification, statistiques focales, zonales et multirasters, superficies, transitions |
| Classification | Forêts aléatoires, arbres extrêmement aléatoires, K-moyennes, validation et modèles enregistrés |
| Vecteur | Anneaux de distance et bilans, table croisée de surfaces par zone, conversion et conditionnement, harmonisation de schémas et fusion avec provenance, qualité avec rapports, topologie, doublons, sélections, superpositions, jointures, synthèses par zone, découpage, tampons, dissolution avec agrégation, mesures, reprojection, réparation, géométries dérivées, coordonnées XY et derniers relevés |
| Terrain et réseaux | Dérivées topographiques, convolution, drainage D8, bassins versants et plus court chemin |
| Cartographie | Couches, symbologie, étiquettes, 24 maquettes, cadres, légendes, échelles, atlas, PDF/PNG/SVG |
| Automatisation | Plans, 55 opérateurs chaînables, recettes et production en série |
| Projets | Sessions JSON, archives CMZ, catalogue des résultats et restauration des vues |

## Exemple Python

```python
import cartomize as cm

carte = cm.Map(title="Localisation des villages", crs="EPSG:32733")
carte.add_layer("villages.gpkg", name="Villages", labels="nom")
carte.export("villages.pdf", dpi=300)
```

Les opérations vectorielles utilisent les objets GeoPandas. Les fichiers GeoTIFF conservent leurs valeurs scientifiques séparément des réglages d’affichage.

## Couverture et procédures expertes

Le [parcours automatique](docs/IMAGERY_AUTOMATIC.md) part des **scènes, des bandes choisies et de la zone d’étude**. Il mesure la couverture, sélectionne les scènes utiles, calibre les valeurs, applique les masques QA/SCL, harmonise les projections et les résolutions, réalise une mosaïque si elle est nécessaire et découpe les produits sur le polygone. Il peut rechercher des compléments dans un catalogue configuré, avec limites de téléchargement. Un refus conserve les cartes des lacunes ; une couverture partielle acceptée reste identifiée. Le [guide de démonstration](docs/DEMONSTRATION_1.0.md) décrit le même parcours dans la fenêtre et dans Jupyter.

Le [diagnostic d’imagerie](docs/IMAGERY_AUDIT.md) mesure séparément l’emprise, la présence des bandes et les pixels utilisables après les masques. Il propose une scène unique, une mosaïque ou la recherche de scènes complémentaires. Le [tutoriel 13](tutorials/notebooks/13_diagnostic_automatique.ipynb) exécute cette décision puis le prétraitement, le NDVI et les statistiques zonales sur des données simulées.

L’[inventaire de 123 procédures](docs/EXPERT_PROCEDURES.md), également disponible en [JSON](docs/EXPERT_PROCEDURES.json), relie les procédures QGIS/ArcGIS aux fonctions réellement présentes : **20 disponibles, 41 partielles et 62 absentes**. Ces statuts portent sur des procédures expertes complètes ; ils ne sont pas un comptage des opérateurs du logiciel. Les fonctions partielles gardent leurs limites explicites, notamment pour le radar, les corrections atmosphériques de niveau 1, la validation avancée et les réseaux soumis à des restrictions.

Le [module M08](docs/VECTOR_QUALITY.md) et le [cours 14](tutorials/notebooks/14_qualite_vectorielle.ipynb) exécutent les procédures G01–G03 depuis Python, Jupyter et l’interface. Chaque opération conserve les diagnostics et les entités écartées.

Le [parcours G01 complété](docs/G01_GEOMETRY_QUALITY.md) et le [cours 17](tutorials/notebooks/17_g01_controle_reparation_geometries.ipynb) précisent le choix d’une couche multicouche, les règles de réparation et les unités de la grille XY. Les fichiers « avant », corrigés et écartés restent raccordables au rapport par leurs positions explicites ou un identifiant métier. Les changements dus à GEOS et ceux dus à la grille sont distincts. Chaque produit GeoPackage est relu avant publication pour contrôler ses valeurs et ses géométries exactes.

Le [module M09](docs/VECTOR_REPROJECTION.md) et le [cours 15](tutorials/notebooks/15_reprojection_vectorielle_par_lot.ipynb) terminent G04. Ils découvrent les couches des fichiers et dossiers, examinent les transformations disponibles et produisent un lot avec un GeoPackage par couche, un CSV et un manifeste. Les fichiers sources restent conservés.

Le [module M10](docs/VECTOR_MERGE.md) et le [cours 16](tutorials/notebooks/16_harmonisation_fusion_vectorielle.ipynb) terminent G05. Ils réunissent des schémas différents dans une couche commune, avec conversions contrôlées, valeurs nulles distinctes des zéros et provenance par enregistrement. La fusion conserve les géométries et leurs éventuels recouvrements.

Le [module M11](docs/DATA_CONVERSION.md) et le [cours 18](tutorials/notebooks/18_conversion_conditionnement.ipynb) terminent G06. Une page « Conversion et formats » réunit le choix de couche, les formats vectoriels, la livraison GeoTIFF/COG et les paramètres de précision, compression et NoData. Chaque sortie est intégralement relue et comparée avant publication.

Le [module M12](docs/VECTOR_SELECTION.md) et le [cours 19](tutorials/notebooks/19_extraction_attributaire_spatiale.ipynb) terminent G07. Dans la page Vecteur, « Extraction avec bilan » combine les critères, publie les retenus et les exclus sans modifier leurs attributs et explique chaque décision dans un rapport. Les deux partitions sont réutilisables dans les plans.

Le [module M14](docs/VECTOR_RINGS.md) et le [cours 21](tutorials/notebooks/21_anneaux_distance.ipynb) terminent G12. Dans la page Vecteur, « Anneaux de distance avec bilan » produit les couronnes, les intervalles, le registre des sources et les bilans. Les géométries, attributs et tables sont relus avant publication.

Le [module M13](docs/VECTOR_TABULATION.md) et le [cours 20](tutorials/notebooks/20_table_croisee_surfaces.ipynb) terminent G09. Dans la page Vecteur, « Table croisée des surfaces » produit intersections, matrice, bilan par zone, catégories, lacunes et recouvrements. Les GeoPackage et CSV sont vérifiés avant publication.

## Projets réels

La [validation sur projets réels](docs/REAL_PROJECTS.md) reprend des analyses des tutoriels GeoPandas et Earth Lab : équipements et occupation du sol à Paris, sites miniers et aires protégées en RDC, MNT/MNS et hauteur de canopée au Colorado. Elle compare les valeurs, géométries, SCR et masques et exerce également les commandes graphiques sur les données téléchargées.

```bash
python scripts/validate_real_projects.py --data .real-project-data --output reports/real-projects
```

Le dossier de sortie contient la correspondance des étapes, les résultats numériques, la provenance des sources, les cartes et les captures de l’interface. Le rapport précise les opérations exécutées et les démonstrations externes non couvertes.

## Documentation

[Interface](docs/WORKBENCH.md), [traitements graphiques](docs/DESKTOP.md), [visualisation](docs/RESULTS_WORKSPACE.md), [API Python](docs/PYTHON_API.md), [prétraitement multispectral](docs/IMAGERY_SELECTION.md), [statistiques zonales](docs/RASTER_STATISTICS.md), [classification](docs/CLASSIFICATION.md), [chaînes de traitements](docs/PROCESSING.md), [moteurs de calcul](docs/EXECUTION.md), [projets réels](docs/REAL_PROJECTS.md).

Le [parcours de tutoriels](tutorials/README.md) contient les notebooks de préparation multispectrale, d’analyse et de production cartographique. La [note de l’édition consolidée](docs/RELEASE_1.0.md) récapitule les modules réunis ; les notes antérieures conservent la traçabilité des développements.

## Développement et validation

Pour travailler sur les sources, cloner le dépôt puis utiliser un environnement Python activé :

```bash
git clone https://github.com/cedrick14/cartomize-python.git
cd cartomize-python
python -m pip install -e ".[dev,notebook,distributed]" pytest-timeout
python -m pytest
python -m build
python -m twine check --strict dist/*
python scripts/check_release.py dist
python scripts/verify_installed_release.py --wheel dist/cartomize-1.0-2026103001-py3-none-any.whl --output reports/installed.json
```

La validation automatise les contrôles Windows et Linux, les traitements, l’interface, les projets, les exports, la console et une installation isolée du paquet construit. Les essais CUDA et QGIS natif demandent leurs environnements respectifs. Les résultats sont associés aux versions, aux données et aux commits inscrits dans les rapports.

## Auteur et licence

Développé par **ONDON NKOUA Cédrick Belmich**.

Code : **GPL-3.0-only**. Maquettes : **CC BY 4.0**, attribuées à Cartomize / ONDON NKOUA Cédrick Belmich. Voir [LICENSE](LICENSE), [NOTICE.md](NOTICE.md) et [PROVENANCE.json](docs/PROVENANCE.json).

Signaler une anomalie dans le [suivi du projet](https://github.com/cedrick14/cartomize-python/issues), avec la version, l’environnement et un exemple reproductible.
