# G01 — Contrôler et réparer les géométries

**Contrat complété dans Cartomize 1.8.0.** G01 reçoit une couche vectorielle,
identifie les anomalies, applique une règle de réparation explicite et conserve
la comparaison avec la source complète. Le complément de la version 1.8.0
précise la sélection des couches, le pas de grille XY, les dimensions et la
fidélité des fichiers publiés. Il complète le parcours G01 initialement
intégré dans M08.

Le [cours 17](../tutorials/notebooks/17_g01_controle_reparation_geometries.ipynb)
est autonome et utilise des géométries simulées à surfaces connues. Le
[guide M08](VECTOR_QUALITY.md) conserve le contexte de G02 et G03. Le
[validateur G01](../scripts/validate_g01_real.py) traite séparément les données
réelles épinglées ; le rapport [VALIDATION_G01_REAL.json](VALIDATION_G01_REAL.json)
porte l'identité des sources et les résultats effectivement observés.

## 1. Choisir la couche et l'identifiant

```python
import cartomize as cm

audit = cm.audit_geometries(
    "donnees/inventaire.gpkg",
    layer="parcelles",
    id_field="parcelle_id",
    metric_crs="EPSG:32733",  # Uniquement si ce SCR convient au territoire.
)
print(audit.report[["source_row", "feature_id", "status", "reason"]])
```

`data` accepte un chemin vectoriel ou un GeoDataFrame. `layer` sélectionne
explicitement la couche d'un fichier ; un fichier contenant plusieurs couches
est refusé si aucun choix n'est donné. Un fichier monocouche peut être utilisé
avec `layer=None`. Un GeoDataFrame représente déjà une couche : il n'a pas de
sélection de couche à résoudre. Le résumé conserve `source_layer`.

`id_field` désigne un attribut unique, renseigné et scalaire. Les zéros initiaux
d'un identifiant textuel et les grands entiers sont conservés. Le résultat
n'ajoute pas d'identifiant technique aux attributs métier. Sans `id_field`,
`feature_id` reprend `source_row`, une position à partir de zéro qui dépend de
l'ordre d'entrée ; cette position n'est pas un identifiant permanent entre
deux extractions réordonnées.

## 2. Diagnostiquer les données originales

L'audit ne modifie aucune géométrie. Pour chaque entité, il décrit la validité
planaire GEOS, le motif, les géométries manquantes ou vides, les coordonnées non
finies et les doublons WKB exacts. Un doublon exact tient compte de l'ordre des
sommets et composantes ; son signalement n'entraîne aucune suppression.

Le rapport ajoute les dimensions observées : `has_z`, `has_m`,
`coordinate_dimension`, `topological_dimension`, `coordinate_count`,
`part_count` et `wkb_sha256`. L'empreinte WKB permet de distinguer une géométrie
strictement inchangée d'un résultat réordonné ou autrement modifié. Elle ne
prouve pas à elle seule une égalité topologique ou une qualité métier.

Une géométrie vide et une géométrie manquante restent deux états distincts.
Le motif GEOS est un diagnostic du moteur, pas l'énumération exhaustive de
toutes les erreurs possibles d'une entité. La validité GEOS concerne XY ; la
présence de Z ne signifie pas qu'une surface ou un réseau a été validé en 3D.

## 3. Retenir une règle de réparation

```python
resultat = cm.repair_geometries(
    "donnees/inventaire.gpkg",
    layer="parcelles",
    id_field="parcelle_id",
    method="linework",
    tolerance=0.0,
    missing="error",
    empty="drop",
    type_changes="allow",
    keep_collapsed=True,
)
```

