# Reprojection vectorielle par lot — M09 / G04

Le module découvre les couches d’un fichier ou d’un dossier, examine les
opérations géodésiques disponibles, puis transforme le lot vers un SCR cible
explicite. Il écrit un GeoPackage par couche, un bilan CSV et un manifeste JSON.
Le lot est publié dans un nouveau dossier après la réussite de toutes les couches.

Les fonctions Python, l’opérateur `vector.reproject_batch`, les plans et la fenêtre
utilisent le même moteur. Le [cours 15](../tutorials/notebooks/15_reprojection_vectorielle_par_lot.ipynb)
exécute le parcours sur des données simulées aux SCR différents.

## Découvrir les couches

```python
import cartomize as cm

couches = cm.discover_vector_layers("donnees/vecteurs", recursive=True)
for couche in couches:
    print(couche["id"], couche["layer"], couche["features"], couche["source_crs"])
```

`sources` accepte un fichier, un dossier, une liste de sources, des objets
GeoDataFrame/GeoSeries ou des descripteurs explicites. Un GeoPackage peut fournir
plusieurs couches. Le parcours d’un dossier reconnaît les fichiers `.gpkg`,
`.shp`, `.geojson`, `.fgb`, `.gml`, `.kml` et `.sqlite`, selon les pilotes installés.
`recursive=False` limite la recherche au dossier fourni ; `True` parcourt aussi
ses sous-dossiers.

```python
sources = [
    {"path": "territoire.gpkg", "layer": "routes"},
    "localites.geojson",
    {"data": releves, "name": "releves_terrain"},  # GeoDataFrame déjà chargé.
]
```

Chaque descripteur retourné contient `id`, `name`, `path`, `layer`, `source_crs`,
`features` et `bounds`. Le nom de fichier et celui de la couche participent à
l’identifiant stable ; deux fichiers portant le même nom dans des dossiers
différents restent distincts. `path` et `layer` valent `None` pour une entrée
en mémoire. Les identifiants doivent être relevés à nouveau après le déplacement
des sources.

Le SCR source doit être déclaré correctement. La découverte ne le devine pas
à partir de l’apparence des coordonnées. Déclarer un SCR et transformer les
coordonnées sont deux opérations distinctes.

## Examiner les opérations disponibles

```python
inspection = cm.inspect_reprojection(sources, "EPSG:32733")
for couche in inspection["layers"]:
    catalogue = couche["catalogue"]
    print(couche["name"], catalogue["best_available"])
    for operation in catalogue["operations"]:
        print(operation["id"], operation["description"], operation["accuracy"])
```

Cette inspection ne produit pas de couche. Elle complète les métadonnées par
les bornes géographiques utilisées pour classer les opérations et par un
`catalogue` contenant :

| Champ | Contenu |
|---|---|
| `operations` | Opérations disponibles, chacune avec un identifiant fondé sur sa définition |
| `best_available` | Disponibilité de la meilleure opération déterminée par PROJ pour les critères fournis |
| `unavailable_operations` | Opérations indisponibles et leurs grilles associées |
| `warnings` | Messages de PROJ conservés pour l’examen |

Chaque opération décrit sa définition PROJ, sa précision annoncée, son domaine
d’utilisation, ses étapes et ses grilles. `accuracy=None` représente une
précision non renseignée ; ce n’est pas une précision de zéro mètre. Le champ
`ballpark` identifie une transformation géodésique approximative.

`area_of_interest=(ouest, sud, est, nord)` est une emprise en degrés géographiques
utilisée pour le classement. Sans ce paramètre, le moteur utilise les bornes
géographiques de chaque couche. La zone d’intérêt ne découpe pas les objets.
Le classement et le contrôle des domaines utilisent le référentiel géodésique
de la source rapporté au méridien de Greenwich ; ils ne constituent pas une
transformation supplémentaire du datum ni une preuve de couverture d’une grille.

## Exécuter le lot

