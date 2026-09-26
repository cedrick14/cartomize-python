# Logique des traitements SIG et de la production cartographique

Audit du 26 septembre 2026. Version étudiée : 0.8.1a2. Corrections préparées : 0.8.2a1.

## Principe de fonctionnement

L’assistant part d’un objectif et des données réellement disponibles. Il propose les étapes nécessaires, vérifie leurs entrées et transmet des résultats identifiés. Une carte administrative peut commencer avec des couches vectorielles déjà préparées ; une carte d’occupation du sol peut demander une préparation multispectrale puis une classification. La classification et les indices ne sont pas des étapes obligatoires de toute carte.

Trois opérations doivent conserver des noms distincts :

- **Mosaïque** : assemblage spatial de scènes compatibles couvrant différentes portions de l’emprise.
- **Assemblage multibande** : réunion des bandes spectrales sur une grille commune dans un GeoTIFF scientifique.
- **Composition colorée** : affectation de trois bandes aux canaux d’affichage rouge, vert et bleu, avec étirement pour la visualisation.

La composition colorée ne remplace pas les valeurs scientifiques. Les indices et la classification utilisent le multibande scientifique. Une mosaïque de dates différentes ne représente pas une acquisition unique ; son autorisation doit être explicite. Les statistiques entre dates constituent une autre opération.

## Des bandes aux analyses

| Étape | Contrôles et décisions | Produit attendu |
|---|---|---|
| Définition du projet | Objectif, emprise, dates, précision spatiale, sorties | Paramètres du projet |
| Importation | Fichiers, métadonnées, capteur, niveau, scène et rôle spectral | Inventaire des bandes par scène |
| Contrôle initial | Lisibilité, géoréférencement, bandes manquantes, doublons, unités, dates, QA/SCL | Erreurs bloquantes et avertissements motivés |
| Calibration et masques | Facteurs propres au produit ; NoData, nuages, ombres et saturation disponible | Valeurs physiques et validité des pixels |
| Grille commune | SCR projeté adapté, résolution, alignement, rééchantillonnage | Bandes spatialement compatibles |
| Mosaïque facultative | Compatibilité des scènes ; priorité dans les recouvrements | Couverture spatiale cohérente |
| Assemblage multibande | Ordre explicite des bandes, descriptions et unités | GeoTIFF scientifique multibande |
| Extraction par masque | Polygone valide, emprise et pixels extérieurs | Multibande limité à la zone d’étude |
| Composition facultative | Canaux RVB disponibles, étirement, transparence | GeoTIFF de visualisation séparé |
| Analyses | Bandes requises, formule, références et paramètres de méthode | Indices, classes, statistiques ou autres rasters |
| Évaluation | Références indépendantes ou groupes réservés, matrice de confusion, incertitudes | Rapport de validation et limites |

La grille cible peut être calculée dès que l’emprise est connue afin de limiter la production aux pixels utiles. Cela ne change pas l’ordre scientifique : les masques et la calibration précèdent l’interpolation. Le moteur choisit la même scène pour toutes les bandes d’un pixel de mosaïque afin de préserver sa cohérence spectrale. Les masques catégoriels sont rééchantillonnés au plus proche voisin. Pour les réflectances, le choix du rééchantillonnage est explicite.

Les produits Landsat Collection 2 L2 et Sentinel-2 L2A sont déjà des produits de réflectance de surface corrigés atmosphériquement. Cartomize applique leurs facteurs de quantification ; cette opération n’est pas une nouvelle correction atmosphérique. La reconnaissance utilise les métadonnées disponibles et refuse les correspondances inconnues plutôt que d’inventer des bandes.

La résolution par défaut est celle de la bande sélectionnée la plus grossière sur la grille cible. Un rééchantillonnage plus fin n’ajoute aucune information spatiale mesurée. Conserver toutes les bandes peut donc abaisser la résolution commune : les bandes doivent être choisies en fonction de l’analyse.

## Classification et analyses dérivées

La classification supervisée comporte : définition de la nomenclature, références géographiques, séparation de l’apprentissage et de l’évaluation, apprentissage, prédiction par blocs, validation et examen des erreurs. Cartomize dispose de forêts aléatoires et d’arbres extrêmement aléatoires. Il fournit une carte de classes, une confiance issue du modèle, un rapport et un modèle rechargeable. La confiance du modèle n’est pas une mesure indépendante d’exactitude.

La séparation par entités ou groupes intervient avant l’échantillonnage des pixels. Des références distinctes peuvent être fournies pour la validation. Cette séparation ne garantit pas à elle seule l’indépendance spatiale : les groupes, la représentativité et les distances entre références doivent être adaptés à l’étude. Une précision élevée sur quelques références ne certifie pas toute la carte.

Les K-moyennes produisent des groupes spectraux ; ils ne reçoivent pas automatiquement les noms « forêt », « eau » ou « culture ». Une classification déjà réalisée peut être importée directement avec sa nomenclature.

Les indices, l’algèbre raster, les statistiques focales, les réductions multirasters et les analyses de terrain constituent des branches sélectionnées selon la question. Le découpage, la reclassification, les surfaces par classe, les statistiques zonales et les matrices de changement utilisent des données compatibles, avec une gestion explicite des unités et du NoData. Il ne faut pas interpréter la valeur zéro comme un fond invalide sans vérifier sa signification.

## Des couches à la carte

La **superposition cartographique** organise l’affichage de rasters et de vecteurs. Les **opérations de superposition vectorielle** — intersection, union, différence — créent de nouvelles géométries et de nouveaux attributs. Elles ont des finalités différentes.