| Paramètre | Règle |
|---|---|
| `method="linework"` | Méthode par défaut : reconstruction à partir des arêtes et sommets de la géométrie invalide. |
| `method="structure"` | Reconstruction à partir des contours extérieurs et des trous déclarés ; exige Shapely ≥ 2.1 et GEOS ≥ 3.10. |
| `missing`, `empty` | `keep` conserve et signale ; `drop` écarte ; `error` interrompt. Les deux valent `keep` par défaut. |
| `type_changes` | `allow` accepte et signale ; `drop` écarte ; `error` interrompt. La valeur par défaut est `allow`. Polygon → MultiPolygon compte comme changement. |
| `keep_collapsed` | Concerne la réparation GEOS : toujours vrai avec `linework`, désactivable avec `structure`. Il ne protège pas les composantes supprimées par la grille. |
| `tolerance` | Pas facultatif de grille XY, zéro par défaut ; voir les unités et l'ordre des opérations ci-dessous. |
| `metric_crs` | SCR projeté réservé au calcul des mesures physiques ; il ne définit pas la grille ni une reprojection de la couche. |

Une géométrie déjà valide et une tolérance nulle donnent une géométrie
inchangée. Les attributs restent ceux de l'enregistrement source. Une
réparation qui produit une collection ou une composante de dimension
inférieure reste visible dans le rapport ; aucune extraction implicite des
seules surfaces polygonales n'est effectuée.

Les coordonnées non finies sont refusées lors de la réparation. Une sortie
non vide encore invalide provoque également un échec explicite.

## 4. Comprendre la tolérance : un pas de grille XY

`tolerance` est un nombre fini, positif ou nul. Sa valeur représente **le pas
de grille dans les unités du SCR source projeté**. Par exemple, `0.01` vaut
un centimètre si la source est en mètres ; il vaut 0,01 pied si elle est en
pieds. Le résumé enregistre `tolerance`, `tolerance_unit` et
`tolerance_metres_per_unit`. La grille est alignée sur les multiples du pas
dans le système de coordonnées source.

Une valeur positive est refusée pour une source géographique, même si
`metric_crs` est renseigné. Pour choisir une grille métrique, préparer d'abord
une couche dans un SCR projeté adapté avec le
[parcours de reprojection G04](VECTOR_REPROJECTION.md), puis traiter cette
nouvelle source. Le choix du SCR et du pas dépend de la précision des données
et de l'objectif de l'étude.

L'ordre du traitement est enregistré dans `processing_steps` :

1. Diagnostiquer la géométrie source, sans la modifier.
2. Appliquer `make_valid` selon `method` seulement si elle est invalide.
3. Si `tolerance > 0`, appliquer `set_precision(..., mode="valid_output")`.
4. Contrôler le résultat, puis appliquer les politiques de vides et de types.

Le résumé contient `precision_mode="valid_output"` lorsque la grille est
activée, et `null` sinon. La précision intervient par entité : des géométries
devenues identiques restent des enregistrements distincts.

Une grille peut déplacer des sommets, en supprimer, modifier l'ordre des
coordonnées, retirer des portions étroites ou produire une géométrie vide.
Les politiques `empty` et `type_changes` valent aussi après cette étape. Le
pas n'est ni une borne universelle de changement de forme, ni un seuil de
variation de surface acceptable. Deux sommets distants de moins que le pas
peuvent se trouver de part et d'autre d'une frontière de grille.

Cette convention est propre au contrat Cartomize : elle ne reproduit pas le
paramètre entier de précision des contrôles détaillés QGIS. `make_valid`
n'expose pas de paramètre de tolérance ; la réduction de précision est donc
une étape distincte, demandée et enregistrée.

## 5. Comparer toutes les décisions

```python
colonnes = [
    "source_row", "feature_id", "output_row", "rejected_row", "decision",
    "repair_changed", "precision_changed", "geometry_changed",
    "before_geometry_type", "after_geometry_type",
    "before_coordinate_count", "after_coordinate_count",
    "before_area_m2", "after_area_m2", "area_delta_m2",
]
print(resultat.report[colonnes])
```

`repair_changed` indique un changement à l'étape GEOS ; `precision_changed`
un changement entre le résultat de cette étape et celui de la grille.
`geometry_changed` compare l'original et le résultat final. Les colonnes
`before_` et `after_` portent les états, les types, les dimensions, les comptes
et l'empreinte WKB. Les compteurs globaux comprennent
`repair_changed_features` et `precision_changed_features`.

Le rapport contient chaque entité source, y compris celles qui sont écartées.
Une géométrie écartée reste disponible avec ses attributs et sa géométrie
**d'origine** dans `rejected`. Ses valeurs `after_` décrivent le résultat
calculé qui a motivé la décision, lorsqu'un résultat a été calculé.

