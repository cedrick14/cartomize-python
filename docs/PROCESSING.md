# Chaînes de traitements

## Registre et dépendances

`operation_catalog()` décrit les 50 opérations, leurs paramètres, leur type de
sortie et leurs produits secondaires. `execute_operation()` exécute une opération
isolée. `processing_plan()` enchaîne des opérations sans imposer de carte finale.
`plan_cartography(..., processing_steps=...)` les insère avant l’analyse du projet
et la mise en page. La fenêtre utilise ces mêmes fonctions.

```python
import cartomize as cm

steps = [
    {"id": "pente", "operation": "terrain",
     "parameters": {"source": "mnt.tif", "products": ["slope"]}},
    {"id": "seuil", "operation": "calculate",
     "parameters": {"inputs": {"p": ["@pente", 1]},
                    "expression": "where(p >= 30, 1, 0)"},
     "map_layer": {"name": "Pentes fortes", "classes": {
         0: ["Moins de 30°", "#eeeeee"], 1: ["30° et plus", "#555555"]}}},
]
plan = cm.plan_cartography(["mnt.tif", "localites.gpkg"],
    processing_steps=steps, title="Contraintes topographiques", credits="Sources")
result = cm.run_plan(plan, "production", workers=4,
                     block_size=512, memory_limit_mb=512)
```

`@identifiant` désigne le produit principal. `@drainage:watersheds` sélectionne
les bassins ; `@classification:confidence` sélectionne la confiance. Dans
`map_layer`, `product` permet ce même choix. `@scientific` est remplacé par le
multibande scientifique dans un plan cartographique ; cette référence n’est pas
définie dans un plan de traitements indépendant.

Le graphe entier est vérifié avant écriture : noms uniques, opérateurs enregistrés,
paramètres connus et dépendances antérieures. Les arguments de sortie, fonctions
Python et options d’écrasement ne peuvent pas être fournis par le document.
Le nouveau dossier n’apparaît qu’après succès de l’ensemble. L’annulation reste
coopérative ; une opération GEOS/GDAL non interruptible doit se terminer.

Les paramètres de blocs, travailleurs et mémoire sont transmis aux opérateurs
compatibles. Un paramètre indiqué dans une étape prévaut sur le réglage global.
Le budget des tableaux ne constitue pas un plafond de mémoire du processus.

```bash
cartomize operations
cartomize process terrain parametres.json resultat --workers 4
cartomize plan plan.json mnt.tif --steps etapes.json --title "Relief"
cartomize run-plan plan.json production --workers 4 --block-size 512
```

## Prétraitement automatique des images

L’opérateur `imagery.preprocess` applique le [module M07](IMAGERY_AUTOMATIC.md) :
diagnostic, compléments STAC facultatifs, sélection des scènes, décision de
mosaïque, contrôle du seuil et préparation. Il exige `sources` et `aoi`.
`coverage_threshold=100` et `allow_partial=False` sont les valeurs par défaut.
Le produit principal est un manifeste JSON ; `@images:multiband` désigne le
GeoTIFF scientifique d’une étape nommée `images`. Les sorties `coverage`, `gaps`
et `audit` restent accessibles indépendamment de l’image.

Une couverture insuffisante lève `ImageryCoverageError`, interrompt les étapes
dépendantes et conserve un diagnostic dans un dossier voisin du résultat
demandé. Les dossiers scientifiques du plan ne sont pas publiés. Un résultat
partiel volontaire est identifié dans le manifeste et les métadonnées de
l’opération.

```bash
cartomize preprocess-imagery scenes resultat --aoi zone.gpkg --bands red,nir
cartomize process imagery.preprocess parametres.json resultat
cartomize plan plan.json scenes --kind scenes --aoi zone.gpkg --coverage-threshold 100
```

Les plans cartographiques construits avec des scènes et une zone d’étude
utilisent aussi cet opérateur. Leurs dépendances scientifiques sont résolues
vers le produit multibande. Sans zone d’étude, la préparation historique sur
l’étendue des scènes est conservée, sans contrôle de couverture territoriale.

## Hydrologie

`hydrology()` produit cinq GeoTIFF : MNT comblé, direction D8, accumulation,
réseau binaire défini par un seuil, et bassins. Le remplissage suit Priority-Flood.
Les cellules descendantes prennent la plus forte pente parmi huit voisins ; les
plats suivent l’arbre parent du remplissage pour garantir un drainage sans cycle.
Les directions sont codées E=1, SE=2, S=4, SO=8, O=16, NO=32, N=64, NE=128.
Zéro désigne un exutoire et 65535 le NoData dans le raster de directions.

L’accumulation inclut la cellule elle-même. La superficie contributive s’obtient
en la multipliant par la superficie du pixel. Les bords et les cellules adjacentes
au NoData sont ouverts. Les exutoires facultatifs sont des points dans le SCR du
fichier ; ils sont reprojetés mais ne sont pas déplacés automatiquement sur un cours
d’eau. Des exutoires imbriqués délimitent des bassins incrémentaux : chaque cellule
est affectée au premier exutoire rencontré en aval. Zéro désigne un bassin non
affecté à un exutoire fourni ; -1 le NoData.

