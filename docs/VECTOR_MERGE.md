# Harmonisation et fusion de couches — M10 / G05

L’harmonisation associe les champs de plusieurs sources à un schéma de sortie
commun. La fusion concatène ensuite les enregistrements dans une nouvelle
couche, avec leur provenance. Les choix de conversion et de valeurs manquantes
font partie du traitement : ils doivent pouvoir être examinés et reproduits.

Une fusion attributaire conserve les géométries des enregistrements, y compris
leurs recouvrements. Elle ne dissout pas les polygones et ne dédoublonne pas les
visites d’un même site. La procédure de référence est
[Merge d’Esri, R016](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/merge.html).
Les fonctions de [qualité vectorielle](VECTOR_QUALITY.md) et de
[reprojection](VECTOR_REPROJECTION.md) couvrent les préparations distinctes
qui peuvent être nécessaires avant de réunir des sources.

## Définir le schéma de l’étude

Deux équipes peuvent décrire les mêmes objets avec des noms et des types
différents. Définir d’abord le sens, le type et les règles de chaque champ cible.

| Champ cible | Relevé A | Relevé B | Décision de l’étude |
|---|---|---|---|
| `code` | `code` | `village_id` | Texte, afin de conserver les zéros initiaux |
| `nom` | `nom` | `village_name` | Texte Unicode |
| `habitants` | `habitants` numérique | `population` textuel | Entier ; absence admise mais jamais remplacée implicitement par zéro |
| `note` | Champ absent | `commentaire` | Texte facultatif |

Les noms de champs ne suffisent pas à garantir la compatibilité : vérifier les
unités, les dates, les nomenclatures et le sens des valeurs. Par exemple, la
concaténation de plusieurs visites ne donne pas automatiquement un recensement
de sites uniques. Un total d’effectifs répétés dans le temps doit rester
identifié comme la somme de ces enregistrements.

## Inspecter les sources

```python
from pathlib import Path
import cartomize as cm

sources = ["releve_A.gpkg", "releve_B.gpkg"]
inspection = cm.inspect_merge(sources)
for couche in inspection["layers"]:
    print(couche["id"], couche["name"], couche["features"])
    for champ in couche["fields"]:
        print(champ["name"], champ["type"], champ["null_count"], champ["target"])
```

Les sources peuvent être des fichiers, dossiers, listes, objets en mémoire ou
descripteurs de couches. Un descripteur `{"path": "donnees.gpkg", "layer": "villages"}`
limite la lecture à une couche ; un GeoPackage sans sélection peut en fournir
plusieurs. `recursive=True` inclut les sous-dossiers. L’inspection ne publie
aucun résultat et ne transforme pas les coordonnées.

L’inspection lit les champs complets, et la fusion charge les couches et leurs
attributs en mémoire. Dimensionner les lots selon la mémoire disponible ; ce
module ne réalise pas une fusion en flux de fichiers dépassant cette capacité.

Une même paire fichier/couche fournie plusieurs fois est découverte une seule
fois. Les tables sans géométrie ne constituent pas des couches de ce module.

Chaque couche est identifiée avec son chemin, son nom, son SCR, son effectif et
ses champs. Les champs décrivent le type de stockage `dtype`, le type logique
`type`, la présence de valeurs nulles, leur nombre et la cible après correspondance.
`common_crs` indique le SCR commun lorsqu’il existe ; `suggested_schema` propose
les champs cibles et `conflicts` signale les choix restant à résoudre.

L’inspection reste possible lorsque des noms tels que `Name` et `name` entrent
en conflit. Elle expose les deux champs et indique le problème dans `conflicts`
pour permettre leur remappage. La fusion exige ensuite des noms cibles valides
et uniques. Une collision à résoudre ne rend donc pas les sources inaccessibles
au diagnostic.

L’identifiant d’une source sert de clé aux correspondances. Le relever à nouveau
après un déplacement de fichier ou un changement de sélection de couche.

## Associer les champs et choisir les types

```python
par_fichier = {Path(couche["path"]).name: couche for couche in inspection["layers"]}
correspondances = {
    par_fichier["releve_A.gpkg"]["id"]: {},
    par_fichier["releve_B.gpkg"]["id"]: {
        "village_id": "code",
        "village_name": "nom",
        "population": "habitants",
        "commentaire": "note",
    },
}
schema = {
    "code": {"type": "string", "nullable": False},
    "nom": {"type": "string", "nullable": False},
    "habitants": "int64",
    "note": {"type": "string", "nullable": False, "default": "Non renseigné"},
}
inspection = cm.inspect_merge(sources, field_maps=correspondances)
print(inspection["conflicts"])
```

`field_maps` associe **identifiant de source → champ source → champ cible**.
Les champs non mentionnés gardent leur nom. Une cible `None` supprime
explicitement le champ. Deux champs d’une même source ne peuvent pas alimenter
la même cible : cette ambiguïté est refusée.
Les noms cibles doivent aussi rester uniques sans distinction de casse et
distincts du champ de géométrie réservé.