Les surfaces sont exprimées en m², les longueurs en mètres, avec conversion
des unités projetées. Sans SCR projeté source ou `metric_crs` explicite,
les mesures physiques restent absentes. L'aire d'un polygone invalide avant
réparation est une mesure de la représentation fournie ; ce n'est pas une
surface territoriale validée. Un delta de surface ne prouve donc pas à lui
seul une perte ou un gain de territoire.

## 6. Conserver la correspondance après fermeture de la session

| Élément | Contenu et correspondance |
|---|---|
| `resultat.before` / produit `before` | Source complète, dans l'ordre d'entrée, y compris les entités ensuite écartées. |
| `resultat.data` / produit `data` | Entités retenues, dans l'ordre source. |
| `resultat.rejected` / produit `rejected` | Entités écartées avec leurs géométries d'origine. |
| `source_row` | Position à partir de zéro dans `before`. |
| `output_row` | Position à partir de zéro dans `data` ; valeur absente pour une entité écartée. |
| `rejected_row` | Position à partir de zéro dans `rejected` ; valeur absente pour une entité retenue. |
| `feature_id` | Identifiant explicite, ou position source en l'absence de `id_field`. |

Pour un audit, `output_row` vaut `source_row` puisque la source est conservée.
Ces correspondances sont indépendantes des FID techniques créés par le
format de fichier. Les colonnes métier ne reçoivent pas d'ID injecté par G01.
Dans un tableur, importer les identifiants du CSV comme texte lorsqu'ils sont
longs ou comportent des zéros initiaux ; le CSV ne porte pas de schéma de types.

## 7. Publier les produits par Python, terminal ou plan

```python
record = cm.execute_operation(
    "vector.repair_geometries",
    {"data": "donnees/inventaire.gpkg", "layer": "parcelles",
     "id_field": "parcelle_id", "method": "linework", "tolerance": 0.01,
     "missing": "error", "empty": "drop", "type_changes": "allow"},
    "resultats/g01_essai_01",  # Le dossier doit être nouveau.
)
print(record["products"])
```

Le même dictionnaire peut être enregistré dans `parametres_g01.json` :

```bash
cartomize process vector.repair_geometries parametres_g01.json resultats/g01_essai_02
```

Les plans utilisent les opérateurs `vector.audit_geometries` et
`vector.repair_geometries`. Les références `@reparation:before`,
`@reparation:data`, `@reparation:report`, `@reparation:issues` et
`@reparation:rejected` désignent les produits nommés d'une étape appelée
`reparation`. Utiliser les chemins du dictionnaire `products` pour rouvrir
les fichiers ; ne pas supposer leur nom ou leur FID interne.

Le dossier contient les couches GeoPackage, `report.csv`, `summary.json` et
`operation.json`. Le fichier compagnon `report.csv.schema.json` décrit les
types et les colonnes d'identifiants pour leur réouverture dans le visualiseur.
Les fichiers sont écrits dans un espace temporaire, relus
et contrôlés : nombre d'entités, attributs et WKB de toutes les géométries.
Une représentation que le format ou le lecteur altère est refusée. Le lot
n'est publié qu'après réussite complète. Une erreur, une annulation ou un
dossier déjà existant ne doit pas produire une livraison partielle.

### Dimensions et limites de persistance

Les dimensions et Z sont suivis avant/après. GEOS travaille en XY : une
réparation peut interpoler les Z de nouveaux sommets et ce suivi ne constitue
pas une validation altimétrique. La grille XY n'arrondit pas les Z.

Une géométrie avec M est refusée **avant mutation** si elle est invalide ou
si un pas positif est demandé. Une géométrie valide avec M et un pas nul peut
rester inchangée dans l'API en mémoire. Sa publication GeoPackage par G01 est
explicitement refusée : le parcours ne promet pas une persistance de M qu'il
ne peut garantir. D'autres représentations incompatibles sont également
refusées si le contrôle de relecture détecte une altération.

