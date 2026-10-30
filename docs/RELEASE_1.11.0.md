# Cartomize 1.11.0 — M13 / G09, table croisée des surfaces

Cette version complète **G09 — Croisement de zonages et occupation du sol**
dans le périmètre polygonal du [guide G09](VECTOR_TABULATION.md). Le nouveau
moteur relie les intersections à une table détaillée, une matrice et des bilans
de couverture, de lacunes et de recouvrements.

## Problème traité

Les intersections, mesures et dissolutions étaient disponibles séparément.
Leur assemblage ne fournissait pas une table prête à l’emploi avec contrôle des
catégories, règles de double comptage, totaux par zone et diagnostics géométriques.
Une somme de surfaces brutes pouvait compter plusieurs fois des objets répétés
ou superposés sans rendre cet effet visible.

`tabulate_area` regroupe les zones et catégories par identité typée, réunit les
géométries d’un même groupe et construit les cellules de surfaces. Les catégories
différentes superposées sont refusées par défaut ou mesurées avec un bilan
explicite. Les zones peuvent être analysées indépendamment ou soumises à un
refus des recouvrements entre groupes.

## Comportement livré

- **Identités exactes :** texte, entiers, booléens, dates, horodatages et décimaux
  distingués ; codes `001`/`NA`, entiers non signés et grands décimaux conservés
  par un registre de type et valeur canonique. Les horodatages avec fuseau sont
  regroupés par instant UTC ; les valeurs naïves restent distinctes.
- **Tables complètes :** toutes les combinaisons zone × catégorie, y compris
  les surfaces nulles ; table détaillée lisible et matrice à identifiants stables.
- **Mesures :** calcul planaire dans un SCR projeté choisi, conversion des unités
  linéaires, sorties en m²/ha/km² et géométries dans ce même SCR. Z/M retirés des
  copies de calcul avec dimensions sources consignées.
- **Bilans :** superficie de zone, couverture unique, surfaces non classées ou
  sans couverture, emprise de recouvrement, excès de comptage et résidus de
  fermeture. Le total sur la réunion du territoire est séparé des sommes par zone.
- **Diagnostics :** intersections, zones dissoutes, lacunes et recouvrements
  entre catégories/zones ou au sein des groupes. Les petites surfaces positives
  sont conservées ; les géométries invalides sont refusées avant et après projection.
- **Publication :** quatre GeoPackage vérifiés, trois CSV relus avec fidélité
  exacte des valeurs, schémas, audit et empreintes, synthèse et manifeste dans
  un nouveau dossier atomique. Annulation et échec ne publient pas de sortie partielle.
- **Interfaces :** API `cm.tabulate_area`, opérateur `vector.tabulate_area`,
  commande `tabulate-area`, plans et page **Vecteur → Table croisée des surfaces**.
  Les sessions et archives portables conservent paramètres et produits.
- **Pédagogie :** le [cours 20](../tutorials/notebooks/20_table_croisee_surfaces.ipynb)
  contient onze cellules autonomes avec surfaces analytiques, cas triple,
  catégories manquantes, publication, terminal, plan, annulation et carte.

## Corrections vérifiées pendant le développement

La relecture du code a identifié un risque de collision de catégories Decimal :
une normalisation dépendant du contexte aurait pu arrondir des valeurs de plus
de 28 chiffres. La normalisation canonique utilise maintenant les chiffres et
l’exposant sans arrondi. Les tests changent aussi la précision active du contexte.

Les valeurs CSV sont relues avec un convertisseur de flottants fidèle. Le
visualiseur applique cette même règle aux rapports accompagnés d’un schéma.
Les textes vides, `001` et `NA` restent des libellés ; les champs numériques
de couches et de catégories restent des noms textuels dans le terminal et les
formulaires de plans.

