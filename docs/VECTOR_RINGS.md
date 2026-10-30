# G12 — Zones tampons et anneaux de distance

Cartomize 1.12.0 complète G12 par `cartomize.buffer_rings` et l’opérateur
`vector.buffer_rings`. Une liste de distances produit des anneaux, une table
complète des intervalles, un registre des sources et des bilans de surface.
Python, le terminal, les plans, Jupyter et la page Vecteur utilisent ce moteur.

Le tampon simple `cartomize.buffer` conserve son contrat : une distance en
mètres, éventuellement négative pour l’érosion des polygones, les attributs et
le SCR de la source en sortie. Les anneaux constituent un produit distinct,
mesuré et enregistré dans le **SCR projeté du calcul**.

## Distances et organisation des anneaux

```python
import cartomize as cm

result = cm.buffer_rings(
    "villages.gpkg", [100, 250, 500, 1000],
    layer="villages", metric_crs="EPSG:32733",
    id_field="code", mode="dissolved", area_unit="ha",
)
result.table
result.balances
result.summary["totals"]
```

EPSG:32733 est un exemple de paramètre ; le SCR doit convenir à l’emprise de
l’étude. Le moteur n’effectue pas de choix automatique de projection.

Les distances sont les **bornes supérieures en mètres**, strictement positives,
finies et croissantes. La borne inférieure initiale est zéro. Ainsi
`[100, 250, 500, 1000]` définit 0–100, 100–250, 250–500 et 500–1000 m. Les listes
vides, valeurs booléennes ou textuelles, valeurs nulles, distances négatives,
doublons et listes désordonnées sont refusés. Aucune correction implicite de la
liste n’est appliquée. Deux valeurs distinctes qui se confondent après
conversion numérique sont également refusées.

| Mode | Construction | Sens des recouvrements |
|---|---|---|
| `dissolved`, par défaut | À chaque distance, réunion des tampons de toutes les sources, puis retrait de l’emprise déjà occupée | Un seul groupe ; les anneaux décrivent la proximité de la source la plus proche |
| `independent` | Une série complète par ligne source, dans son ordre d’origine | Anneaux disjoints au sein d’une série ; les séries de sources différentes peuvent se recouvrir |

Dans les deux modes, les limites polygonales peuvent se toucher. Un fichier de
polygones ne représente pas la convention mathématique d’une borne ouverte ou
fermée ; les contrôles de recouvrement portent sur les surfaces intérieures.

Le mode indépendant ne regroupe pas les étiquettes identiques. Deux lignes
portant `001` restent deux sources avec deux identifiants techniques distincts.
Les données peuvent mélanger les familles ponctuelles, linéaires et polygonales
standard ; les géométries multiparties de ces familles sont acceptées.

## Intérieur des polygones

`include_input=False`, par défaut, retire les polygones sources. Le premier
anneau représente alors leur voisinage extérieur jusqu’à la première distance.
`include_input=True` conserve leur surface dans le premier anneau. Les points
et lignes ont une surface propre nulle : ce choix ne modifie pas leur aire.

En mode fusionné, la base retirée est la réunion des polygones sources. En mode
indépendant, chaque série retire uniquement son propre polygone. Un autre
polygone source peut donc se trouver dans une couronne indépendante. Les trous
font partie de l’extérieur du polygone : les tampons se développent aussi dans
les trous, dont l’emprise libre diminue lorsque la distance augmente.

## SCR, géométries et précision

Toutes les sources doivent avoir un SCR connu. Le SCR source doit être projeté,
ou `metric_crs` doit désigner un SCR projeté. Les pieds internationaux et les
pieds US survey sont convertis au moyen du facteur linéaire du SCR. Les
distances restent en mètres et les surfaces utilisent `m2`, `ha` ou `km2`.
Les géométries de `data` et `sources` sont enregistrées dans ce SCR d’analyse.

Les géométries manquantes, vides, invalides ou non finies sont refusées ; les
collections de géométries ne sont pas des entrées prises en charge. Une couche
sans entités reste acceptée si son SCR et son schéma sont connus. Les géométries
sont contrôlées avant et après reprojection. Toutes les coordonnées Z/M présentes
sont vérifiées avant l’analyse XY ; l’abandon de Z/M dans les produits est
explicitement inscrit dans `summary.dimensionality`.

Les extrémités et les angles sont arrondis. `quad_segs`, entier de **1 à 1024**,
fixe le nombre de segments par quart de cercle ; sa valeur par défaut est 16.
La borne supérieure évite une allocation accidentelle de polygones démesurés.
La construction est une approximation polygonale d’une distance euclidienne
plane, sans calcul géodésique ou ellipsoïdal. Elle ne transforme pas un SCR
projeté déformant en une mesure adaptée au terrain.