```python
resultat = cm.reproject_batch(
    sources,
    "resultats/reprojection_01",
    "EPSG:32733",
)
print(resultat.manifest)
print(resultat.report)
for identifiant, fichier in resultat.layers.items():
    print(identifiant, fichier)
```

Le résultat `ReprojectedBatch` donne accès au manifeste, au CSV, au dictionnaire
des couches enregistrées et à leur synthèse complète dans `summary`.

| Paramètre | Valeur par défaut | Règle appliquée |
|---|---|---|
| `recursive` | `False` | Recherche dans les sous-dossiers seulement sur demande |
| `operations` | `None` | Choix automatique, ou dictionnaire `identifiant_couche: identifiant_operation` |
| `area_of_interest` | `None` | Classement suivant les bornes géographiques de chaque couche |
| `accuracy` | `None` | Aucun seuil supplémentaire ; une valeur strictement positive demande un filtre de précision PROJ en mètres |
| `allow_ballpark` | `False` | Refus des transformations approximatives |
| `require_best` | `True` | Refus lorsque la meilleure opération exige une ressource indisponible |
| `area_policy` | `"error"` | Refus des sommets hors du domaine connu du SCR source, du SCR cible ou de l’opération retenue |

Le moteur ne modifie pas la configuration réseau de PROJ. Le manifeste conserve
son état, les versions de bibliothèques et les informations sur les grilles.
Une précision annoncée par PROJ caractérise l’opération géodésique ; elle ne
mesure pas l’exactitude des relevés d’entrée.

### Fixer une opération

Après examen du catalogue, construire une sélection à partir de ses identifiants :

```python
choix = {}
for couche in inspection["layers"]:
    candidates = couche["catalogue"]["operations"]
    if not candidates:
        raise ValueError(f"Aucune opération disponible pour {couche['name']}")
    # Exemple : retenir explicitement la première candidate examinée.
    choix[couche["id"]] = candidates[0]["id"]

resultat = cm.reproject_batch(
    sources, "resultats/reprojection_choisie", "EPSG:32733", operations=choix,
)
```

Un identifiant inconnu ou devenu indisponible est refusé. Aucune autre opération
ne lui est substituée silencieusement. `require_best=False` permet de travailler
explicitement avec les alternatives disponibles ; `allow_ballpark=True` autorise
séparément les approximations. `area_policy="warn"` conserve les dépassements
dans le rapport au lieu de bloquer la production. Ces décisions restent inscrites
dans les paramètres et avertissements du manifeste.

## Conservation des données et emprises

Le module conserve les enregistrements, leur ordre, leurs attributs, les géométries
manquantes et vides. Il transforme les coordonnées avec l’ordre SIG **x, y** :
longitude/latitude pour les entrées géographiques. Les valeurs non finies sont
refusées avant et après transformation.

Les sorties GeoPackage sont relues avant publication. Le nombre d’entités, le SCR,
les valeurs attributaires et les géométries exactes sont vérifiés. Un champ métier nommé `fid` est
conservé grâce à un identifiant technique distinct. Si un attribut ne peut pas
être préservé par le pilote de sortie, le lot est refusé au lieu de publier une
valeur modifiée.

Un mélange de géométries XY et XYZ dans des entités distinctes est conservé.
Si le pilote normalise une même collection en inventant des valeurs Z pour ses
composantes XY, la comparaison des géométries relues refuse cette écriture.

Les géométries invalides ne sont pas réparées par une reprojection. Le manifeste
dénombre les invalidités avant et après ; le [module M08](VECTOR_QUALITY.md) permet
d’effectuer une réparation préalable avec ses propres règles et son rapport.

`bounds` et `target_bounds` représentent les bornes des sommets réels dans les
SCR respectifs. Les géométries ne sont pas densifiées géodésiquement et leurs
segments ne sont pas découpés automatiquement à l’antiméridien. Une géométrie
traversant cette limite doit être préparée explicitement avant la transformation.