1. Importer les couches et vérifier géométries, SCR, attributs et emprises.
2. Définir le SCR de la carte et l’emprise d’étude. Les mesures de distance et de surface requièrent une méthode adaptée ; une simple reprojection d’affichage n’est pas une validation des mesures.
3. Préparer les copies nécessaires : réparation, découpage, masques et nomenclature.
4. Attribuer les rôles : image de fond, occupation du sol, limites, hydrographie, routes et localités. Les rôles proposés restent modifiables.
5. Organiser la symbologie et les étiquettes. Les polygones opaques peuvent cacher un raster ; les limites administratives doivent généralement être représentées par leurs contours.
6. Choisir la maquette, le format, les cadres et les échelles. Renseigner titre, légende liée aux couches, orientation, sources, auteur et informations de projection nécessaires.
7. Examiner l’aperçu et le rapport technique, puis exporter. Un atlas réutilise cette configuration avec une emprise par entité d’index.

Les 24 maquettes ne dispensent pas de vérifier le contenu. La qualité de la carte dépend aussi du contraste, de la lisibilité à la taille imprimée, de la hiérarchie visuelle et de l’adéquation à son public.

## Corrections de la logique dans la version 0.8.2a1

| Constat dans le code | Correction |
|---|---|
| Le plan de scènes et le parcours direct privilégiaient implicitement quatre bandes | Toutes les bandes importées sont conservées par défaut ; une sélection explicite est respectée |
| Les incompatibilités QA, dates ou bandes pouvaient apparaître seulement à l’exécution | Le plan vérifie ces prérequis avant de produire des fichiers |
| La composition naturelle était imposée dans le plan de scènes | Composition sélectionnable ou désactivable ; une analyse rouge/proche infrarouge peut fonctionner sans RVB |
| L’examen « occupation du sol » ne proposait pas la classification disponible | Proposition explicite de classification à partir des données scientifiques, avant la préparation cartographique |
| Les champs de validation existaient dans l’outil de classification mais pas dans le plan de l’assistant | Références de validation, libellés et groupes transmis au moteur et à l’outil |
| Le transfert depuis l’assistant pouvait choisir un RVB comme entrée de classification et écarter un raster à deux bandes | Sélection d’une entrée scientifique et refus explicite des images d’affichage |
| Les résultats de préparation alimentaient certains outils sans préremplir la classification | Transmission du multibande à la classification, aux indices et à la composition |
| La navigation mélangeait préparation, diagnostics et finition | Ordre : objectif et diagnostic, imagerie, analyses, préparation des couches, mise en page, atlas, automatisation et révision |
| Le plan automatisé exportait sans conserver un rapport technique final distinct | Rapport `quality.json` avant export ; erreurs techniques bloquantes, avertissements conservés |
| Des choix du moteur d’imagerie n’étaient pas exposés dans la fenêtre | Rééchantillonnage spectral, priorité de recouvrement et masque de saturation accessibles |

Les clés des outils et les sessions restent stables malgré le changement d’ordre de navigation. L’icône conserve ses couleurs et l’interface ses contrôles neutres.

## Couverture et limites vérifiables

Le parcours préparation → multibande → visualisation/analyse → couches → carte est implémenté et les corrections ci-dessus font l’objet de tests d’intégration. Cela ne signifie pas que tous les traitements SIG possibles existent.

- La reconnaissance automatique porte sur Landsat C2 L2 et Sentinel-2 L2A. D’autres produits demandent un manifeste explicite. La correction atmosphérique de données brutes L1, l’orthorectification générique et le traitement radar complet ne sont pas implémentés.
- La mosaïque utilise une priorité première/dernière scène valide. Elle ne réalise pas un équilibrage radiométrique universel ni une harmonisation intercapteurs automatique. Les mélanges incompatibles sont refusés.
- L’outil de préparation peut produire une sortie par scène sans mosaïque. Le plan cartographique de scènes réalise une mosaïque ; une série de cartes par acquisition passe par la préparation séparée et les recettes. Ce n’est pas un composite temporel médian.
- La validation de classification dépend des références fournies. Les surfaces corrigées de l’erreur avec intervalles de confiance selon un plan d’échantillonnage probabiliste ne sont pas produites automatiquement.
- Le contrôle technique de carte examine les géométries, attributs, classes et métadonnées. Il ne certifie ni l’exactitude thématique ni l’absence de tout conflit visuel.
- Les moteurs par blocs limitent certains besoins mémoire ; ils ne garantissent pas un traitement instantané de toute scène. Les métriques de performance doivent être mesurées sur des données et un matériel définis.
- La bibliothèque et la fenêtre sont autonomes. La reproduction intégrale d’effets spécifiques de projets QGIS/ArcGIS reste une passerelle facultative nécessitant ces moteurs.

## Références techniques

- [USGS — facteurs d’échelle Landsat L2](https://www.usgs.gov/faqs/how-do-i-use-a-scale-factor-landsat-level-2-science-products)
- [USGS — bandes de qualité Collection 2](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands)
- [Copernicus — produits Sentinel-2 et quantification](https://sentiwiki.copernicus.eu/web/s2-products)
- [GDAL — mosaïque raster](https://gdal.org/en/stable/programs/gdal_raster_mosaic.html)
- [GDAL — assemblage multibande](https://gdal.org/en/stable/programs/gdal_raster_stack.html)
- [scikit-learn — séparation apprentissage/évaluation](https://scikit-learn.org/stable/common_pitfalls.html)
- [QGIS — production cartographique](https://docs.qgis.org/3.44/en/docs/user_manual/print_layout/index.html)

Ces références définissent les principes utilisés pour l’audit ; Cartomize exécute ses moteurs Python et n’automatise pas une session de QGIS ou d’ArcGIS.
