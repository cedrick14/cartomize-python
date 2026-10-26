# M08 — Qualité des données vectorielles

Ce module réalise les procédures **G01** (diagnostic et réparation des
géométries), **G02** (contrôle topologique) et **G03** (traitement des doublons).
Les mêmes fonctions sont disponibles dans Python et Jupyter, le terminal,
les chaînes de traitements et la rubrique **Traitements vectoriels** de la
fenêtre Cartomize.

Le [cours 14](../tutorials/notebooks/14_qualite_vectorielle.ipynb) présente un
parcours autonome sur des données simulées : diagnostic, réparation,
dédoublonnage, contrôle topologique et comparaison des résultats avec des
surfaces connues.

## Choisir le contrôle adapté

| Besoin | Fonction Python | Opérateur commun | Résultat principal enregistré |
|---|---|---|---|
| Localiser les géométries manquantes, vides, invalides, non finies ou exactement dupliquées | `cm.audit_geometries` | `vector.audit_geometries` | Couche des anomalies ; la couche source est aussi conservée dans le produit `data`. |
| Réparer les géométries invalides avec des décisions explicites | `cm.repair_geometries` | `vector.repair_geometries` | Couche réparée et retenue. |
| Chercher les chevauchements, lacunes et problèmes de raccordement | `cm.check_topology` | `vector.check_topology` | Couche des violations des règles demandées. |
| Retirer les enregistrements répétés selon des critères définis | `cm.deduplicate` | `vector.deduplicate` | Enregistrements conservés. |

La validité d'un polygone décrit sa géométrie individuelle. Deux polygones
valides peuvent néanmoins se chevaucher ou laisser une lacune. De même, une
géométrie identique peut représenter deux observations légitimes à des dates
différentes : les critères du dédoublonnage doivent correspondre à l'étude.

## Résultats, identifiants et fichiers

Chaque appel Python retourne un objet `VectorQualityResult` :

| Attribut | Contenu |
|---|---|
| `data` | Couche principale en mémoire ; pour l'audit, il s'agit de la source inchangée. |
| `report` | Table détaillée des observations ou décisions. |
| `summary` | Paramètres, effectifs, conventions et résultats globaux. |
| `issues` | Couche de localisation des anomalies lorsqu'elle s'applique. |
| `rejected` | Enregistrements écartés, conservés avec leur géométrie d'origine lorsqu'ils existent. |

`source_row` désigne la **position de la ligne dans l'entrée de l'opération,
à partir de zéro**. Ce champ reste utilisable lorsque l'index pandas contient
des valeurs répétées. Il n'est pas un identifiant permanent entre deux fichiers
réordonnés. Fournir `id_field="identifiant"` pour suivre un identifiant métier,
unique et renseigné. Les rapports d'audit, réparation et topologie le nomment
`feature_id`; le rapport de dédoublonnage utilise `source_id` et `retained_id`.
Les grands entiers sont conservés sans conversion en nombres flottants.

Les appels directs retournent des objets en mémoire. Pour produire tous les
fichiers ensemble, utiliser `execute_operation`, le terminal, une chaîne ou la
fenêtre. Chaque exécution crée **un nouveau dossier** :

| Produit | Fichier habituel | Usage |
|---|---|---|
| `data` | `data.gpkg` | Couche principale de la procédure. |
| `issues` | `issues.gpkg` | Anomalies localisables ; pour la topologie, ce produit référence directement `data.gpkg`. |
| `rejected` | `rejected.gpkg` | Objets écartés ; couche vide lorsqu'aucun objet n'a été écarté. |
| `report` | `report.csv` | Rapport détaillé, UTF-8 avec marqueur d'encodage, sans index supplémentaire. |
| `summary` | `summary.json` | Résumé des règles, unités et effectifs. |
| — | `operation.json` | Opérateur, résultat principal et chemins de tous les produits. |

Utiliser les chemins du dictionnaire `products` plutôt que supposer que tous
les fichiers portent un nom distinct. Un contrôle sans anomalie produit une
couche vide et un résumé avec zéro violation. Les fichiers ne sont rendus
disponibles ensemble qu'après réussite ; une erreur ou une annulation ne
publie pas un dossier partiellement calculé. Le dossier existant et les
fichiers sources sont protégés contre l'écrasement.

