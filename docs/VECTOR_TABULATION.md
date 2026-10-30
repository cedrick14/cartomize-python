# G09 — Croisement de zonages et occupation du sol

Le module M13 fournit une table croisée des surfaces entre des **zones polygonales**
et des **catégories polygonales**. Une même fonction alimente l’API Python,
la commande `tabulate-area`, les plans, le cours 20 et la page Vecteur.

Une zone ou une catégorie peut comprendre plusieurs polygones non contigus.
Les objets portant une même identité sont réunis avant le calcul : un doublon
de polygone ne double pas la superficie d’une catégorie. Les recouvrements
entre catégories différentes font l’objet d’une règle explicite.

## Contrat de calcul

```python
result = cm.tabulate_area(
    zones, classes,
    zone_field="territoire",
    class_field="occupation",
    zones_layer=None,
    classes_layer=None,
    metric_crs=None,
    area_unit="ha",
    overlap_policy="error",
    zone_overlap_policy="independent",
    null_classes="error",
)
```

Les entrées sont des GeoDataFrame, ou des chemins vers des couches vectorielles.
Chaque fichier multicouche exige son nom de couche explicite. Les noms de
champs et de couches restent des chaînes, même lorsqu’ils ressemblent à des
nombres. Les sources et leurs attributs ne sont jamais modifiés.

### Géométries et projection

- Chaque entrée doit avoir un SCR connu et contenir des Polygon/MultiPolygon
  valides, non vides, de surface positive, avec des coordonnées finies.
  Un diagnostic ou une réparation G01 précède le calcul si nécessaire.
- Une couche sans enregistrement est acceptée lorsqu’elle possède son schéma
  et son SCR. Des classes absentes donnent des zones entièrement non couvertes.
- Le calcul est **planaire**. `metric_crs` choisit une projection adaptée à
  l’étude. À défaut, le SCR des zones doit déjà être projeté. Une projection
  équivalente convient lorsque la conservation des surfaces est prioritaire.
- Les deux sources sont transformées dans ce SCR d’analyse. Les unités
  projetées, y compris les pieds, sont converties en mètres avant conversion
  vers `m2`, `ha` ou `km2`.
- Toutes les **géométries de sortie** utilisent ce SCR d’analyse. Les Z/M
  sont explicitement retirés des copies de calcul ; les surfaces sont en XY.
  Le bilan consigne les dimensions présentes dans les sources.
- Aucun arrondi de coordonnées, grille de précision, seuil de suppression
  des petites surfaces ou réparation implicite n’est appliqué. Les contacts
  uniquement ponctuels ou linéaires ont une surface nulle et ne produisent
  pas de polygone d’intersection.

### Identités des zones et catégories

Le champ `zone_field` définit les groupes de zones ; `class_field` définit les
groupes de catégories. L’ordre de première apparition fixe les identifiants
stables de l’exécution : `z000001`, `z000002`, puis `c000001`, `c000002`…

Une identité comprend son **type et sa valeur**. Le texte `"1"`, l’entier `1`
et le booléen `True` restent distincts. Les libellés `001`, `NA`, les chaînes
vides et les grands entiers conservent leur valeur exacte. Les décimaux sont
normalisés sans arrondi, indépendamment de la précision du contexte Decimal.
Les horodatages avec fuseau sont regroupés par instant UTC ; les dates et les
horodatages sans fuseau gardent des types distincts.

Les colonnes `zone_type`/`zone_value` et `class_type`/`class_value` rendent ces
identités transportables : la valeur est un texte canonique, accompagné de son
type. Cela permet de représenter ensemble des codes textuels, des entiers
non signés et des dates sans conversion implicite par GeoPackage, CSV ou JSON.
Les registres du bilan relient chaque identité aux positions sources, à partir
de zéro. Les catégories pandas sans aucune ligne source ne créent pas de classe.

Les identités de zones manquantes sont refusées. Pour les catégories :

| `null_classes` | Comportement |
|---|---|
| `error` — défaut | Refuse une catégorie manquante et indique la ligne concernée. |
| `unclassified` | Écarte ces objets de la couverture classée et mesure leur emprise dans les lacunes. |

Une emprise portant une catégorie connue reste classée même si elle recoupe
un objet sans catégorie. Les lacunes distinguent `unclassified` — couvert par
un objet sans catégorie, hors couverture connue — et `no_coverage`.

### Recouvrements et double comptage

Les géométries d’une même catégorie ou d’une même zone sont dissoutes avant
mesure. Leurs surfaces brutes, leur surface réunie et l’excès ainsi retiré
restent consultables. Les recouvrements entre catégories sont contrôlés
**dans la réunion des zones** : des recouvrements extérieurs au territoire
d’analyse ne bloquent pas le calcul.

