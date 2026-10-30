# Cartomize 1.10.0 — M12 / G07, extraction avec bilan

Cette version termine **G07 — Extraction attributaire et spatiale** dans
le périmètre du [guide G07](VECTOR_SELECTION.md). Les sélections simples
restent disponibles ; une opération complète ajoute les exclus, les motifs
par enregistrement et le bilan des critères combinés.

## Problème traité

Les anciennes sélections renvoyaient seulement les entités retenues. Elles
ne donnaient ni la partition complémentaire, ni une explication de chaque
exclusion, ni les effectifs des intersections entre critères attributaires
et spatiaux. Un index dupliqué pouvait aussi rendre ambiguë la reconstruction
des décisions à partir d'une couche déjà filtrée.

Le moteur `extract_features` calcule les décisions par position source et
renvoie les deux partitions complètes. Les attributs et les géométries restent
intacts ; le rapport contient les informations de suivi. La sélection ne
constitue pas un découpage géométrique.

## Comportement livré

- **Critères attributaires :** comparaisons exactes, textes littéraux,
  appartenance à une liste et valeurs manquantes ; combinaison tous/au moins
  un. Entiers 64 bits, booléens, dates natives et horodatages sont contrôlés.
- **Localisation :** prédicat planaire dans le sens source → réunion du
  masque. Le masque est aligné dans le SCR source ; recouvrements et doublons
  du masque ne dupliquent pas les entités extraites.
- **Combinaison :** ET/OU entre les blocs, puis inversion finale facultative.
  Les quatre cases attributaire/spatial sont comptées avant inversion.
- **Traçabilité :** une décision par ligne source, positions sources et
  positions dans les retenus/exclus, critères individuels, blocs, état
  géométrique et motif. Un identifiant métier unique peut être conservé.
- **Publication :** deux GeoPackage vérifiés intégralement, CSV avec schéma,
  audit JSON typé et synthèse. Dossier neuf atomique, avec protection des
  sources et annulation sans sortie partielle.
- **Parcours :** API Python, commande `extract-features`, opérateur
  `vector.extract_features`, plans, **Vecteur → Extraction avec bilan** et
  [cours 19](../tutorials/notebooks/19_extraction_attributaire_spatiale.ipynb).

## Corrections vérifiées pendant le développement

Les dates natives préservées par G06 étaient des objets Python, tandis que
le filtre historique reconnaissait surtout le dtype pandas datetime64.
Les sélections simples et le nouveau moteur utilisent maintenant la même
normalisation contrôlée. Un horodatage n'est pas tronqué en date, les fuseaux
ne sont pas ajoutés ou retirés implicitement, et les booléens ne servent pas
de substituts aux nombres dans les filtres typés. Les horodatages textuels
relatifs ou ambigus sont refusés pour conserver des critères reproductibles.
Les colonnes numériques objet et catégorielles comparent aussi leurs grands
entiers sans les convertir en flottants.

Une revue indépendante a révélé que l'inférence de type sur chaque partition
pouvait transformer une colonne DATE en TEXT lorsqu'elle ne contenait plus
que des valeurs nulles. Le schéma est maintenant établi sur **la source
entière** puis imposé aux deux sorties. Les tests vérifient DATE, DATETIME
et BOOLEAN directement dans SQLite, avec des sources en mémoire sans
métadonnées de type ajoutées par l'utilisateur.

Le tableau des décisions contient des booléens nuls quand un bloc est absent.
La lecture de ces CSV utilise leur schéma et leur séparateur connus, ce qui
préserve les colonnes entièrement nulles et les identifiants `001` ou `NA`.

Les contrôles graphiques ont également révélé une liste de critères de largeur
nulle et une restauration qui reconstruisait des contrôles G07 dormants.
Le formulaire garde une largeur utilisable et ne change plus les réglages
d'un autre outil restauré. Les tests compacts contrôlent les textes 12/16 px
et interdisent le défilement horizontal.

## Validation locale finale

| Contrôle | Résultat |
|---|---|
| Suite complète, sources figées | **1 469 réussis, 2 exclus, 0 échec**, en 492,12 s |
| Régressions ajoutées | **155** : 109 moteur, 14 interfaces, 21 fenêtre, 11 oracle spatial |
| Données réelles G07 | **9 scénarios réussis**, 10 fichiers sources inchangés |
| Cours 19 dans un noyau neuf | **9 cellules réussies**, 3,93 s |
| Paquet installé hors du dépôt | **26 contrôles réussis**, 98 modules identiques aux sources |
| Édition HTML du parcours | **20 leçons exportées** |

Les deux exclusions de la suite locale concernent CUDA et QGIS natif. La
matrice GitHub apporte les contrôles Windows/Ubuntu et le moteur QGIS séparé.
Le rapport de livraison est généré avant la création de la demande
d'intégration ; son état CI décrit cet instant. Les résultats distants
se consultent sur le commit exact de cette demande.

## Données réelles et limites des références

Les **80 quartiers de Paris** servent à contrôler une combinaison population
et masque polygonal, avec un masque répété et des index dupliqués. Les
**3 687 visites minières de RDC** servent à combiner projet IPIS, effectif
positif, date de visite et position dans Kahuzi. Le rapport vérifie chaque
attribut, chaque WKB, l'ordre, les SCR, les décisions et la partition publiée.
Le stockage DATE est contrôlé indépendamment dans SQLite.

Le prédicat point/polygone RDC est calculé aussi par un algorithme de ray
casting Python indépendant de GEOS. La transformation du masque partage
PROJ avec l'application. Les intersections polygonales de Paris partagent
GEOS ; elles contrôlent l'intégration et ne constituent pas une validation
indépendante du moteur géométrique. Les données sont historiques, épinglées
par empreinte ; les valeurs ne décrivent pas une situation actuelle.

Les résultats et empreintes exacts se trouvent dans le
[rapport réel G07](VALIDATION_G07_REAL.json) et le
[rapport de livraison 1.10.0](VALIDATION_1.10.0.json). Les contrôles distants
Windows/Ubuntu et QGIS sont associés à la révision exacte de la demande
d'intégration. Le nouveau contrôle réel G07 fait partie du workflow exécuté
avant fusion.

## Cours, paquet et inventaire

Le cours 19 comporte **neuf cellules exécutables autonomes** : cas analytiques
simulés, ET/OU, inversion, frontière, dates natives, entiers exacts, publication,
SQLite, reprise des exclus dans un plan et annulation. Le contrôle du paquet
installé hors du dépôt exerce aussi le nouveau moteur et son worker graphique.

Le registre compte **53 opérateurs**, répartis dans les **21 outils** existants
de la fenêtre. L'inventaire conserve **123 procédures et 88 références** :
G07 passe de partiel à disponible, soit **18 disponibles, 43 partielles et
62 absentes**. M12 complète M01–M11. Les rapports historiques restent inchangés.
La construction d'un paquet 1.10.0 ne constitue pas une publication sur PyPI.
