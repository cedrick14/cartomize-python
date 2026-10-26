# Cartomize 1.7.0 — Harmonisation et fusion de couches

Le module **M10** termine la procédure **G05** de l’inventaire. Il associe
les champs de plusieurs couches à un schéma commun, convertit leurs valeurs
selon des règles explicites, puis concatène les enregistrements avec leur
provenance dans une nouvelle couche.

## Changements

- **Inspection des schémas :** champs, types, valeurs nulles, correspondances,
  proposition de schéma commun et conflits à résoudre. Les collisions de noms
  telles que `Name`/`name` et un attribut métier `geometry` restent inspectables
  pour être remappés.
- **Correspondances par source :** renommage, suppression volontaire et refus
  des collisions ; un champ non mentionné conserve son nom.
- **Schéma cible explicite :** texte, entier signé 64 bits, nombre flottant,
  booléen, date, date/heure naïve ou date/heure UTC, avec nullabilité et valeur
  par défaut facultative.
- **Conversions contrôlées :** refus par défaut des valeurs incompatibles ;
  remplacement par une valeur nulle seulement sur demande et avec journal.
  Champs absents, champs non retenus et valeurs nulles ont des règles distinctes.
- **Préservation des attributs :** lecture Arrow, écriture typée avec masques
  de valeurs nulles et relecture des données enregistrées. Les entiers ne
  passent pas implicitement par un flottant ; les dates/heures ne sont pas
  arrondies silencieusement à la milliseconde.
- **Compatibilité SQL :** la lecture utilise le schéma effectif du résultat
  de la requête, afin qu’une expression entière remplaçant une colonne de date
  reste entière ; les options `bbox`, `mask` et `rows` restent prises en charge.
- **Champs entièrement nuls :** un champ `object` sans type déclaré peut adopter
  le type concret d’une autre source ; un champ réellement déclaré `TEXT`
  conserve cette information et reste texte.
- **Provenance de chaque ligne :** identifiant, nom, chemin, couche source et
  position d’origine à partir de zéro. Les noms de colonnes restent distincts
  des champs métier.
- **Produits :** `merged.gpkg`, `fields.csv`, `issues.csv` et `manifest.json`,
  publiés ensemble dans un nouveau dossier après les contrôles de fidélité.
- **Interfaces :** API, commandes d’inspection et de fusion, opérateur
  `vector.merge_layers`, formulaire graphique et produits nommés dans les plans.
- **Cours 16 :** huit cellules autonomes sur deux relevés villageois simulés,
  contrôle SQLite indépendant, conversion refusée ou acceptée explicitement,
  provenance et chaîne de tampons.

La fusion conserve les géométries et les répétitions d’enregistrements. Elle
ne réalise ni union géométrique, ni dissolution, ni déduplication. Sans cible
de reprojection explicite, toutes les sources doivent avoir le même SCR.
Une cible demandée réutilise M09 avec ses règles géodésiques et son manifeste.
Le [guide M10](VECTOR_MERGE.md) précise les types, politiques et limites.

## Validation locale de la livraison

La suite complète réussit **1 074 tests**, avec **2 exclusions prévues et
aucun échec**, en **197,43 s** sous Linux / Python 3.12.14. Les exclusions
concernent le matériel CUDA indisponible et le moteur QGIS natif, couvert
séparément sur GitHub. Les **134 nouvelles régressions** comprennent 84 cas
du moteur, 10 cas terminal/plans/tableaux, 26 cas de fenêtre et 14 cas de
compatibilité de lecture, dont les requêtes SQL.

Les **15 notebooks autonomes exécutent 97 cellules** dans des noyaux neufs,
en **47,85 s cumulées**. La wheel est installée dans un environnement neuf,
hors du dépôt, et réussit ses **17 contrôles** API/fenêtre/console. Ses
**93 modules Python** sont identiques aux sources validées ; `pip check` et
le contrôle strict Twine réussissent. Les sources et les tests sont figés
pendant la suite complète finale, après la correction du lecteur SQL.
Le [rapport de livraison](VALIDATION_1.7.0.json) conserve les empreintes
et la provenance de ces résultats locaux.

## Vérification sur données réelles

Le [rapport M10](VALIDATION_M10_REAL.json) enregistre la réexécution sur les
sources arrêtées pour l’intégration : **12 contrôles réussis, 0 échec, 2,535 s**,
le 26 octobre 2026 à **20 h 40 UTC**. Les empreintes des deux fichiers épinglés
et des **93 modules Python** restent inchangées pendant cette exécution et
correspondent encore aux sources à la fin de la vérification. Le rapport
conserve aussi l’empreinte du script. Le commit de base `4fbd322` précède M10 ;
les empreintes de la copie de travail identifient donc le code réellement testé.