| Paramètre | Valeur | Effet |
|---|---|---|
| `overlap_policy` | `error` — défaut | Refuse toute intersection de surface positive entre catégories différentes. |
| `overlap_policy` | `report` | Mesure chaque catégorie et cartographie les recouvrements ; les sommes peuvent dépasser 100 %. |
| `zone_overlap_policy` | `independent` — défaut | Calcule chaque zone indépendamment ; le bilan distingue la réunion du territoire et la somme des zones. |
| `zone_overlap_policy` | `error` | Refuse toute intersection de surface positive entre groupes de zones différents. |

Aucune catégorie ne reçoit de priorité automatique. Le mode `report` n’affecte
pas arbitrairement une zone ambiguë à la première classe rencontrée.

## Table et bilans de surface

La table contient **toutes les combinaisons zone × catégorie**, y compris les
surfaces nulles. `area` est la surface de l’intersection. `percentage` vaut
`100 × area / zone_area` : le dénominateur est toute la zone, y compris ses
surfaces non couvertes. La matrice utilise les mêmes surfaces ; ses colonnes
`c000001`… renvoient au registre des catégories, ce qui évite les collisions
entre libellés de types différents.

| Champ du bilan de zone | Sens |
|---|---|
| `source_area` | Somme des surfaces des polygones sources du groupe, avant dissolution. |
| `zone_area` | Surface de leur réunion. |
| `same_zone_excess_area` | Excès retiré par la dissolution du groupe de zones. |
| `covered_area` | Surface couverte par au moins une catégorie connue, comptée une fois. |
| `uncovered_area` | Surface hors de cette couverture, avec ventilation en `unclassified_area` et `no_coverage_area`. |
| `overlap_area` | Emprise couverte par au moins deux catégories différentes, comptée une fois. |
| `summed_class_area` | Somme des surfaces attribuées aux catégories. |
| `excess_area` | Excès de cette somme par rapport à la couverture unique. |
| `closure_error` | Différence signée `zone_area - covered_area - uncovered_area`. |

`overlap_area` et `excess_area` sont différents en présence de recouvrements
triples : une surface couverte trois fois représente une seule emprise de
recouvrement et deux unités de surface excédentaire. Les champs de pourcentage
correspondants utilisent toujours la surface complète de la zone.

Les diagnostics entre catégories ou zones sont enregistrés par paire ; leurs
surfaces ne doivent pas être additionnées pour obtenir une emprise unique.
Les bilans calculent cette emprise par réunion. Au sein d’un même groupe,
le diagnostic représente une emprise de recouvrement réunie.

Les totaux `summary["totals"]["domain"]` portent sur la réunion des zones.
`summary["totals"]["zone_sums"]` additionne les bilans par zone et expose
`zone_excess_area` lorsque des zones se recouvrent. Ces deux totaux ne sont
donc pas interchangeables.

La fermeture arithmétique utilise une tolérance documentée de
`1e-6 m² + 1e-8 × surface de référence en m²`. Elle ne supprime aucun petit
polygone et n’autorise pas un recouvrement en mode `error`. Les résidus signés
sont conservés. Un excès légèrement négatif dans cette tolérance est ramené
à zéro dans le champ non négatif, avec sa valeur brute dans `raw_*` ; une
incohérence au-delà de la tolérance est refusée.

La couverture d’une zone est construite par réunion des intersections utilisées
dans ses cellules. Ce choix garde un ordre de calcul cohérent entre table et
bilan, car des opérations d’intersection et de réunion mathématiquement
équivalentes peuvent produire de petits écarts en arithmétique flottante.

## Résultat Python et fichiers publiés

`AreaTabulationResult` contient huit objets. Les GeoDataFrame sont des résultats
géométriques dérivés ; les registres et tables portent les identités et mesures.

| Attribut / produit | Objet Python | Fichier |
|---|---|---|
| `data` — produit principal | GeoDataFrame des intersections de surface positive | `data.gpkg` |
| `table` | DataFrame détaillé, y compris les cellules nulles | `table.csv` |
| `matrix` | DataFrame, une ligne par zone et une colonne par catégorie | `matrix.csv` |
| `zones` | GeoDataFrame des zones dissoutes et de leurs bilans | `zones.gpkg` |
| `categories` | DataFrame du registre et des surfaces par catégorie | `categories.csv` |
| `gaps` | GeoDataFrame des surfaces non classées ou non couvertes | `gaps.gpkg` |
| `overlaps` | GeoDataFrame des recouvrements entre catégories/zones et au sein des groupes | `overlaps.gpkg` |
| `summary` | Dictionnaire des paramètres, registres, règles, unités et totaux | `summary.json` |