La lecture fidèle d'un fichier contenant M exige Shapely ≥ 2.1 et GEOS ≥ 3.12.
Avec un moteur plus ancien, les avertissements de pyogrio signalant un type
mesuré sont interceptés et transformés en refus avant la conversion qui
pourrait perdre M. La présence d'une dimension supplémentaire ne doit pas
être interprétée implicitement comme Z.

Un `LinearRing` utilisé comme géométrie autonome, y compris à l'intérieur
d'une collection, est refusé à la publication : sa représentation ne permet
pas de garantir un aller-retour fidèle. Les anneaux structurels d'un polygone
restent des composants ordinaires de ce polygone.

## 8. Parcours dans la fenêtre

Dans **Traitements vectoriels**, choisir **Diagnostic détaillé des géométries**
ou **Réparation avec rapport des changements**. Sélectionner la source, la
couche lorsqu'il y en a plusieurs et l'identifiant à suivre. Pour réparer,
choisir la méthode, les politiques de vides et de types, puis le pas de grille
avec l'unité du SCR source. Zéro conserve la précision originale.

Après exécution, ouvrir le rapport et les anomalies, puis comparer la source
complète et les données retenues. Rechercher une entité par `feature_id` et
utiliser les correspondances de lignes pour consulter une exclusion. Le
rapport est nécessaire même lorsque la carte paraît inchangée : une variation
de type, de dimension ou d'attribut peut être peu visible à l'échelle affichée.

### Rouvrir une session portable

L'enregistrement d'une session portable `.cmz` emporte les produits G01
référencés, leur document d'opération et le fichier compagnon du CSV. À la
restauration, les chemins sont réécrits vers les fichiers extraits ; le choix
de couche, l'identifiant, le pas et les politiques sont restaurés. Les actions
de rapport, d'anomalies et de comparaison utilisent ces produits relocalisés.

`report.csv.schema.json` reste adjacent à `report.csv`. Le visualiseur s'appuie
sur ce schéma pour conserver les identifiants textuels, y compris des codes
comme `0001` ou des chaînes qui ressemblent à une valeur manquante. Copier
manuellement le CSV seul ne transporte pas ce schéma : conserver les deux
fichiers ou préciser les types dans l'outil de lecture.

## 9. Exigences et preuves

| Exigence G01 | API et produit | Parcours fenêtre | Vérification ciblée |
|---|---|---|---|
| Choisir les entrées et IDs stables | `layer`, `id_field`, `source_row` | Couche et identifiant | Fichier multicouche ambigu refusé ; choix explicite ; permutation des vrais IDs de Paris. |
| Contrôler et isoler les erreurs | `audit_geometries`, `issues`, `report` | Diagnostic et accès anomalies | Itombwe et ses 49 témoins initialement valides ; états manquants/vides contrôlés. |
| Retenir une règle de réparation | `method`, `keep_collapsed` | Méthode et composantes effondrées | Réparation de l'auto-intersection ; oracle analytique à surface connue. |
| Préciser la tolérance | `tolerance`, unités et étapes au résumé | Pas de grille et unité source | Scénarios RDC 0, 0,01 et 1 ; coordonnées sur grille ; source géographique refusée. |
| Traiter vides et types | `empty`, `missing`, `type_changes`, `rejected` | Choix explicites | Rectangle effondré, géométrie vide/manquante, Polygon → MultiPolygon. |
| Comparer nombres, types, surfaces et IDs | Champs `before_`/`after_`, `before`, correspondances | Rapport et comparaison | Identités, compteurs, surfaces par formule indépendante et changements par étape. |
| Conserver les changements après export | Produits nommés et contrôle de relecture | Réouverture des produits | Relecture GeoPackage/CSV, attributs et WKB, exclusions et refus atomique. |

Les cas de précision et de règles sont définis dans
[`test_g01_precision.py`](../tests/test_g01_precision.py), la fidélité et les
refus de publication dans
[`test_g01_publication.py`](../tests/test_g01_publication.py), les parcours
terminal/plans dans [`test_g01_interfaces.py`](../tests/test_g01_interfaces.py)
et les contrôles de fenêtre, travail asynchrone et restauration de session
dans [`test_g01_desktop.py`](../tests/test_g01_desktop.py). Leur présence ne
remplace pas les résultats d'exécution : ceux-ci appartiennent aux rapports
de validation de la version.