Les jeux proviennent des instantanés historiques du tutoriel GeoPandas. Le
[script reproductible](../scripts/validate_vector_merge_real.py) crée des
variantes temporaires de schéma pour exercer les renommages, nombres textuels
et champs absents. Ces variantes sont identifiées comme telles ; les fichiers
épinglés d’origine sont conservés et ne sont pas redistribués.

| Contrôle | Résultat observé |
|---|---|
| Visites minières de RDC | **3 687 enregistrements** conservés, avec leurs cinq attributs cibles et cinq valeurs de provenance |
| Effectifs miniers | **658 valeurs nulles et 44 zéros** conservés ; les valeurs renseignées restent des entiers |
| Géométries des visites | **3 687 points** relus directement depuis le binaire GeoPackage, coordonnées exactement identiques |
| Quartiers parisiens | **80 polygones, 8 366 couples de coordonnées** et tous les attributs retenus conservés |
| Répétitions intentionnelles de quartiers | **160 enregistrements** après réunion de deux copies distinctes de 80 polygones ; aucun regroupement géométrique |
| Conversion invalide insérée dans une copie | Mode strict refusé sans publication ; mode `null` accepté avec la valeur exacte consignée et 659 effectifs manquants |
| Champ absent | Politique `error` refusée sans publication ; valeur par défaut explicite appliquée à 1 843 enregistrements |

La référence est construite avec le lecteur JSON standard et des listes de
valeurs Python. La sortie est contrôlée avec SQLite pour les valeurs et leurs
types, et un lecteur `struct` du format
[GeoPackage/WKB documenté par l’OGC](https://www.geopackage.org/spec140/#gpb_format)
pour les points et polygones. La comparaison ne réutilise ni la concaténation
Cartomize, ni `pandas.concat`, ni GDAL/GEOS comme référence des coordonnées.

La somme des effectifs renseignés vaut **552 559 sur les visites**. Les visites
concernent 2 403 sites distincts et plusieurs années : ce total ne représente
pas un effectif territorial unique ou contemporain. La somme de l’attribut
population des quartiers parisiens vaut **2 125 851** dans cet instantané.
Ces sommes servent à détecter une perte ou une duplication d’enregistrement,
sans actualiser les données de terrain.

## Livraison et parcours

Le [rapport de livraison 1.7.0](VALIDATION_1.7.0.json) regroupe la suite complète,
le parcours réexécuté et le paquet installé. Les contrôles Windows/Ubuntu et
QGIS sont associés au commit testé dans
[GitHub Actions](https://github.com/cedrick14/cartomize-python/actions).
Les preuves des modules M08 et M09 restent attachées à leurs versions respectives.

Le registre comprend **50 opérateurs**. Le parcours compte **15 notebooks
autonomes, soit 97 cellules de code**, et deux cas supplémentaires demandant
les données locales de `Tuto.zip`. Le nouveau
[cours 16](../tutorials/notebooks/16_harmonisation_fusion_vectorielle.ipynb)
est inclus dans le catalogue et la matrice pédagogique. Son exécution locale
dans un noyau Jupyter neuf réussit : **8 cellules, aucune erreur, 3,14 s**,
y compris la chaîne de fusion puis tampons. Les sorties numériques et la
figure sont enregistrées dans le notebook.

## Inventaire et suite

Les **123 procédures** et les **88 références** sont conservées. G05 passe
d’absent à disponible dans son périmètre explicite : le bilan devient
**16 disponibles, 45 partielles et 62 absentes**. Le bloc E01 reste en cours.
La prochaine procédure est **G06 — Conversion et conditionnement des données**,
actuellement partielle.

## Installation et reproduction

Depuis la copie des sources GitHub :

```bash
python -m pip install -e ".[gui]"
python -m cartomize gui
python -m pip install -r tutorials/requirements.txt
python tutorials/scripts/execute.py --select 16
python scripts/validate_vector_merge_real.py --data .m10-cache --output reports/m10-real.json
```

La lecture fiable des types utilise PyArrow, inclus dans les dépendances du
paquet. Le script réel télécharge les deux fichiers épinglés si le cache est
absent et vérifie leurs empreintes avant les essais. La publication sur PyPI
reste une étape distincte de la construction et de la vérification de cette version.