Pour un point et une distance `r`, l’aire de la construction régulière est
`2 × q × sin(π / (2 × q)) × r²`, avec `q=quad_segs`. Son écart à `πr²` décrit
l’approximation du cercle, séparément des résidus numériques. Pour un segment
droit de longueur `L`, la capsule arrondie a une aire de
`2 × L × r + 2 × q × sin(π / (2 × q)) × r²`.

La précision des coordonnées reste celle de la représentation flottante. Des
distances très petites devant l’amplitude des coordonnées peuvent perdre en
précision. Le bilan contrôle les géométries construites ; sa fermeture ne
certifie pas la distance terrain, la qualité du SCR ou la précision des sources.

Aucune réparation, grille de précision, suppression de petites surfaces ou
priorité entre sources n’est appliquée. Tous les composants d’aire strictement
positive sont conservés. Une distance non représentable ou une construction
invalide provoque un refus explicite.

## Tables et traçabilité

`BufferRingsResult` contient cinq objets.

| Objet | Contenu |
|---|---|
| `data` | GeoDataFrame des anneaux d’aire positive, en Polygon ou MultiPolygon |
| `table` | DataFrame dense, une ligne par groupe et intervalle, y compris les intervalles d’aire nulle |
| `sources` | GeoDataFrame des sources en XY et dans le SCR d’analyse, avec identifiants, étiquettes typées et positions d’origine |
| `balances` | DataFrame des contrôles de surface par groupe |
| `summary` | Paramètres, facteurs d’unités, règles, effectifs, correspondances et bilan global |

`data` et `table` possèdent les mêmes champs attributaires :

| Champ | Sens |
|---|---|
| `ring_id` | Identifiant technique stable dans le résultat, indépendant de l’étiquette source |
| `group_id` | Groupe fusionné ou série d’une source indépendante |
| `band_index` | Numéro d’intervalle, à partir de 1 |
| `lower_m`, `upper_m` | Bornes en mètres, quelle que soit l’unité du SCR |
| `area` | Surface de l’anneau dans `area_unit` |

Le registre `sources` contient `source_id`, `source_row` à partir de zéro,
`id_type`, `id_value`, `geometry_type`, `source_area` et la géométrie. En
l’absence de `id_field`, l’étiquette est la position entière de la source. Si un
champ est choisi, une étiquette manquante est refusée. `id_type` distingue les
chaînes, entiers, flottants, booléens, dates, dates-heures et décimaux pris en
charge ; `id_value` conserve leur représentation canonique sans arrondir les
grands entiers. Les textes `001`, `NA` et la chaîne vide restent des textes.

Les autres attributs ne sont ni copiés ni agrégés dans les anneaux. Ils restent
dans la source intacte. `summary.groups` associe chaque groupe à ses
`source_ids` et `source_rows`, permettant de les retrouver explicitement. Un
index pandas dupliqué n’est pas utilisé comme identité technique.

## Bilans de surface

Chaque ligne de `balances` expose les contrôles suivants, dans l’unité choisie.

| Champs | Interprétation |
|---|---|
| `group_id`, `source_count` | Identité de la série et nombre de lignes sources |
| `base_area` | Surface retirée au départ ; zéro lorsque l’intérieur est inclus |
| `outer_area` | Surface du tampon extérieur maximal |
| `expected_area` | Surface attendue après retrait de la base |
| `sum_ring_area`, `union_ring_area` | Somme des anneaux et surface de leur réunion |
| `overlap_area` | Emprise unique partagée par au moins deux anneaux |
| `excess_area`, `raw_excess_area` | Somme moins réunion, avec résidu signé conservé dans `raw_excess_area` |
| `uncovered_area`, `outside_area` | Manque dans l’emprise attendue et surface au-delà de celle-ci |
| `closure_error` | Surface attendue moins somme des anneaux, signée |
| `max_step_closure_error` | Plus grand résidu absolu après une distance intermédiaire |
| `non_nested_area` | Somme des résidus d’inclusion des tampons cumulés |

Les contrôles utilisent `1e-6 m² + 1e-8 × surface de référence en m²`, converti
dans l’unité demandée. Cette tolérance contrôle les résidus arithmétiques et
géométriques ; elle ne filtre aucune géométrie. Un résidu au-delà de cette
tolérance est refusé. Un excès négatif dans la tolérance devient zéro dans
`excess_area`, tandis que sa valeur d’origine reste dans `raw_excess_area`.

