# Catalogue des outils

Ce catalogue décrit les sources **Cartomize 1.5.0**. Les outils sont accessibles dans l’interface graphique et par l’API Python. Les traitements enregistrés peuvent également être intégrés aux plans et chaînes d’opérations.

| Rubrique | Algorithmes et produits |
|---|---|
| Assistant cartographique | Examen, plan dépendant, variantes de maquettes, exécution jusqu’aux exports et reprise de mise en page |
| Analyse du projet | Copies masquées, fond périphérique, classes éditables, application à la carte, rétablissement des sources |
| Analyse des couches | Diagnostic raster et vectoriel |
| Prétraitement multispectral | M07 automatique : contrôle de couverture, compléments STAC facultatifs, sélection des scènes, mosaïque décidée par le moteur, calibration, QA/SCL, multibande, découpage, RVB et bandes séparées ; seuil appliqué à la production, résultat partiel explicite ; mode expert et session persistante |
| Composition colorée | Quatre compositions spectrales et RVB natif ; sortie RGBA |
| Classification | Forêt aléatoire, arbres extrêmement aléatoires, K-moyennes ; classes, confiance, validation et modèle |
| Traitements vectoriels | M08 : diagnostic détaillé, réparation traçable, topologie polygonale/linéaire, doublons et exclusions ; superpositions, sélections, jointures spatiales et attributaires, tampons, dissolution, réparations, synthèses, relevés datés et coordonnées XY |
| Traitements raster | Inspection, découpage, reprojection, reclassification, statistiques zonales, surfaces et changements selon le sélecteur |
| Analyse de terrain | Pente, exposition, ombrage, TPI, TRI, rugosité et convolution par blocs |
| Indices spectraux | 18 indices intégrés, paramètres, calibration et correspondances ; registre extensible |
| Calculatrice raster | Expressions analysées sans eval, conditions, fonctions mathématiques et alignement explicite |
| Statistiques focales | Sept statistiques, voisinages complets entre blocs et comptage du NoData |
| Statistiques multirasters | Sept réductions pixel par pixel |
| Mise en page | 24 maquettes, cadres, textes mesurés, étiquettes, tableaux, graphiques, géométrie éditable, aperçu, contrôle et exports |
| Atlas cartographique | Une carte par entité, paramètres transmis depuis la mise en page |
| Production automatisée | Avec zone d’étude : prétraitement automatique et seuil de couverture avant composition colorée, superposition et export ; diagnostics conservés si la couverture bloque le calcul |
| Recettes et production en série | Recettes réutilisables, variables, associations, migration historique, manifestes jusqu’à 5 000 tâches |
| Projets SIG | Inventaire QGS/QGZ, import des sous-couches et styles pris en charge ; passerelle native optionnelle pour copie et export |
| Chaîne de traitements | 48 opérateurs, références aux résultats et produits secondaires, paramètres moteur, exécution autonome ou intégrée à la carte |
| Révision cartographique | Instantanés, empreintes, comparaison, décision nominative et contrôle de la carte |
| Visualisation des résultats | Onglets intégrés, zoom, déplacement, valeurs de pixels, légendes, métadonnées, comparaisons, tableaux et graphiques |

## Connexions entre traitements

Le catalogue des résultats transmet les fichiers aux outils compatibles. Les GeoTIFF scientifiques alimentent la classification, les indices et la composition colorée. Les couches préparées et leur nomenclature sont transmises à la mise en page. La configuration de carte peut être réutilisée pour un atlas.

Les traitements préservent les sources et enregistrent leurs sorties dans les destinations configurées. Les productions dans un nouveau répertoire sont finalisées après réussite. En production par lots, l’option de poursuite sur erreur conserve les tâches terminées.