Le parcours Windows du cours 20 rend explicite le mode UTF-8 du processus
Python enfant qui exécute la commande, en accord avec le décodage de sa sortie
JSON. Ce correctif du notebook conserve les libellés accentués et les mêmes
calculs dans les deux systèmes.

Le jeu réel parisien a révélé un écart entre une couverture calculée en réunissant
les catégories avant découpage et les surfaces calculées catégorie par catégorie.
Le moteur construit désormais la couverture d’une zone à partir de ses cellules
mesurées. La tolérance de fermeture reste `1e-6 m² + 1e-8 × surface de référence`.
Les résidus sont conservés et aucun petit polygone n’est supprimé. L’index spatial
et le regroupement des géométries identiques bornent les comparaisons nécessaires
à l’audit des recouvrements au sein d’une catégorie.

La validation réelle utilise la projection équivalente native des données
d’occupation du sol. Elle vérifie séparément le refus des objets devenus invalides
après une autre reprojection. Aucune réparation de source n’est introduite pour
faire passer le contrôle.

## Validation de la livraison

Les résultats finaux, les empreintes des sources figées et les versions des
dépendances sont consignés dans [VALIDATION_1.11.0.json](VALIDATION_1.11.0.json).
Les résultats sur données publiques figurent dans
[VALIDATION_G09_REAL.json](VALIDATION_G09_REAL.json). Les contrôles GitHub sont
associés au commit exact de la demande d’intégration.

La suite complète sur les sources figées réussit **1 619 tests**, avec
**2 exclusions prévues et aucun échec**, en **408.966 s** sous Linux/Python
3.12.14. Les 150 nouvelles régressions se répartissent entre le
moteur (99), les interfaces (14), la fenêtre (16) et l’oracle indépendant (21).
Les sources, tests, scripts et workflows restent identiques avant et après
la passe complète.

Les **13 scénarios réels** réussissent : 80 zones × 8 classes donnent 640 cellules,
dont 283 cellules nulles, avec 357 géométries d’intersection. Les sept fichiers
sources sont inchangés. Les produits sont rouverts avec contrôle des géométries,
attributs, tableaux et empreintes.

Le cours 20 exécute **11 cellules** dans un noyau neuf (6.87 s) ; le site
exporte **21 leçons**. La wheel installée hors du dépôt dans un environnement
neuf réussit **29 contrôles**, avec `pip check` réussi et **100 modules identiques
aux sources**. Les deux exclusions locales concernent CUDA et QGIS. Les
matrices Windows/Ubuntu et le contrôle QGIS distant restent attachés au commit
exact testé sur GitHub ; leurs résultats sont lus sur la révision finale de la PR.


## Données réelles et portée des références

Les essais utilisent les **80 quartiers de Paris** et **3 243 polygones
d’occupation du sol**, répartis dans **huit catégories originales**. Les sources
sont historiques, publiques et épinglées par empreinte. Leurs catégories ne sont
pas inventées ni présentées comme une description de la situation actuelle.

Une référence distincte intersecte les quartiers réels avec des bandes analytiques
par découpage Python et calcule les surfaces par la formule du lacet, avec trous,
polygones multiples et origines projetées élevées. Elle ne dépend pas de GEOS
pour les intersections ou mesures. La comparaison des polygones d’occupation
du sol réels partage GEOS ; les transformations de coordonnées partagent PROJ.
Ces portées sont enregistrées dans le rapport.

## Inventaire et distribution

G09 passe de partiel à disponible. L’inventaire conserve **123 procédures** et
**88 références** : **19 disponibles, 42 partielles et 62 absentes**. Le registre
compte **54 opérateurs** dans les **21 outils** existants. M13 prolonge M01–M12 ;
E01 reste en cours pour les autres procédures du socle. Le parcours comporte
21 leçons, dont 19 autonomes et deux dépendantes des données locales de Tuto.

La construction des paquets 1.11.0 et leur validation sont distinctes d’une
publication sur PyPI. Les rapports des versions précédentes sont conservés.
