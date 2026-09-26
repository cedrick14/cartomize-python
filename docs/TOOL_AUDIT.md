# Catalogue des outils

Les outils sont accessibles dans l’interface graphique et par l’API Python. Les traitements enregistrés peuvent également être intégrés aux plans et chaînes d’opérations.

| Rubrique | Algorithmes et produits |
|---|---|
| Assistant cartographique | Examen, plan dépendant, variantes de maquettes, exécution jusqu’aux exports et reprise de mise en page |
| Analyse du projet | Copies masquées, fond périphérique, classes éditables, application à la carte, rétablissement des sources |
| Analyse des couches | Diagnostic raster et vectoriel |
| Prétraitement multispectral | Tableau des bandes par scène, correspondances manuelles, calibration, QA/SCL, mosaïque facultative, assemblage multibande, extraction par masque, canaux RVB et GeoTIFF monobandes séparés ; session persistante |
| Composition colorée | Quatre compositions spectrales et RVB natif ; sortie RGBA |
| Classification | Forêt aléatoire, arbres extrêmement aléatoires, K-moyennes ; classes, confiance, validation et modèle |
| Traitements vectoriels | 13 opérations GeoPandas, dont superposition, jointure, tampon, dissolution et réparation |
| Traitements raster | Inspection, découpage, reprojection, reclassification, statistiques zonales, surfaces et changements selon le sélecteur |
| Analyse de terrain | Pente, exposition, ombrage, TPI, TRI, rugosité et convolution par blocs |
| Indices spectraux | 18 indices intégrés, paramètres, calibration et correspondances ; registre extensible |
| Calculatrice raster | Expressions analysées sans eval, conditions, fonctions mathématiques et alignement explicite |
| Statistiques focales | Sept statistiques, voisinages complets entre blocs et comptage du NoData |
| Statistiques multirasters | Sept réductions pixel par pixel |
| Mise en page | 24 maquettes, cadres, textes mesurés, étiquettes, tableaux, graphiques, géométrie éditable, aperçu, contrôle et exports |
| Atlas cartographique | Une carte par entité, paramètres transmis depuis la mise en page |
| Production automatisée | Préparation des scènes, assemblage multibande, composition colorée, superposition et export |
| Recettes et production en série | Recettes réutilisables, variables, associations, migration historique, manifestes jusqu’à 5 000 tâches |
| Projets SIG | Inventaire QGS/QGZ, import des sous-couches et styles pris en charge ; passerelle native optionnelle pour copie et export |
| Chaîne de traitements | 34 opérateurs, références aux résultats et produits secondaires, paramètres moteur, exécution autonome ou intégrée à la carte |
| Révision cartographique | Instantanés, empreintes, comparaison, décision nominative et contrôle de la carte |

| Visualisation des résultats | Onglets intégrés, zoom, déplacement, valeurs de pixels, légendes, métadonnées, comparaisons, tableaux et graphiques |

## Connexions entre traitements

Le catalogue des résultats transmet les fichiers aux outils compatibles. Les GeoTIFF scientifiques alimentent la classification, les indices et la composition colorée. Les couches préparées et leur nomenclature sont transmises à la mise en page. La configuration de carte peut être réutilisée pour un atlas.

Les traitements préservent les sources et enregistrent leurs sorties dans les destinations configurées. Les productions dans un nouveau répertoire sont finalisées après réussite. En production par lots, l’option de poursuite sur erreur conserve les tâches terminées.

## Conditions et limites

- La reconnaissance automatique des scènes couvre Landsat Collection 2 L2 et Sentinel-2 L2A. Les autres produits nécessitent un manifeste ou des correspondances explicites.
- Les classifications supervisées nécessitent des références représentatives. La validation thématique dépend du plan d’échantillonnage et de l’indépendance des références.
- Les propositions de rôles, de maquettes et de placement reposent sur des règles et restent modifiables. Le contrôle cartographique détecte des défauts techniques ; la lisibilité et la validité thématique nécessitent un examen adapté à l’étude.
- L’hydrologie utilise Priority-Flood et D8. Les modèles hydrauliques, MFD et D-infinity ne sont pas pris en charge. Le routage requiert un réseau préparé et ne gère pas toutes les restrictions routières.
- Dask prend en charge les opérateurs raster documentés. CUDA couvre l’algèbre, les indices et les réductions ; la validation matérielle nécessite un GPU compatible.
- L’import QGIS transfère les couches et les styles pris en charge. Les expressions, SVG natifs, propriétés définies par les données et certains effets figurent dans le rapport des propriétés non transférées. Le rendu natif nécessite QGIS ou ArcGIS Pro selon le projet. La validation ArcGIS Pro reste à effectuer sur une installation licenciée.

Voir les [méthodes de traitement](PROCESSING.md), les [moteurs de calcul](EXECUTION.md), la [vue des résultats](RESULTS_WORKSPACE.md) et la [validation](VALIDATION.md).