Le bilan global `summary.totals` distingue `sum_ring_area`, `union_ring_area`,
`overlap_area`, `excess_area` et `raw_excess_area`. En mode indépendant, une
surface couverte par trois sources contribue une fois à l’emprise de
recouvrement et deux fois à l’excès. Additionner les intersections par paires
ne donne donc pas la surface unique du recouvrement.

## Enregistrement vérifié et atomique

```python
record = cm.execute_operation(
    "vector.buffer_rings",
    {"data": "villages.gpkg", "layer": "villages",
     "distances": [100, 250, 500, 1000], "metric_crs": "EPSG:32733",
     "id_field": "code", "mode": "dissolved", "area_unit": "ha"},
    "resultats/anneaux_villages",
)
```

Le dossier doit être nouveau. Les fichiers sources et les résultats existants
sont protégés. Les produits sont écrits dans un dossier temporaire, relus,
vérifiés puis publiés ensemble. Une erreur ou une annulation annule ce dossier.

| Produit nommé | Fichier |
|---|---|
| `primary`, `data` | `data.gpkg`, couche `features` |
| `sources` | `sources.gpkg`, couche `features` |
| `table` | `table.csv` et `table.csv.schema.json` |
| `balances` | `balances.csv` et `balances.csv.schema.json` |
| `audit` | `audit.json` |
| `summary` | `summary.json` |
| Manifeste du traitement | `operation.json` |

Les **neuf fichiers** constituent la livraison complète. Les GeoPackage sont
vérifiés par géométrie WKB, attributs et SCR. Les CSV UTF-8 sont relus avec
leurs types et une précision de flottants permettant la comparaison exacte.
L’audit `cartomize.vector_rings.audit.v1` conserve les tables et les empreintes
SHA-256 des quatre fichiers de données vérifiés. Le manifeste porte les chemins
définitifs et le résumé du moteur. Les schémas des tables sont nécessaires à
leur interprétation dans le lecteur Cartomize.

`progress(done, total)` utilise une progression totale de 10 000. Dans la
publication, les premiers 8 000 correspondent au moteur et les derniers 2 000
aux sorties vérifiées. L’annulation est vérifiée entre étapes ; une opération
géométrique native déjà en cours doit se terminer avant le prochain contrôle.

## Terminal, plans et fenêtre

```bash
cartomize buffer-rings villages.gpkg resultats/anneaux_villages --layer villages --distances 100 250 500 1000 --metric-crs EPSG:32733 --id-field code --mode dissolved --area-unit ha
```

Les options supplémentaires sont `--include-input` et `--quad-segs`.
`cartomize process vector.buffer_rings parametres.json sortie` utilise le même
registre. Dans un plan, `@anneaux:data`, `@anneaux:sources`, `@anneaux:table` et
`@anneaux:balances` exposent les produits de l’étape `anneaux`. Un croisement
G09 peut recevoir `@anneaux:data` comme zones et `ring_id` comme champ de zone.

Dans **Vecteur → Anneaux de distance avec bilan**, sélectionner la couche
source, l’étiquette facultative, les bornes et les politiques. Le formulaire
utilise des points-virgules, par exemple `100; 250; 500; 1000`, et le point
pour les décimales. Il affiche immédiatement les intervalles. Les six boutons
de résultat ouvrent les anneaux, les intervalles, les sources, les bilans, le
résumé et l’audit. Ils restent liés au traitement terminé si le formulaire est
modifié ensuite. Les sessions et les projets portables conservent ces liens.

Le [cours 21](../tutorials/notebooks/21_anneaux_distance.ipynb) exécute les modes,
les formules indépendantes, les cas ponctuels, linéaires et polygonaux, la
publication, le terminal, un plan G12→G09, les refus et l’annulation.

## Références et portée

La [documentation ArcGIS Multiple Ring Buffer](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/analysis/multiple-ring-buffer.html)
distingue également les anneaux fusionnés et l’option de retrait de l’intérieur
des polygones. Ses modes et valeurs par défaut ne sont pas ceux de toutes les
fonctions Cartomize : le contrat ci-dessus définit précisément les anneaux par
source, le retrait initial et le calcul projeté de G12.

Les tests de référence utilisent une formule de polygone régulier, des capsules
de segments droits et des rectangles. Les essais sur données publiques
examinent aussi les formes réelles, les intersections, les fichiers écrits et
l’intégrité des sources. Leur détail est conservé dans
[VALIDATION_G12_REAL.json](VALIDATION_G12_REAL.json) et la
[note 1.12.0](RELEASE_1.12.0.md). Ces contrôles ne constituent pas une précision
terrain certifiée ni une analyse statistique d’un effet de proximité.
