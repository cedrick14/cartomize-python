# Couverture des outils

Le registre comprend 52 opérateurs. Cette matrice relie 44 d’entre eux aux cours qui exécutent leurs fonctions publiques. Les huit opérateurs vectoriels ajoutés en 1.3 sont documentés dans le guide SIG et vérifiés par les tests d’intégration ; un cours dédié reste à rédiger. Elle décrit la couverture pédagogique des familles, sans prétendre tester toutes les combinaisons de paramètres. Le cours 08 montre leur insertion dans des plans ; le cours 13 exécute le prétraitement automatique M07. Le cours 14 exécute les quatre opérateurs de qualité vectorielle M08 ; le cours 15 vérifie la reprojection par lot M09 et raccorde une couche nommée à l’étape suivante. Le cours 16 harmonise les schémas, contrôle les valeurs enregistrées et poursuit la couche fusionnée dans un plan.

| Opérateur | Fonction | Cours |
|---|---|---|
| `vector.clip` | Découpage vectoriel | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.buffer` | Zone tampon | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.sjoin` | Jointure spatiale | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.nearest` | Jointure de proximité | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.dissolve` | Dissolution | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.reproject` | Reprojection vectorielle | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.reproject_batch` | Reprojection multicouche et choix géodésique | [15](notebooks/15_reprojection_vectorielle_par_lot.ipynb) |
| `vector.convert` | Conversion vectorielle vérifiée | [18](notebooks/18_conversion_conditionnement.ipynb) |
| `raster.convert` | Conversion raster et livraison COG vérifiées | [18](notebooks/18_conversion_conditionnement.ipynb) |
| `vector.merge_layers` | Harmonisation des schémas et fusion avec provenance | [16](notebooks/16_harmonisation_fusion_vectorielle.ipynb) |
| `vector.make_valid` | Réparation des géométries | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.intersection` | Intersection | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.union` | Union | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.difference` | Différence | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.symmetric_difference` | Différence symétrique | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.area` | Superficies vectorielles | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `vector.length` | Longueurs vectorielles | [01](notebooks/01_superposition_vectorielle.ipynb) |
| `raster.clip` | Extraction par masque | [05](notebooks/05_surfaces_changements.ipynb) |
| `raster.reproject` | Reprojection raster | [05](notebooks/05_surfaces_changements.ipynb) |
| `raster.reclassify` | Reclassification | [05](notebooks/05_surfaces_changements.ipynb) |
| `raster.zonal_stats` | Statistiques zonales et couverture | [03](notebooks/03_indices_algebre.ipynb), [13](notebooks/13_diagnostic_automatique.ipynb) |
| `raster.class_areas` | Superficies par classe | [05](notebooks/05_surfaces_changements.ipynb) |
| `raster.change_matrix` | Matrice de transition | [05](notebooks/05_surfaces_changements.ipynb) |
| `calculate` | Algèbre raster | [03](notebooks/03_indices_algebre.ipynb) |
| `focal` | Statistiques focales | [03](notebooks/03_indices_algebre.ipynb) |
| `reduce` | Statistiques multirasters | [03](notebooks/03_indices_algebre.ipynb) |
| `terrain` | Dérivées du terrain | [06](notebooks/06_terrain_reseaux.ipynb) |
| `convolve` | Convolution | [06](notebooks/06_terrain_reseaux.ipynb) |
| `indices` | Indices spectraux | [03](notebooks/03_indices_algebre.ipynb) |
| `background` | Masquage du fond | [09](notebooks/09_projets_controle.ipynb) |
| `composite` | Composition colorée | [02](notebooks/02_pretraitement_multispectral.ipynb) |
| `classify` | Classification supervisée | [04](notebooks/04_classification.ipynb) |
| `cluster` | Classification non supervisée | [04](notebooks/04_classification.ipynb) |
| `prepare` | Prétraitement multispectral | [02](notebooks/02_pretraitement_multispectral.ipynb) |
| `hydrology` | Analyse hydrologique D8 | [06](notebooks/06_terrain_reseaux.ipynb) |
| `routing` | Plus court chemin | [06](notebooks/06_terrain_reseaux.ipynb) |
| `stac.search` | Recherche de scènes STAC | [10](notebooks/10_catalogues_execution.ipynb) |
| `stac.download` | Téléchargement des scènes STAC | [10](notebooks/10_catalogues_execution.ipynb) |
| `imagery.audit` | Diagnostic de couverture et de lacunes | [13](notebooks/13_diagnostic_automatique.ipynb) |
| `imagery.preprocess` | Diagnostic, sélection et préparation automatique | [13](notebooks/13_diagnostic_automatique.ipynb) |

Les opérations `vector.select_attributes`, `vector.select_location`, `vector.geometry_operation`, `vector.spatial_summary`, `vector.join_attributes`, `vector.latest_records`, `vector.from_xy` et `vector.validate` sont décrites dans [SIG_WORKFLOWS.md](../docs/SIG_WORKFLOWS.md). Leur chaîne est exercée dans [test_vector_registry.py](../tests/test_vector_registry.py).

## Fonctions complémentaires

| Famille | Contenu | Référence |
|---|---|---|
| Préparation | Scènes, correspondances, masques, bandes séparées, composition et couverture | Cours 00, 02 et 13 |
| Indices | 18 indices, registre extensible, 7 statistiques focales et 7 réductions | Cours 03 |
| Classification | K-moyennes, forêt aléatoire, Extra Trees, confiance, modèle sauvegardé et validation | Cours 04 |
| Cartographie | Superposition, classes, étiquettes, catalogue de 24 maquettes, cadres, tableaux, graphiques, atlas et exports | Cours 01 et 07 |
| Automatisation | Évaluation, proposition, plan dépendant, recettes, variables, associations et production en série | Cours 08 |
| Projets | Analyse, copies masquées, restauration des sources, sessions JSON/CMZ, empreintes et révisions | Cours 09 |
| Catalogues | Recherche et téléchargement HTTP sur un service local de démonstration, manifeste et empreintes | Cours 10 |
| Reprojection | Découverte des couches, sélection d’opérations, références numériques et sorties nommées des plans | Cours 15 |
| Harmonisation | Correspondances, conversions, types et valeurs manquantes, provenance et contrôle SQLite | Cours 16 |
| Données réelles | Cinq jeux de données, emprises, atlas de concessions, groupes et audit des classes | Cours 11 et 12 |
| Fenêtre et vues | Lancement, panneaux, inspection, comparaisons et transfert des sorties | [Guide manuel](DESKTOP_AND_EXTENSIONS.md) |
| Moteurs externes | QGIS/ArcGIS Pro, Dask et CUDA : prérequis, exemples conditionnels et limites | [Guide des extensions](DESKTOP_AND_EXTENSIONS.md) |

Les exercices autonomes n’exécutent pas QGIS, ArcGIS Pro ni CUDA. Le service STAC de démonstration ne vérifie pas la disponibilité d’un fournisseur distant. Les 24 maquettes sont inventoriées ; la planche du cours 07 illustre le paramétrage des éléments.

| Opérateurs de qualité vectorielle | Cours |
|---|---|
| `vector.audit_geometries`, `vector.repair_geometries`, `vector.check_topology`, `vector.deduplicate` | [14 — Qualité vectorielle](notebooks/14_qualite_vectorielle.ipynb) |