Les attributs des données retenues proviennent des enregistrements sources.
Les colonnes de diagnostic sont séparées pour ne pas écraser un champ métier.
Les types géométriques exacts avant et après réparation figurent dans le
rapport : `Polygon`, `MultiPolygon`, `GeometryCollection`, etc. Dans un tableur,
importer les identifiants longs ou comportant des zéros initiaux comme texte ;
le format CSV ne porte pas de schéma de types.

## G01 — Diagnostic et réparation

```python
import cartomize as cm

audit = cm.audit_geometries(
    "donnees/parcelles.gpkg",
    id_field="identifiant",
    metric_crs="EPSG:32733",  # Choisir le SCR projeté adapté à l'étude.
)
print(audit.summary)
print(audit.report[["source_row", "feature_id", "status", "reason"]])

reparation = cm.repair_geometries(
    "donnees/parcelles.gpkg",
    id_field="identifiant",
    method="linework",
    missing="drop",
    empty="error",
    type_changes="allow",
    keep_collapsed=True,
    metric_crs="EPSG:32733",
)
print(reparation.report[[
    "feature_id", "decision", "retained",
    "before_geometry_type", "after_geometry_type",
    "before_area_m2", "after_area_m2", "area_delta_m2",
]])
```

Le diagnostic parcourt toutes les entités. Le motif de validité provient de
GEOS. Son signalement de doublons compare le WKB exact, donc aussi l'ordre des
coordonnées ; il ne supprime aucun enregistrement. Utiliser G03 pour choisir
une autre définition du doublon et une règle de conservation.

### Règles de réparation

| Paramètre | Choix et effet |
|---|---|
| `method="linework"` | Réparation à partir des arêtes et sommets d'origine ; méthode par défaut. |
| `method="structure"` | Reconstruction à partir des contours extérieurs et des trous déclarés ; exige Shapely ≥ 2.1 et GEOS ≥ 3.10. |
| `missing`, `empty` | `keep` : conserver et signaler ; `drop` : écarter dans `rejected` ; `error` : arrêter. |
| `type_changes` | `allow` : accepter et signaler ; `drop` : écarter ; `error` : arrêter. Un passage de Polygon à MultiPolygon est un changement de type. |
| `keep_collapsed` | Conserver les composantes réduites à une ligne ou un point. Toujours vrai avec `linework` ; désactivable avec `structure`. |

Les règles `missing` et `empty` valent `keep` par défaut. La politique des
géométries vides s'applique aussi à un résultat devenu vide après réparation.
Une collection ou une composante de dimension inférieure est conservée lorsque
les règles l'autorisent ; aucune extraction implicite des seules parties
polygonales n'est effectuée. Les coordonnées non finies provoquent un arrêt.
Les entités déjà valides passent sans modification. Les principes des deux
méthodes et leurs effets sur les collections sont décrits dans la
[documentation Shapely de `make_valid`](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html).

Les surfaces et longueurs sont exprimées en m² et en mètres dans le SCR de
mesure déclaré, avec conversion des unités projetées en pieds. Si la source
est géographique et qu'aucun `metric_crs` n'est fourni, l'audit et la réparation
restent possibles, mais leurs mesures physiques sont manquantes et ce choix
est inscrit au résumé. L'aire d'un polygone invalide avant réparation ne
constitue pas une surface validée : son écart après réparation décrit l'effet
de l'opération, sans prouver une perte ou un gain territorial.

## G02 — Topologie polygonale et linéaire

```python
controle = cm.check_topology(
    reparation.data,
    id_field="identifiant",
    rules=["duplicates", "overlaps", "gaps", "outside"],
    reference="donnees/emprise_attendue.gpkg",
    allowed_gaps="donnees/trous_legitimes.gpkg",
    min_area=1.0,
    metric_crs="EPSG:32733",
)
print(controle.summary["counts"])
print(controle.report[["rule", "feature_id", "feature_id_other", "area_m2"]])
```

Les entrées doivent avoir des géométries valides, présentes, non vides et
finies. Une couche mêlant polygones et lignes doit être contrôlée par famille.
Un SCR projeté ou `metric_crs` explicite est requis. Les géométries des
violations reviennent dans le SCR source ; les mesures restent dans les
unités physiques indiquées au rapport.