Chaque GeoPackage utilise la couche `features`. Chaque CSV possède un fichier
`*.csv.schema.json` qui protège les types et les libellés. La publication ajoute
`audit.json`, avec les tables sans géométrie, les contrôles et empreintes des
produits, ainsi que `operation.json`, le manifeste habituel de traitement.

Les quatre GeoPackage sont relus et vérifiés intégralement. Les trois CSV sont
relus avec conversion des flottants permettant un aller-retour exact, puis
comparés aux valeurs calculées. Un échec de vérification annule la publication
entière. Une destination existante ou contenant une source est refusée.
L’annulation conserve les sources et ne laisse pas de dossier de résultat partiel.

```python
import cartomize as cm

parameters = dict(
    zones="territoires.gpkg", zones_layer="territoires", zone_field="code",
    classes="occupation.gpkg", classes_layer="occupation", class_field="classe",
    metric_crs="EPSG:32733", area_unit="ha",
    overlap_policy="error",
)
# Choisir un SCR réellement adapté au territoire étudié.
result = cm.tabulate_area(**parameters)
display(result.table)
display(result.matrix)
display(result.zones.drop(columns="geometry"))

published = cm.execute_operation("vector.tabulate_area", parameters, "sortie_neuve")
print(published["products"]["matrix"])
```

`progress(done, total)` et `cancel` sont disponibles sur l’API et l’opérateur.
Le total de progression est 10000 ; l’opérateur réserve la dernière partie à
la vérification et à l’écriture des produits.

## Terminal et plans

```bash
cartomize tabulate-area territoires.gpkg occupation.gpkg sortie_neuve \
  --zones-layer territoires --classes-layer occupation \
  --zone-field code --class-field classe \
  --metric-crs EPSG:32733 --area-unit ha
```

Le même dictionnaire de paramètres est accepté par
`cartomize process vector.tabulate_area parametres.json sortie_neuve`.
Les options `--overlap-policy report`, `--zone-overlap-policy error` et
`--null-classes unclassified` expriment les choix correspondants.

```python
plan = cm.processing_plan([
    dict(id="surfaces", operation="vector.tabulate_area", parameters=parameters),
    dict(id="lacunes", operation="vector.area",
         parameters=dict(source="@surfaces:gaps", unit="ha")),
])
manifest = cm.run_plan(plan, "plan_neuf")
```

Les produits nommés `@surfaces:data`, `@surfaces:zones`, `@surfaces:gaps`,
`@surfaces:overlaps`, `@surfaces:table`, `@surfaces:matrix` et
`@surfaces:categories` restent accessibles aux étapes compatibles.

## Interface et cours

Dans **Vecteur → Table croisée des surfaces**, choisir la source de zones,
sa couche et son champ, puis la source d’occupation du sol, sa couche et son
champ. Le formulaire expose la projection, l’unité et les règles de recouvrement
et de catégories manquantes. Choisir un nouveau dossier de résultat et lancer
le traitement. Les boutons ouvrent les intersections, tables, bilans, lacunes,
recouvrements et synthèse. Les choix sont conservés dans les sessions et les
projets portables.

Le [cours 20](../tutorials/notebooks/20_table_croisee_surfaces.ipynb) utilise
des données explicitement simulées, avec des surfaces calculables à la main,
des doublons, des lacunes et un recouvrement triple. Il vérifie les interfaces,
la publication, les plans et l’annulation.

## Données réelles, portée et références

Le validateur `scripts/validate_vector_tabulation_real.py` utilise les quartiers
de Paris et les catégories originales d’un jeu public d’occupation du sol
épinglé par empreinte. Il compare aussi les quartiers réels à des bandes
rectangulaires analytiques : une référence Python indépendante calcule leurs
intersections par découpage de polygones et leurs surfaces par la formule du
lacet, y compris les trous et polygones multiples.

La comparaison avec l’occupation du sol réelle partage GEOS pour ses
intersections. Les transformations de coordonnées partagent PROJ. Les bandes
analytiques ne représentent aucune catégorie réelle du territoire. Les jeux
publics historiques ne décrivent pas l’occupation du sol actuelle.

G09 couvre la tabulation des **surfaces polygonales**. Le choix scientifique de
la projection, la signification des catégories et la résolution d’une ambiguïté
entre classes restent explicites. La table et la matrice sont denses : leur
taille dépend du nombre de groupes de zones multiplié par celui des catégories.

Références fonctionnelles :

- [ArcGIS Pro — Tabulate Intersection](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/analysis/tabulate-intersection.html) : groupes de zones/classes, surfaces et pourcentages.
- [QGIS 3.44 — Vector overlay](https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/vectoroverlay.html) : intersections et différences vectorielles.

Ces références situent la procédure ; les règles exactes de dissolution,
recouvrement, conservation des identités et publication sont celles décrites ici.
