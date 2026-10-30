# Cartomize 1.12.0 — M14 / G12, zones tampons et anneaux de distance

Cette version complète **G12 — Zones tampons et anneaux de distance** dans le
périmètre du [guide G12](VECTOR_RINGS.md). Une liste de bornes métriques produit
des anneaux, des identités sources et des bilans vérifiés dans toutes les interfaces.

## Problème traité

Les tampons simples, différences et dissolutions existaient séparément. Pour
constituer des bandes 0–100, 100–250 ou 250–500 m, il fallait assembler ces
opérations, attribuer les bornes et contrôler manuellement les surfaces. Autour
de plusieurs objets, la somme des tampons pouvait compter plusieurs fois le
même territoire sans distinguer cette somme de la surface unique.

`buffer_rings` réunit les tampons de toutes les sources à chaque distance, puis
retire l’emprise déjà occupée. Le mode indépendant répète la construction par
ligne source et rapporte les recouvrements entre séries. Le bilan distingue
l’emprise partagée une seule fois et l’excès additif de comptage.

## Comportement livré

- **Bornes explicites :** distances supérieures positives, finies, croissantes,
  exprimées en mètres ; aucun tri ou retrait silencieux de doublons.
- **Géométries :** points, lignes et polygones valides, simples ou multiparties ;
  fusion globale ou séries indépendantes ; intérieur des polygones inclus ou
  exclu explicitement. Les trous sont traités comme l’extérieur du polygone.
- **Mesure :** calcul plan dans un SCR projeté adapté, conversion des pieds,
  surfaces en m²/ha/km², sorties dans le SCR du calcul. Les arcs sont approchés
  par 1 à 1024 segments par quadrant, 16 par défaut.
- **Identités :** registre source positionnel, étiquettes typées et exactes,
  grands entiers conservés ; les étiquettes répétées ne fusionnent pas les lignes.
- **Bilans :** table complète des intervalles, surface attendue, somme et réunion,
  recouvrements, excès, lacunes, débordements et résidus signés. Les composants
  d’aire positive sont conservés sans filtre, grille ou réparation implicite.
- **Publication :** deux GeoPackage et deux CSV relus intégralement, schémas,
  audit, résumé et manifeste ; neuf fichiers publiés dans un nouveau dossier
  atomique, avec annulation et protection des sources.
- **Interfaces :** API `cm.buffer_rings`, opérateur `vector.buffer_rings`, commande
  `buffer-rings`, plans et **Vecteur → Anneaux de distance avec bilan**. Sessions,
  archives portables et vues des résultats sont raccordées.
- **Pédagogie :** le [cours 21](../tutorials/notebooks/21_anneaux_distance.ipynb)
  exécute douze cellules avec formules indépendantes, points/lignes/polygones,
  cartes, publication, terminal, chaîne G12→G09, refus et annulation.

Le tampon simple existant conserve ses distances signées, attributs et sorties
dans le SCR source. G12 ne change pas son comportement.

## Validation de la livraison

Les résultats et empreintes sont consignés dans
[VALIDATION_1.12.0.json](VALIDATION_1.12.0.json). La suite complète sur sources
figées réussit **1 821 tests**, avec **deux exclusions prévues et aucun échec**,
en **629.740 s** sous Linux/Python 3.12.14. Les **202 nouvelles régressions**
couvrent le moteur (118), les interfaces (14), la fenêtre (27) et les oracles
arithmétiques indépendants (43). Les sources, tests, scripts et workflows
restent identiques avant et après cette passe.

Les deux exclusions locales concernent CUDA et QGIS. Les matrices Windows et
Ubuntu ainsi que le contrôle QGIS distant restent associés au commit exact
testé sur GitHub. Les résultats distants sont consignés dans la demande
d’intégration, séparément du rapport local horodaté.

Le cours 21 réussit **12 cellules** dans un noyau neuf ; le site exporte
**22 leçons**, dont 20 autonomes et deux dépendantes de données locales. La
wheel installée hors du dépôt dans un environnement neuf réussit **32 contrôles**,
avec `pip check` réussi. Ses **102 modules** sont identiques aux sources validées.
Les quatre contrôles du formulaire compact G12 couvrent deux modes et les
polices 12/16 à 1100 × 740, sans défilement horizontal.

## Références numériques et données publiques

Les [15 scénarios de validation](VALIDATION_G12_REAL.json) réussissent tous.
Une référence arithmétique calcule les surfaces des polygones réguliers,
capsules de segments droits, rectangles et trous rectangulaires sans demander
de tampon ou d’intersection à GEOS. Les cas triples distinguent une emprise de
recouvrement de 800 m² et un excès de comptage de 1 600 m².

Le jeu minier public historique contient 3 687 enregistrements. Une sélection
géographique déterministe de **240 points** produit **960 anneaux indépendants**,
vérifiés cellule par cellule ; l’écart arithmétique maximal est
**9,555 × 10⁻⁷ m²**. Les **80 quartiers de Paris** produisent **320 anneaux
indépendants**, ainsi que des bandes fusionnées. Leurs 80 limites dérivées
testent explicitement le cas linéaire, sans être présentées comme des routes.

Les références de formes irrégulières partagent GEOS avec le moteur ; PROJ et
GDAL restent communs à la reprojection et à la lecture. Les deux fichiers
originaux et les sources en mémoire restent inchangés. Les publications des
mines et de Paris sont relues avec contrôle exact des géométries WKB, attributs,
bornes, valeurs CSV, audits et empreintes.

La fermeture d’un bilan vérifie les géométries construites. Elle ne certifie
pas la précision terrain, le choix du SCR ou la finesse effective des distances
devant des coordonnées très grandes. Les instantanés historiques ne décrivent
pas l’activité minière ou la situation parisienne actuelle.

## Inventaire et distribution

G12 passe de partiel à disponible. L’inventaire conserve **123 procédures** et
**88 références** : **20 disponibles, 41 partielles et 62 absentes**. Le registre
compte **55 opérateurs** dans les **21 outils** existants. Les anneaux automatiques
complètent aussi une étape de SA02, qui reste partielle pour ses analyses du
support observé et ses comparaisons statistiques. M14 prolonge M01–M13 ; E01
reste en cours. La prochaine procédure partielle est **G14 — Jointure d’enquêtes
et de tables**.

Les paquets 1.12.0 et leur intégration GitHub sont distincts d’une publication
sur PyPI. Les rapports des versions précédentes sont conservés.