Le périmètre porte sur les SCR horizontaux statiques à deux axes. Des géométries
XYZ peuvent être traitées : **Z est conservé sans transformation verticale**.
Les mesures M, les SCR dynamiques nécessitant une époque, les SCR géocentriques,
verticaux, composés et les SCR à trois axes relèvent d’un protocole distinct.

## Produits enregistrés

Le dossier contient un GeoPackage par identifiant, `report.csv` et `manifest.json`.
Le manifeste suit le schéma `cartomize.vector_reprojection.v1`.

| Élément | Informations conservées |
|---|---|
| Lot | SCR cible et WKT, paramètres, nombre de couches et d’entités, environnement |
| Couche | Source, nom, identifiant, SCR source et WKT, effectif, emprises avant/après, fichier de sortie |
| Transformation | Identifiant, définition, description, précision annoncée, grilles et domaine |
| Décision | Sélection automatique ou explicite, meilleure opération disponible, avertissements |
| Géométries | Nombres de géométries manquantes, vides, invalides avant/après et avec Z |

La publication est atomique à l’échelle du nouveau dossier. Le dossier final
doit être absent avant le lancement ; les sources ne sont jamais écrasées.
`progress` et `cancel` permettent à la fenêtre de suivre et d’interrompre
l’exécution entre les opérations contrôlées.

## Terminal et plans

Dans `parametres.json` :

```json
{
  "sources": "donnees/vecteurs",
  "target_crs": "EPSG:32733",
  "recursive": true
}
```

```bash
cartomize process vector.reproject_batch parametres.json resultats/reprojection_01
```

Dans un plan, chaque couche est un produit nommé du lot. Son identifiant est
obtenu avec `discover_vector_layers` :

```python
identifiant = cm.discover_vector_layers(
    {"path": "territoire.gpkg", "layer": "sites"}
)[0]["id"]
plan = cm.processing_plan([
    {"id": "lot", "operation": "vector.reproject_batch",
     "parameters": {"sources": "territoire.gpkg", "target_crs": "EPSG:32733"}},
    {"id": "tampons", "operation": "vector.buffer",
     "parameters": {"data": f"@lot:{identifiant}", "distance": 100}},
])
cm.run_plan(plan, "resultats/chaine_01")
```

Les étapes suivantes utilisent explicitement `@lot:identifiant_couche` pour
sélectionner leur entrée. Le [guide des plans](PROCESSING.md) décrit les
dépendances et les autres produits secondaires.

## Vérification reproductible

Le [cours 15](../tutorials/notebooks/15_reprojection_vectorielle_par_lot.ipynb)
contrôle des coordonnées simulées avec les équations Web Mercator, un point
numérique publié, une sélection explicite et un plan avec produits nommés.
Le script [validate_vector_reprojection_real.py](../scripts/validate_vector_reprojection_real.py)
utilise les trois instantanés réels déjà épinglés pour M08 : quartiers parisiens,
visites minières et aires protégées de RDC.

```bash
python scripts/validate_vector_reprojection_real.py --data .m09-cache --output reports/m09-real.json
```

Les références numériques indépendantes sont les équations NumPy de Web Mercator
pour tous les sommets WGS 84 et les exemples chiffrés publiés. La comparaison du
Mercator RDC utilise un appel PROJ distinct mais partage son moteur ; le rapport
l’identifie comme une vérification d’intégration. Voir les résultats effectivement
obtenus dans [la validation M09](VALIDATION_M09_REAL.json) et la
[note 1.6.0](RELEASE_1.6.0.md).

## Références

- [PROJ : Web Mercator, équations et exemple numérique](https://proj.org/en/stable/operations/projections/webmerc.html).
- [PROJ : UTM, exemples nord et sud](https://proj.org/en/stable/operations/projections/utm.html).
- [pyproj : groupes de transformations et grilles indisponibles](https://pyproj4.github.io/pyproj/stable/advanced_examples.html#transformation-group).
- [QGIS : opérations vectorielles générales](https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/vectorgeneral.html).
- [ArcGIS Pro : Project](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/project.html).