Un attribut métier nommé `geometry`, distinct de la géométrie active de la
couche, reste lisible et apparaît dans l’inspection. Le nom cible `geometry`
est réservé : le remapper, par exemple avec
`{"geometry": "geom_label"}`, conserve ses valeurs dans un champ métier valide.
Cela fonctionne aussi pour un fichier dont la colonne géométrique porte un
autre nom. Dans une même source possédant `Name` et `name`, choisir deux cibles
distinctes ou supprimer explicitement l’un des champs avec `None`.

Le schéma associe chaque champ cible à un type, ou à un objet contenant `type`,
`nullable` et éventuellement `default`. `nullable` vaut `True` par défaut.
L’ordre des champs suit celui du schéma explicite. Sans schéma, le moteur
réunit les champs de types compatibles ; un conflit exige une décision
explicite plutôt qu’une conversion devinée.

Un champ `object` en mémoire entièrement vide ou nul, sans type déclaré,
est signalé par `untyped_null=True`. Il peut adopter le type concret du champ
correspondant dans une autre source. Si tous les champs correspondants sont
ainsi dépourvus de type, la proposition utilise `string`.

Un champ réellement déclaré `TEXT` conserve au contraire cette information,
même si toutes ses cellules sont `NULL`. Son type reste `string` ; son association
à un champ numérique demande un schéma explicite. Les valeurs manquantes ne
suppriment pas le type connu du fichier.

| Type | Usage et convention |
|---|---|
| `string` | Texte Unicode ; les identifiants textuels conservent leurs zéros initiaux |
| `int64` | Entier signé sur 64 bits, sans arrondi d’une valeur fractionnaire, avec valeurs nulles lorsque le schéma l’autorise |
| `float64` | Nombre fini à virgule flottante ; une perte de précision d’un entier converti est refusée |
| `boolean` | Booléen, `true`/`false` ou `1`/`0` ; les autres textes ne sont pas interprétés implicitement |
| `date` | Date ISO `YYYY-MM-DD`, sans suppression silencieuse d’une heure ou d’un fuseau |
| `datetime` | Date et heure sans fuseau ; aucune zone n’est devinée |
| `datetime_utc` | Date et heure avec fuseau, normalisée en UTC |

Les dates et heures enregistrées ont une précision maximale à la milliseconde ;
les valeurs plus fines doivent être normalisées explicitement et ne sont pas
arrondies silencieusement.
Une valeur incompatible avec le type choisi suit la politique de conversion.
Les valeurs manquantes ne sont pas transformées implicitement en texte `"nan"`,
en zéro ou en valeur logique fausse.

## Fusionner et examiner les produits

```python
resultat = cm.merge_layers(
    sources,
    "resultats/villages_fusionnes",
    schema=schema,
    field_maps=correspondances,
)
couche = cm.vector.read_file(resultat.data)
print(resultat.manifest, resultat.report, resultat.issues)
print(resultat.summary["feature_count"])
```

`MergedVectors` expose les chemins `data`, `manifest`, `report`, `issues` et
le manifeste complet dans `summary`. La couche `features` se trouve dans
`merged.gpkg`. Le dossier final doit être nouveau ; le moteur relit les données
écrites et publie le dossier entier après réussite des contrôles.

| Paramètre | Valeur par défaut | Décision |
|---|---|---|
| `schema` | `None` | Union des champs compatibles ; schéma explicite pour fixer noms, types, ordre et obligations |
| `field_maps` | `None` | Correspondance par nom identique |
| `conversion_errors` | `"error"` | Une conversion invalide refuse la fusion ; `"null"` l’enregistre et crée une valeur nulle |
| `missing_fields` | `"null"` | Un champ cible absent d’une source reçoit une valeur nulle ; `"error"` refuse cette absence |
| `extra_fields` | `"error"` | Avec un schéma explicite, un champ non retenu doit être supprimé explicitement ; `"drop"` autorise ces suppressions |
| `recursive` | `False` | Recherche dans les sous-dossiers seulement sur demande |
| `target_crs` | `None` | Les sources doivent déjà partager le même SCR |
| `reprojection_options` | `None` | Paramètres M09 lorsque la reprojection est demandée explicitement |

Une valeur `default` comble les valeurs nulles du champ, qu’elles proviennent
d’une cellule vide ou d’un champ absent. Une chaîne vide reste distincte d’une
valeur nulle. `nullable=False` refuse les absences restantes après application
de la valeur par défaut. Accepter les conversions vers une absence ne dispense
donc pas de respecter le schéma final.

Utiliser `cm.vector.read_file` pour relire les entiers avec valeurs nulles sans
passage intermédiaire par un nombre flottant. La lecture Arrow et l’écriture
de tableaux typés avec leurs masques de valeurs nulles assurent cette
préservation des types et des grands identifiants.

## Provenance, géométries et SCR