Ce calcul utilise des tableaux globaux et une estimation de mémoire préalable.
Il faut augmenter explicitement le budget ou sélectionner un bassin complet si
le MNT est trop grand. Découper arbitrairement une zone modifie ses limites
hydrologiques. D8 n’est ni une simulation hydraulique ni un calcul de débit ; MFD,
D-infinity, incision des dépressions et Strahler ne sont pas inclus.

## Routage

`shortest_path()` utilise Dijkstra sur un réseau de lignes, avec distances en mètres.
Par défaut, `snap="edge"` projette les coordonnées de départ/arrivée sur les
segments les plus proches dans `max_snap_m`, puis insère ces positions dans le
graphe. Deux positions à 400 m et 600 m sur un segment de 1 000 m donnent donc un
trajet de 200 m. `snap="node"` conserve le rattachement aux seuls sommets, pour
reproduire explicitement le comportement précédent.

Les géométries sont segmentées aux sommets et, par défaut, aux intersections.
Les deux extrémités projetées sur un même segment sont traitées ensemble ; les
connexions existantes sont conservées. Une insertion sur une arête ne crée pas de
connexion à un croisement non nodé lorsque `node_intersections=False`.

Les distances de rattachement figurent dans `start_snap_m` et `end_snap_m`.
`distance_m` mesure le parcours sur le réseau, hors déplacements de rattachement.
`snap_method` enregistre le mode choisi. Si les deux coordonnées sont rattachées
au même point du réseau, la sortie est un **Point valide** avec `distance_m=0`
et `route_status="coincident"`. Un trajet ordinaire est une LineString avec
`route_status="ok"`.

```python
trajet = cm.shortest_path(
    "routes.gpkg", [400, 0], [600, 0],
    points_crs="EPSG:32733", metric_crs="EPSG:32733",
    max_snap_m=25, snap="edge",
)
```

Les coordonnées de cet exemple sont illustratives. Déclarer leur SCR réel ; le
SCR de calcul doit être projeté et adapté à l’étude. Les unités projetées en pieds
sont converties en mètres. La géométrie de sortie retrouve le SCR du réseau source.

Le graphe est bidirectionnel. Les sens uniques, restrictions de virage et vitesses
ne sont pas inférés. Pour les ponts et passages dénivelés, fournir un réseau déjà
préparé et désactiver `node_intersections`. Les composantes déconnectées et les
rattachements hors tolérance provoquent une erreur explicite.

Les segments équidistants sont départagés de manière déterministe selon leur
ordre dans le graphe construit. Ce choix ne déduit ni le niveau d’un pont, ni le
sens d’une route, ni l’itinéraire voulu par l’utilisateur. Examiner le rattachement
sur la carte lorsque plusieurs axes sont très proches.

## Scènes STAC et capteurs supplémentaires

`search_stac(endpoint, bbox=..., datetime_range=..., collections=..., limit=...)`
consulte un service STAC Item Search choisi par l’utilisateur. Les pages GET/POST
sont suivies jusqu’à la limite demandée ; les boucles et volumes excessifs sont
refusés. `download_stac()` télécharge les assets HTTP(S) sélectionnés dans un
nouveau dossier, conserve les métadonnées locales et calcule leurs empreintes.
Les empreintes SHA256 annoncées au format multihash sont vérifiées. Une limite
globale d’octets, un délai et l’annulation contrôlent le transfert. Les mécanismes
privés d’authentification ou de signature d’URL propres aux fournisseurs ne sont
pas fournis par la bibliothèque.

`intersects=geometrie_geojson` recherche sur la géométrie réelle en WGS84,
avec une requête POST. Ce paramètre est exclusif de `bbox`.

`discover_scenes()` accepte les fichiers STAC Item/FeatureCollection locaux et
les dossiers téléchargés contenant `scenes.json`. Les rôles spectraux et les
coefficients proviennent des métadonnées `bands`, `eo:bands` et `raster:bands`.
Une calibration absente est signalée ; les unités d’origine sont conservées.
Ne pas assimiler ces valeurs à une réflectance sans information du producteur.
Les profils Landsat C2 L2 et Sentinel-2 L2A raccordent automatiquement leurs
masques QA/SCL lorsqu’ils sont présents. Le téléchargement sélectionne aussi
les compagnons nécessaires avec `include_companions=True`, valeur par défaut.
Les correspondances particulières passent par `band_mapping`, `quality_asset`,
`quality_kind` et `saturation_asset`. `mask_clouds=False` reste un choix explicite
lorsque le produit ne possède pas de masque ; son absence n’est pas masquée.

Un manifeste `cartomize.scenes.v1` décrit aussi les données d’un capteur quelconque :

```json
{"schema":"cartomize.scenes.v1","scenes":[{
  "scene_id":"tuile_01","sensor":"capteur_declare","acquired":"2026-09-01",
  "bands":{"red":{"path":"rouge.tif","scale":0.0001,"unit":"reflectance"},
           "nir":{"path":"proche_infrarouge.tif","scale":0.0001,"unit":"reflectance"}}
}]}
```