La preuve réelle G01 reprend deux instantanés pédagogiques historiques du
dépôt GeoPandas, épinglés au commit
`72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0`. Les aires protégées de RDC ne
possèdent pas de champ métier unique retenu pour cette vérification : le
validateur construit explicitement un ID de provenance à partir de l'archive
épinglée et de la ligne source. Paris utilise son véritable champ `id`.

Les pas de 0,01 m et 1 m sont des **scénarios de validation**, pas des
recommandations sur la précision des données. Le contrôle sur grille,
l'arithmétique des surfaces et la lecture SQLite apportent des comparaisons
distinctes de l'orchestration. Les prédicats de validité et les réparations
reposent toujours sur GEOS ; le rapport ne revendique pas une certification
indépendante de ce moteur. Les rapports historiques M08, M09 et M10 restent
des preuves de leurs versions respectives et ne sont pas réécrits.

### Résultats observés du complément G01

La validation du **26 octobre 2026 à 21:29:20 UTC**, sous Cartomize **1.8.0**,
a réussi **14 contrôles, sans échec, en 5,908 s**. Le rapport conserve les
empreintes de **93 modules applicatifs** et de **9 fichiers d'entrée**, restés
inchangés pendant l'exécution. Il distingue le commit de base de l'identité
exacte des sources de travail testées.

Les **50 aires protégées** comportent **148 651 coordonnées** et une anomalie
GEOS, sur la Réserve naturelle d'Itombwe. Les trois scénarios conservent
50 entités valides, avec 44 Polygon et 6 MultiPolygon. À pas nul, les
49 géométries initialement valides gardent exactement leur WKB.

| Pas de grille en mètres | Changements GEOS | Changements à l'étape grille | Coordonnées après | Somme des deltas de surface, m² | Somme des valeurs absolues des deltas, m² |
|---|---|---|---|---|---|
| 0 | 1 | 0 | 148 652 | −0,000003815 | 0,000003815 |
| 0,01 | 1 | 50 | 148 627 | −685,901 | 2 717,144 |
| 1 | 1 | 50 | 148 541 | 145 462,960 | 428 205,861 |

Les valeurs de surface sont arrondies dans ce tableau. Le bilan net peut
masquer des variations opposées entre entités ; la somme des valeurs absolues
montre pourquoi il ne suffit pas à décrire les changements. Ces mesures
planaires, qui incluent une géométrie initialement invalide, ne valident pas
une évolution territoriale et ne justifient aucun de ces pas pour un usage
métier.

Les **80 quartiers de Paris** ont conservé leurs vrais IDs, leurs attributs
et tous leurs WKB après permutation de l'entrée à pas nul. La grille positive
a été refusée sur leur source géographique, y compris avec un SCR de mesure
projeté. La publication RDC et le cas contrôlé d'exclusion ont été relus par
SQLite : toutes les valeurs attributaires et tous les WKB vérifiés coïncident,
les correspondances persistent, les zéros initiaux et un entier métier
supérieur à 2⁵³ restent exacts.

Les surfaces analytiques, l'effondrement d'un rectangle, les unités en pieds,
le Z inchangé par la grille et le refus de M sont des **cas contrôlés
simulés**, distincts des anomalies réelles. Le
[cours 17](../tutorials/notebooks/17_g01_controle_reparation_geometries.ipynb)
a également réussi son exécution isolée : **9 cellules de code, 2,78 s**.

## Références techniques

- [QGIS 3.44 — Check validity et Fix geometries](https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/vectorgeometry.html) : paramètres des opérations et méthodes de réparation.
- [QGIS 3.44 — Check Geometry](https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/checkgeometry.html) : contrôles détaillés, identifiants et convention de précision numérique.
- [Esri — Check Geometry, R013](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/check-geometry.html) : table d'anomalies et méthodes de validation.
- [Shapely — make_valid](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html) : reconstruction et composantes effondrées.
- [Shapely — set_precision](https://shapely.readthedocs.io/en/stable/reference/shapely.set_precision.html) : grille, validité de l'entrée, modes et effets de réduction de précision.
