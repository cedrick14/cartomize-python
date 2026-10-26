# Cartomize 1.8.0 — G01, contrôle et réparation des géométries

Cette version termine le parcours **G01** avant la poursuite des autres
procédures. Elle complète le moteur M08, les sorties persistantes et les
interfaces. Le travail est relié aux exigences de l'inventaire dans le
[guide G01](G01_GEOMETRY_QUALITY.md).

## Problèmes corrigés

Un GeoPackage multicouche pouvait être traité sur sa première couche sans
choix explicite. La tolérance prévue par l'inventaire n'était pas exposée.
Le chemin d'écriture pouvait changer des types de géométrie ou d'attribut,
arrondir un horodatage et rendre identiques deux identifiants distincts.
Les zéros initiaux d'un identifiant disparaissaient aussi dans le tableau du
rapport. Enfin, le bundle ne conservait pas toute la couche originale pour
une comparaison après fermeture de la session.

## Comportement livré

- **Choix de couche :** `layer` dans l'API, la commande `process`, les plans
  et la fenêtre. Un fichier multicouche sans sélection est refusé ; les
  champs d'identifiant proposés correspondent à la couche choisie.
- **Tolérance explicite :** `tolerance=0.0` désactive la grille. Une valeur
  positive est un pas XY dans les unités du SCR source projeté. La grille
  intervient après la réparation GEOS et suit les politiques de géométrie
  vide et de changement de type. `metric_crs` sert seulement aux mesures.
- **Rapport complet :** changements dus à GEOS et à la grille distingués,
  états, types, dimensions Z/M, nombres de coordonnées/composantes, empreintes
  WKB, surfaces, longueurs et deltas avant/après, avec une ligne par entrée.
- **Correspondance persistante :** produit `before` complet, puis
  `source_row`, `output_row` et `rejected_row` pour relier les originaux,
  résultats retenus et exclusions. Les attributs métier restent intacts.
- **Écriture vérifiée :** valeurs typées et géométries relues avant la
  publication atomique. DATE, DATETIME, grands entiers, NULL et attributs
  métier `fid` ou `geometry` sont contrôlés. Une perte non représentable
  provoque un refus explicite, sans résultat partiel.
- **Dimensions :** Z reste suivi par les opérations planaires ; les nouveaux
  sommets GEOS peuvent recevoir des Z interpolés. Une modification M est
  refusée avant réparation et la publication M est refusée. Les anneaux
  autonomes, y compris imbriqués dans une collection, ne peuvent pas être
  changés silencieusement en LineString.
- **Fenêtre et sessions :** actions Anomalies, Rapport et Comparer avant/après,
  emprises synchronisées, choix capturés au lancement puis restaurés. Le
  schéma compagnon du CSV préserve les identifiants, y compris dans un projet
  portable extrait sans accès au dossier d'origine.

Les règles GEOS et la grille XY ont des sens différents ; le guide explique
leurs effets et les unités. La validité contrôlée est planaire. Les objets
devenus identiques restent des enregistrements distincts. Les méthodes
`linework` et `structure`, ainsi que les décisions keep/drop/error et
allow/drop/error, restent explicites.

## Validation locale sur les sources figées

| Contrôle | Résultat |
|---|---|
| Suite complète Linux / Python 3.12.14 | **1 131 réussis**, **2 exclusions prévues**, aucun échec ; **209.075 s** |
| Nouvelles régressions G01 incluses | **57 cas** : 29 précision/couches, 12 publication, 3 terminal/plans, 13 fenêtre/sessions |
| Notebooks autonomes | **16 réussis, 106 cellules**, 49.93 s cumulées, un noyau neuf par cours |
| Paquet installé hors des sources | **20 contrôles réussis**, environnement neuf sans site-packages hérités ; `pip check` réussi |
| Identité de la wheel | **93 modules Python** identiques aux sources testées |
| Données réelles et cas analytiques | **14 contrôles réussis**, aucun échec, **5,908 s** |

Les deux exclusions de la suite locale concernent le matériel CUDA et le
moteur QGIS natif indisponibles dans cet environnement. QGIS possède son
contrôle séparé sur GitHub. Deux cours supplémentaires demandent les données
locales de `Tuto.zip` et ne sont pas inclus dans les 16 cours autonomes.
Les contrôles Windows/Ubuntu et les résultats du moteur QGIS sont associés
au commit testé dans [GitHub Actions](https://github.com/cedrick14/cartomize-python/actions).

Le [rapport de livraison](VALIDATION_1.8.0.json) enregistre les empreintes des
sources et tests, les sorties des contrôles et l'identité du paquet installé.
Les fichiers applicatifs et tests n'ont pas changé pendant la suite finale.

## Référence sur données réelles

Le [rapport G01](VALIDATION_G01_REAL.json) traite **50 aires protégées de RDC**
et **80 quartiers parisiens** provenant d'instantanés historiques épinglés.
Il conserve les neuf empreintes des fichiers d'entrée, restés intacts.

Itombwe est l'unique géométrie invalide des 50 aires protégées. La réparation
à pas nul produit 50 géométries valides et conserve exactement le WKB des
49 objets initialement valides. Les grilles de 0,01 m et 1 m sont des
scénarios de vérification, avec leurs changements de coordonnées et de
surface documentés ; elles ne constituent pas une recommandation de précision.
Les vrais IDs, attributs et géométries des 80 quartiers sont conservés après
permutation de leur ordre d'entrée.

Les résultats enregistrés sont vérifiés par SQLite et lecture des WKB,
complétés par des surfaces analytiques et des coordonnées attendues.
Le validateur distingue ces oracles de la validité GEOS, qui reste évaluée
par le moteur de réparation lui-même.

## Cours, inventaire et livraison

Le [cours 17](../tutorials/notebooks/17_g01_controle_reparation_geometries.ipynb)
guide les neuf cellules du parcours G01 : choix de couche, audit, réparation,
grille, comparaison et publication. Il est inclus dans le catalogue, la
matrice pédagogique et l'archive source.

Le registre reste à **50 opérateurs**. Les **123 procédures** et **88 références**
de l'inventaire sont conservées : **16 disponibles, 45 partielles, 62 absentes**.
Ce complément ne crée pas de module M11 et ne change pas ces comptes : G01
était déjà classée disponible. Les preuves M08, M09, M10 et leurs cours
historiques sont conservés. La version 1.8.0 du dépôt et du paquet validé ne
constitue pas une publication sur PyPI.