| Règle | Famille | Définition |
|---|---|---|
| `duplicates` | Polygones, lignes | Même ensemble de points XY ; l'ordre des sommets ne compte pas. |
| `overlaps` | Polygones | Partie de surface commune à chaque paire ; un simple contact de frontière est admis. |
| `gaps` | Polygones | Emprise de référence sans couverture, après retrait des trous légitimes. |
| `outside` | Polygones | Partie de chaque entité située hors de l'emprise de référence. |
| `overlaps` | Lignes | Longueur commune à deux parties ou segments ; un contact ponctuel seul est admis. |
| `dangles` | Lignes | Extrémité ouverte sans autre partie de ligne à la distance de raccordement choisie. |
| `crossings` | Lignes | Intersection ponctuelle sans sommet sur au moins une des lignes participantes. |

Sans référence, les règles polygonales par défaut sont `duplicates` et
`overlaps`. Avec une référence, elles incluent aussi `gaps` et `outside`.
Les quatre règles linéaires sont sélectionnées par défaut. Les règles peuvent
être données explicitement pour suivre le protocole de l'étude.

`gaps` et `outside` exigent une référence. Un espace entre polygones n'est pas
automatiquement une lacune : il faut connaître le territoire attendu. Les trous
de la référence sont hors de son domaine. `allowed_gaps` retire explicitement
les secteurs où une absence de couverture est légitime. `min_area` conserve
les anomalies de surface **strictement supérieures** au seuil en m² ; il ne
supprime jamais le signalement d'une géométrie dupliquée.

Pour les lignes, `tolerance` est en mètres et s'applique **uniquement à
`dangles`**. Elle ne déplace aucun sommet et ne modifie aucune autre règle :

```python
reseau = cm.check_topology(
    "donnees/routes.gpkg",
    rules=["overlaps", "dangles", "crossings"],
    tolerance=0.5,
    metric_crs="EPSG:32733",
)
```