Le [module M07](IMAGERY_AUTOMATIC.md) partage le même contrôle entre Python,
le terminal, la fenêtre et les plans. Une couverture inférieure au seuil
interrompt les étapes dépendantes, sauf acceptation explicite d’un résultat
partiel non vide. Le rapport distingue la couverture réelle complète de
l’atteinte d’un seuil réduit. Les 48 opérateurs ne correspondent pas à
48 procédures expertes intégralement achevées ; voir l’[inventaire](EXPERT_PROCEDURES.md).

## Conditions et limites

- La reconnaissance automatique des scènes couvre Landsat Collection 2 L2 et Sentinel-2 L2A. Les autres produits nécessitent un manifeste ou des correspondances explicites.
- Les classifications supervisées nécessitent des références représentatives. La validation thématique dépend du plan d’échantillonnage et de l’indépendance des références.
- Les propositions de rôles, de maquettes et de placement reposent sur des règles et restent modifiables. Le contrôle cartographique détecte des défauts techniques ; la lisibilité et la validité thématique nécessitent un examen adapté à l’étude.
- L’hydrologie utilise Priority-Flood et D8. Les modèles hydrauliques, MFD et D-infinity ne sont pas pris en charge. Le routage requiert un réseau préparé et ne gère pas toutes les restrictions routières.
- Dask prend en charge les opérateurs raster documentés. CUDA couvre l’algèbre, les indices et les réductions ; la validation matérielle nécessite un GPU compatible.
- L’import QGIS transfère les couches et les styles pris en charge. Les expressions, SVG natifs, propriétés définies par les données et certains effets figurent dans le rapport des propriétés non transférées. Le rendu natif nécessite QGIS ou ArcGIS Pro selon le projet. La validation ArcGIS Pro reste à effectuer sur une installation licenciée.

Voir les [méthodes de traitement](PROCESSING.md), les [moteurs de calcul](EXECUTION.md), la [vue des résultats](RESULTS_WORKSPACE.md) et la [validation](VALIDATION.md).

## Extraction avec bilan — ajouté en 1.10.0

M12/G07 complète les sélections simples dans la page Vecteur : critères
attributaires multiples, masque choisi par couche, combinaison ET/OU et
inversion finale. Les produits retenus et exclus conservent leurs champs et
géométries ; le rapport séparé relie chaque décision à une position source.
La publication relit intégralement les deux couches, avec leur schéma commun.
Le terminal `extract-features`, les plans, Python et le cours 19 utilisent
la même opération `vector.extract_features`. Voir le [guide G07](VECTOR_SELECTION.md).

## Conversion et formats — ajouté en 1.9.0

Le module M11/G06 relie une inspection explicite des entrées aux conversions vectorielles et raster, à la comparaison des fichiers relus et au rapport de fidélité. La page dédiée, les commandes `convert-vector` et `convert-raster`, les plans et l’API appellent le même moteur. Le [guide G06](DATA_CONVERSION.md) précise les six formats de livraison, les paramètres, les différences autorisables et les incompatibilités refusées.

## Table croisée des surfaces — ajouté en 1.11.0

M13/G09 complète le croisement de zonages et de catégories polygonales dans
l’outil Vecteur existant. La même opération `vector.tabulate_area` relie l’API,
le terminal, les plans, le cours 20 et la fenêtre. Les identités sont typées,
les doublons de groupe sont dissous, les catégories superposées font l’objet
d’une règle explicite, et les totaux distinguent couverture, lacunes, emprise
ambiguë et excès de comptage. Les quatre GeoPackage et les trois tableaux CSV
sont relus avant publication. Voir le [guide G09](VECTOR_TABULATION.md).

## Anneaux de distance — ajouté en 1.12.0

M14/G12 complète les tampons par une liste de bornes métriques, une construction fusionnée ou indépendante et des bilans de surface. Les polygones sources sont inclus ou exclus explicitement. Les identités, les composantes de petite surface et les résidus sont conservés. Les sorties sont relues avant publication ; le terminal, les plans, le notebook 21 et la fenêtre appellent le même moteur. [Guide G12](VECTOR_RINGS.md).