Les coefficients de cet exemple sont illustratifs : employer ceux du produit.
Les bandes manquantes, capteurs incompatibles et dates mélangées ne sont pas
harmonisés silencieusement. Les sessions portables suivent les dépendances STAC.

## Reprise QGIS et contrôle cartographique

`import_native_project()` matérialise les sous-couches vectorielles locales,
conserve l’ordre, la visibilité des groupes, les styles simples/catégorisés,
la transparence, les palettes raster et les champs d’étiquettes pris en charge.
Les autres styles, services ou filtres figurent dans `transfer_warnings`.
La sortie `map.json` est directement réouvrable par `Map.load()`.

Les copies et exports natifs conservent leur rendu via le moteur ArcPy/PyQGIS
installé. Cette exécution reste à valider dans ces environnements ; l’import
autonome ne revendique pas la parité avec tous les objets natifs.

Le masquage par `valid_footprint` respecte les valeurs zéro valides dans l’emprise.
La nomenclature raster est vérifiée sur tous les blocs, et non uniquement sur
un échantillon. Les étiquettes évitent les symboles ponctuels et les autres
étiquettes placées ; les omissions sont rapportées. Les légendes essaient plusieurs
colonnes avant de signaler un débordement. L’exactitude thématique et tous les
conflits possibles avec les objets linéaires ou surfaciques nécessitent encore
une vérification cartographique.

## Références techniques

- Barnes, Lehman et Mulla, Priority-Flood : https://arxiv.org/abs/1511.04463
- Directions D8 : https://pro.arcgis.com/en/pro-app/3.3/tool-reference/spatial-analyst/how-flow-direction-works.htm
- STAC, métadonnées : https://github.com/radiantearth/stac-spec/blob/master/commons/common-metadata.md
- STAC Item Search : https://github.com/radiantearth/stac-api-spec/blob/main/item-search/README.md
- QGIS, styles : https://docs.qgis.org/testing/en/docs/user_manual/working_with_vector/vector_properties.html

## Qualité vectorielle dans les chaînes

Les quatre opérateurs `vector.audit_geometries`, `vector.repair_geometries`, `vector.check_topology` et `vector.deduplicate` exposent les produits `data`, `report`, `summary`, `issues` et `rejected`. Le produit principal de l’audit est la couche des anomalies ; celui de la réparation et du dédoublonnage est la couche conservée. Le contrôle topologique renvoie les violations. Utiliser `@audit:data` pour poursuivre depuis les données originales auditées. Les résultats sont publiés ensemble dans un nouveau dossier ; erreur ou annulation ne publient aucun résultat partiel. Voir [le guide](VECTOR_QUALITY.md).

## Reprojection vectorielle par lot

`vector.reproject_batch` accepte `sources` et `target_crs`, ainsi que les politiques
et sélections du [module M09](VECTOR_REPROJECTION.md). Il découvre automatiquement
les couches des fichiers et dossiers. `@lot:identifiant_couche` sélectionne une
couche précise du résultat d’une étape `lot` ; les identifiants sont obtenus avec
`discover_vector_layers`. Le manifeste et le bilan CSV conservent les opérations
réellement exécutées et les emprises avant/après. Le [cours 15](../tutorials/notebooks/15_reprojection_vectorielle_par_lot.ipynb)
exécute un plan qui poursuit les sites reprojetés avec des tampons.

## Harmonisation et fusion de couches

`vector.merge_layers` reçoit `sources`, les correspondances `field_maps` et
le `schema` cible. Les politiques `conversion_errors`, `missing_fields` et
`extra_fields` sont les mêmes que dans l’API. Il produit la couche `data`,
le `manifest`, le `report` et les `issues`. `data` est le produit principal ;
`@fusion:data` permet de le sélectionner explicitement dans l’étape suivante.

Le nouveau dossier est publié après contrôle des fichiers enregistrés.
Chaque ligne de la couche reste reliée à sa source et à sa position d’origine.
La fusion ne dissout ni ne dédoublonne les géométries. Le
[guide M10](VECTOR_MERGE.md) décrit les conversions et le
[cours 16](../tutorials/notebooks/16_harmonisation_fusion_vectorielle.ipynb)
exécute une chaîne de fusion puis tampons.

## Conversion G06 dans les plans

`vector.convert` et `raster.convert` fournissent `primary`, `data`, `manifest` et `report`. Leur produit `data` est un fichier géographique directement réutilisable, par exemple `@conversion:data`. Le dossier contient aussi les compagnons du format choisi.

```python
plan = cm.processing_plan([
    {"id": "conversion", "operation": "raster.convert", "parameters": {
        "source": "classes.tif", "driver": "COG", "dtype": "uint8", "nodata": 255}},
])
cm.run_plan(plan, "livraison_plan")
```

Les options de conversion sont celles de l’[API G06](DATA_CONVERSION.md). Les paramètres refusés et les différences non autorisées empêchent la publication du dossier.