Chaque ligne conserve cinq informations de provenance. Le manifeste donne les
noms effectifs de leurs colonnes dans `provenance_columns`, car ils sont choisis
pour rester distincts des champs métier.

| Clé logique | Information |
|---|---|
| `source_id` | Identifiant de la couche source |
| `source_name` | Nom de la source |
| `source_path` | Chemin du fichier, absent pour une source en mémoire |
| `source_layer` | Couche dans le fichier, absente pour une source en mémoire |
| `source_row` | Position de l’enregistrement dans sa source, à partir de zéro |

Le manifeste suit le schéma `cartomize.vector_merge.v1` et conserve le schéma
attributaire, les correspondances, politiques, effectifs, sources et décisions.
`fields.csv` décrit, par source et champ, les conversions, valeurs manquantes,
valeurs par défaut, erreurs et valeurs nulles finales. `issues.csv` identifie
les conversions invalides acceptées : source, position de ligne, champs source
et cible, valeur, motif et décision. Le contenu exact des entrées n’est pas
remplacé par une simple somme globale : la provenance relie chaque sortie à
son enregistrement d’origine.

Les géométries restent associées à leurs lignes, avec leurs recouvrements et
répétitions. La lecture reprend le périmètre M09 : SCR horizontaux statiques
à deux axes, valeurs Z conservées et mesures M refusées. Une normalisation
de type, de dimension ou de coordonnées par le pilote de sortie n’est pas
publiée silencieusement. Les invalidités géométriques ne sont pas réparées
par l’harmonisation attributaire.

Pour des SCR différents, préparer les sources avec M09 ou demander explicitement
un `target_crs`. La reprojection réutilise le moteur M09 et ses règles de
sélection géodésique ; les transformations sont conservées dans le manifeste.
Elle ne modifie pas les choix de correspondance ni les règles attributaires.
Voir les [limites horizontales et les contrôles de domaine](VECTOR_REPROJECTION.md).

## Terminal, plans et fenêtre

Le terminal propose une inspection et une exécution dédiées :

```bash
cartomize merge-options releve_A.gpkg releve_B.gpkg --field-maps correspondances.json
cartomize merge-layers resultats/villages_fusionnes releve_A.gpkg releve_B.gpkg --schema schema.json --field-maps correspondances.json
```

Les options `--on-conversion-error`, `--missing-fields` et `--extra-fields`
portent les mêmes politiques que Python. `--crs`, `--reprojection-options`
et `--recursive` complètent les paramètres lorsque nécessaire.

L’opérateur `vector.merge_layers` utilise aussi les paramètres JSON communs :

```python
plan = cm.processing_plan([
    {"id": "fusion", "operation": "vector.merge_layers",
     "parameters": {"sources": sources, "schema": schema,
                    "field_maps": correspondances}},
    {"id": "tampons", "operation": "vector.buffer",
     "parameters": {"data": "@fusion:data", "distance": 100}},
])
cm.run_plan(plan, "resultats/chaine_fusion")
```

Le plan expose `data` comme produit principal, ainsi que `manifest`, `report`
et `issues`. La distance de tampon doit être interprétée dans les unités du
SCR de travail. La fenêtre utilise les mêmes sources, schémas et politiques ;
elle permet d’examiner la correspondance avant d’exécuter le lot.

## Références et vérification

Les contrôles M10 s’appuient sur les instantanés historiques du tutoriel
GeoPandas déjà épinglés pour les modules précédents. Les schémas différents
utilisés dans l’essai sont des variantes dérivées, explicitement construites
pour exercer les correspondances et conversions. Les fichiers d’origine restent
inchangés et ne sont pas redistribués.

La référence attributaire est calculée avec la lecture JSON standard et des
listes/dictionnaires Python. Les valeurs enregistrées sont relues directement
dans le GeoPackage avec SQLite. Cette comparaison vérifie les entiers, textes,
valeurs nulles, ordre des lignes et provenance sans reprendre la concaténation
de Cartomize comme résultat attendu. Le contrôle des géométries compare leur
représentation WKB après lecture de l’en-tête GeoPackage documenté par l’OGC.

Le [cours 16](../tutorials/notebooks/16_harmonisation_fusion_vectorielle.ipynb)
exécute le cas des villages simulés, y compris le refus d’une conversion et
son acceptation explicite vers une valeur nulle. Le
[script reproductible](../scripts/validate_vector_merge_real.py) utilise les
visites minières et quartiers parisiens épinglés :

```bash
python scripts/validate_vector_merge_real.py --data .m10-cache --output reports/m10-real.json
```

Le [rapport M10](VALIDATION_M10_REAL.json) conserve uniquement les résultats
effectivement observés et les empreintes de leurs sources.

- [Esri : Merge et correspondances des champs](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/merge.html).
- [SQLite : classes de stockage et types](https://www.sqlite.org/datatype3.html).
- [Python : interface sqlite3](https://docs.python.org/3/library/sqlite3.html).
- [OGC : GeoPackage 1.4, encodage des géométries](https://www.geopackage.org/spec140/#gpb_format).
