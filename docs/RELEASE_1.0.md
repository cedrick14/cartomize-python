# Cartomize 1.0 — Espace de travail dynamique

Édition du 30 octobre 2026, préparée pour la démonstration du 1er novembre 2026.

## Contenu retenu

Cette édition réunit le code de la branche principale après l’intégration de
G12 (base `c81e798b24da8bbb902f77f49008bb556c71e784`) et les corrections du
parcours de démonstration. Le numéro du paquet et `cartomize.__version__`
sont tous deux **1.0**. Le wheel porte l’identifiant de construction `2026103001`
(`cartomize-1.0-2026103001-py3-none-any.whl`) afin de distinguer la correction
de l’interface de la construction précédente ; cet identifiant ne change pas le numéro de version. L’interface
et Python utilisent le même moteur.

## Interface dynamique

La disposition initiale et les thèmes sont conservés. L’explorateur, le
catalogue, les paramètres, la console et les vues de résultat deviennent
des panneaux déplaçables et redimensionnables.

- **Placement guidé** : déplacer une barre de titre affiche les positions
  possibles, l’aperçu de la destination et le regroupement en onglets.
- **Détacher et agrandir** : un panneau peut devenir une fenêtre indépendante,
  être maximisé puis réancré. Les résultats retrouvent les onglets centraux
  avec « Réintégrer dans les vues ».
- **Conserver le travail** : le déplacement conserve les paramètres saisis,
  les cartes et leurs réglages. Les résultats rafraîchis retrouvent leur
  emplacement et leur groupe.
- **Retrouver la disposition** : F11 agrandit la vue centrale, Échap restaure
  l’affichage ou annule le déplacement. Le menu Affichage permet de rouvrir
  un panneau masqué et de restaurer l’organisation initiale.
- **Alléger les formulaires** : les descriptions longues sont repliées dans
  Aide. Les commandes, unités, diagnostics et erreurs restent accessibles.

La disposition locale est mémorisée entre les lancements. Les projets
enregistrent les positions des vues avec des propriétés JSON contrôlées.
Le [guide pratique](https://github.com/cedrick14/cartomize-python/blob/main/docs/DYNAMIC_WORKSPACE.md)
détaille ces commandes ; la démonstration fournit les mêmes indications.

## Modules réunis

| Ensemble | Contenu |
|---|---|
| Prétraitement optique automatique | Reconnaissance des produits et bandes, calibration, masques, couverture de la zone, sélection des scènes, harmonisation de grille, mosaïque si nécessaire, découpage et produits scientifiques/visuels. |
| Qualité vectorielle | Diagnostic et réparation des géométries, précision XY explicite, topologie et doublons, rapports avant/après. |
| G04 | Reprojection vectorielle par lot et contrôles des transformations. |
| G05 | Harmonisation des schémas et fusion avec provenance. |
| G06 | Conversion et conditionnement vectoriel/raster avec relecture des sorties. |
| G07 | Extraction attributaire et spatiale avec retenus, exclus et bilan. |
| G09 | Table croisée de surfaces, catégories, lacunes et recouvrements. |
| G12 | Zones tampons et anneaux de distance, identités des sources et bilans. |
| Socle commun | Traitements raster, indices, classification, terrain, réseaux, cartes et maquettes, plans, console et projets. |

Les procédures futures de l’inventaire, dont G14, ne sont pas ajoutées à cette
livraison. Les notes historiques du dépôt conservent les preuves de développement
et de validation des modules réunis ici.

## Démonstration principale

L’utilisateur choisit **les scènes, les bandes et la zone d’étude**. Le mode
« Automatique : contrôler et préparer » mesure la couverture utile, choisit une
scène suffisante ou les scènes contributrices, aligne les grilles, effectue les
masques et la calibration, réalise la mosaïque utile et découpe sur le polygone.
Les bandes scientifiques, le multibande et la composition colorée sont des
produits distincts. Le rapport conserve la décision et les scènes utilisées.

Une couverture insuffisante produit un diagnostic et une carte des lacunes.
Un résultat partiel n’est produit que selon la politique explicitement choisie.
Les scènes à dates différentes exigent également un choix explicite.

Le [guide de démonstration](https://github.com/cedrick14/cartomize-python/blob/main/docs/DEMONSTRATION_1.0.md) donne le parcours graphique,
le code Jupyter et les conditions d’entrée des scènes USGS.

## Installation et distribution

Le wheel de cette édition inclut les modules déjà terminés et les points d’entrée
`cartomize` et `cartomize-desktop`. L’option `gui` installe l’interface ; l’option
`notebook` installe aussi JupyterLab et son noyau Python.

Les fichiers de livraison comprennent le wheel installable, l’archive source
et `cartomize-1.0-presentation.zip`, qui rassemble les guides, le notebook 22
et des scènes pédagogiques synthétiques prêtes à charger dans l’interface.
Décompresser le ZIP et suivre `LISEZ_MOI.md`.

Si une construction précédente de **1.0** est déjà installée, utiliser
`--force-reinstall --no-cache-dir` puis vérifier `Build: 2026103001`, ou
installer directement le wheel de cette livraison. Le
[suivi de publication](https://github.com/cedrick14/cartomize-python/blob/main/docs/PUBLICATION.md)
indique les fichiers disponibles et les vérifications exécutées.