Une jonction en T est raccordée pour le contrôle des extrémités. Si la ligne
traversante ne comporte pas de sommet à cette intersection, `crossings` la
signale comme non nœudée. Les multiparties, auto-croisements et retracements
linéaires sont inspectés. Les boucles fermées n'ont pas d'extrémité pendante.
Une impasse peut être légitime : la règle aide à la localiser et son
interprétation dépend du réseau, comme le précise le
[vérificateur topologique QGIS](https://docs.qgis.org/3.44/en/docs/user_manual/plugins/core_plugins/plugins_topology_checker.html).

Les chevauchements sont rapportés **par paire**. Dans une zone commune à trois
polygones, la somme des chevauchements peut compter plusieurs fois une même
surface. Elle ne remplace pas la surface d'une union géométrique. Les candidats
sont recherchés avec un [index spatial STRtree](https://shapely.readthedocs.io/en/maint-2.0/strtree.html).

## G03 — Définir et traiter les doublons

```python
unique = cm.deduplicate(
    reparation.data,
    keys=["parcelle"],
    geometry="topological",
    keep="last",
    order_by=["date_releve"],
    ascending=True,
    null_keys="distinct",
    id_field="identifiant",
)
print(unique.report[[
    "source_row", "source_id", "group_id", "group_size",
    "retained", "retained_id", "reason",
]])
```

Au moins un critère est obligatoire : champ(s) dans `keys`, ou comparaison
géométrique. Lorsque les deux sont présents, **les attributs et la géométrie
doivent correspondre**. Pour conserver des observations de dates distinctes,
inclure la date dans `keys`; pour choisir la plus récente dans un groupe,
utiliser la date comme champ de tri plutôt que comme clé de comparaison.

| Paramètre | Choix |
|---|---|
| `geometry` | `none` : attributs seuls ; `exact` : WKB identique, ordre des coordonnées et Z/M compris ; `topological` : égalité XY indépendamment de l'ordre des sommets et des sommets colinéaires redondants. |
| `keep` | `first` ou `last` : conserver un enregistrement entier ; `none` : écarter tous les membres des groupes ayant plusieurs lignes. |
| `order_by` | Champ ou liste de champs définissant le premier/dernier enregistrement ; sans tri, ordre des lignes sources. |
| `ascending` | Ordre croissant par défaut ; le même sens est appliqué à tous les champs de tri. |
| `null_keys` | `distinct` par défaut : chaque clé manquante est distincte ; `match` : rapprocher les mêmes combinaisons de valeurs manquantes ; `error` : arrêter. |

Les ex æquo sont départagés par la position source. Les valeurs de tri
manquantes sont toujours placées à la fin : avec `keep="last"`, elles peuvent
donc être retenues. Pour choisir la dernière date renseignée, contrôler ou
traiter les dates manquantes au préalable. Les règles usuelles premier/dernier
et le traitement des valeurs de tri manquantes sont décrits par pandas
([doublons](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.duplicated.html),
[tri](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.sort_values.html)).

Les géométries absentes ou vides restent distinctes lorsqu'une comparaison
géométrique est demandée. La comparaison topologique exige des géométries
valides et finies ; ses résultats portent sur XY, sans distinguer les altitudes.
L'[égalité topologique Shapely](https://shapely.readthedocs.io/en/stable/reference/shapely.Polygon.html)
diffère de l'identité des coordonnées.

Aucune agrégation de mesures n'est effectuée. La ligne conservée reste un
enregistrement source complet. Les sorties retenues et écartées gardent l'ordre
source, même si un tri a servi à choisir la ligne représentative. `group_id`
commence à un ; `retained_row` et `retained_id` sont manquants lorsqu'un groupe
entier est supprimé par `keep="none"`.

## Enregistrer les produits depuis Python ou le terminal

```python
produits = cm.execute_operation(
    "vector.repair_geometries",
    {
        "data": "donnees/parcelles.gpkg",
        "id_field": "identifiant",
        "method": "linework",
        "missing": "drop",
        "empty": "error",
        "type_changes": "allow",
    },
    "resultats/reparation_01",
)
print(produits["primary"])
print(produits["products"]["report"])
```

Le terminal reçoit les mêmes paramètres dans un fichier JSON. Exemple
`reparation.json` :

```json
{
  "data": "donnees/parcelles.gpkg",
  "id_field": "identifiant",
  "method": "linework",
  "missing": "drop",
  "empty": "error",
  "type_changes": "allow"
}
```

```bash
cartomize process vector.repair_geometries reparation.json resultats/reparation_01
```

## Chaîne diagnostic → réparation → dédoublonnage → topologie

```python
plan = cm.processing_plan([
    dict(id="audit", operation="vector.audit_geometries",
         parameters=dict(data="donnees/parcelles.gpkg", id_field="identifiant")),
    dict(id="reparation", operation="vector.repair_geometries",
         parameters=dict(data="@audit:data", id_field="identifiant",
                         missing="drop", empty="error", type_changes="allow")),
    dict(id="uniques", operation="vector.deduplicate",
         parameters=dict(data="@reparation:data", id_field="identifiant",
                         keys=["parcelle"], geometry="topological",
                         keep="last", order_by=["date_releve"])),
    dict(id="topologie", operation="vector.check_topology",
         parameters=dict(data="@uniques:data", id_field="identifiant",
                         rules=["duplicates", "overlaps", "gaps", "outside"],
                         reference="donnees/emprise_attendue.gpkg",
                         metric_crs="EPSG:32733")),
])
manifest = cm.run_plan(plan, "resultats/chaine_qualite_01")
print(manifest)
```

`@audit:data` transmet la couche entière à la réparation. `@audit` désigne le
résultat principal de l'audit, donc sa couche d'anomalies : ce serait un autre
choix analytique. Chaque étape conserve ses propres rapports ; les lignes
écartées restent consultables dans `@reparation:rejected` et `@uniques:rejected`.

## Utilisation dans la fenêtre

Dans **Traitements vectoriels**, sélectionner la source, puis l'une des
opérations suivantes :

1. **Diagnostic détaillé des géométries** : choisir l'identifiant et, si
   nécessaire, le SCR projeté servant aux mesures.
2. **Réparation avec rapport des changements** : choisir la méthode, le sort
   des géométries manquantes/vides et les changements de type autorisés.
3. **Contrôle topologique** : cocher les règles adaptées aux polygones ou aux
   lignes ; renseigner l'emprise, les trous légitimes et les seuils concernés.
4. **Traitement des doublons** : renseigner les champs de comparaison et de
   tri séparés par des virgules, puis la règle de conservation et le sort des
   clés manquantes.

Choisir un **répertoire parent** et un **nouveau nom de dossier de résultats**,
puis lancer le traitement. Le résultat expose les couches et leurs rapports.
Dans **Chaîne de traitements**, ces mêmes opérations permettent de réutiliser
les produits nommés d'une étape précédente. Les sources restent inchangées ;
les décisions de réparation et de dédoublonnage sont inscrites dans les
rapports.

Les clés booléennes restent distinctes des nombres : `True` ne correspond pas à `1`, et `False` ne correspond pas à `0`. Les valeurs numériques équivalentes `1` et `1.0` peuvent appartenir au même groupe ; le texte `"1"` reste distinct. Cette convention est inscrite dans la synthèse du dédoublonnage.
