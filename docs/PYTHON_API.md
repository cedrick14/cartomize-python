# Exemples Python

Les exemples utilisent des chemins de données à adapter au projet. Les traitements nécessitent des systèmes de coordonnées et des bandes compatibles.

Les scripts et les cellules Jupyter appellent cette même API, sans dépendance à Qt. Voir [l’installation et les noyaux Jupyter](NOTEBOOKS.md). Les changements de valeurs par défaut de la version 1.3.0 sont décrits dans la [note de version](RELEASE_1.3.0.md).

## Prétraitement automatique avec contrôle de couverture

```python
import cartomize as cm

try:
    images = cm.preprocess_imagery(
        "donnees/scenes", "resultats/automatique_01",
        aoi="zone_etude.gpkg", band_order=["red", "nir"],
        coverage_threshold=100, allow_partial=False,
    )
except cm.ImageryCoverageError as erreur:
    print(erreur.manifest, erreur.diagnostic.gaps)
else:
    cm.spectral_indices(images.products[0]["multiband"], "ndvi.tif", ["NDVI"])
```

Le moteur sélectionne les scènes, décide de la mosaïque et bloque la production
si le seuil n’est pas atteint. `allow_partial=True` accepte explicitement une
couverture non vide inférieure au seuil ; son statut reste partiel. Un catalogue
STAC facultatif peut compléter les données. Voir le [module M07](IMAGERY_AUTOMATIC.md)
pour les entrées, les produits, la politique de couverture et les commandes.

## Diagnostic des scènes et couverture zonale

```python
import cartomize as cm

diagnostic = cm.audit_imagery(
    "donnees/scenes", "resultats/diagnostic_01",
    aoi="zone_etude.gpkg", band_order=["red", "nir"],
)
print(diagnostic.report["recommended_action"])
print(diagnostic.report["usable_percent"])

zones = cm.read_file("zones.gpkg")
tableau = cm.raster.zonal_stats(
    "ndvi.tif", zones, value_mode="physical",
    prefix="ndvi_", include_coverage=True,
)
```

Le diagnostic et les statistiques sont deux opérations indépendantes dans cet extrait ; `ndvi.tif` doit avoir été calculé à partir d’un produit scientifique adapté. Le [cours 13](../tutorials/notebooks/13_diagnostic_automatique.ipynb) exécute leur enchaînement complet sur des données générées. Les contrats des [images](IMAGERY_AUDIT.md), des [statistiques zonales](RASTER_STATISTICS.md), de la [classification](CLASSIFICATION.md) et du [registre de traitements](PROCESSING.md) précisent les paramètres et les limites.

## Analyse du projet et NoData

La rubrique **Analyse du projet** importe plusieurs couches, détecte les fonds
périphériques, prépare des copies masquées et propose des classes. Le bouton
**Appliquer à la mise en page** transmet les couches et la nomenclature éditée
au rendu cartographique. **Rétablir les sources** recharge les fichiers initiaux.

```python
projet = cm.prepare_project([
    {"data": "occupation.tif", "classes": {
        2: ("Forêt primaire", "#26743b"),
        3: ("Forêt secondaire", "#88ad56"),
    }},
    "routes.gpkg", "localites.gpkg",
], "resultats/analyse_01")
projet.compose(title="Occupation du sol").export("carte.pdf")
# Recharger le plan ou retrouver les sources sans masquage supplémentaire :
projet = cm.load_project("resultats/analyse_01/project.json")
original = cm.load_project(projet.manifest, original_sources=True)
```

Les fonds non déclarés sont une inférence spatiale, jamais une certitude.
Les rasters binaires 0/1 et les classes documentées sont protégés par défaut.
Les libellés ne sont pas devinés à partir des codes. Voir le
[fonctionnement des masques](PROJECT_ANALYSIS.md) et le
[périmètre fonctionnel](FUNCTIONAL_COVERAGE.md).

## Automatiser la production depuis Python

```python
import cartomize as cm

production = cm.cartographic_workflow(
    "donnees/scenes", "resultats/production_01",
    aoi="zone.gpkg",
    layers=["routes.gpkg", "localites.gpkg", "limites.gpkg"],
    composition="natural", title="Carte de la zone d'étude",
    credits="Sources et auteur", formats=("pdf", "png"),
)
print(production.multiband, production.maps)
```

Le répertoire de production doit être nouveau. Les produits sont préparés
ensemble avant leur enregistrement final. La reconnaissance automatique
couvre Landsat C2 L2 SR et Sentinel-2 L2A; d'autres données peuvent être
fournies en Python par des objets `Scene` et `Band` explicites.

Avec `aoi`, cette production utilise le contrôle automatique de couverture,
100 % par défaut, avant de rendre la carte. Elle accepte `coverage_threshold`,
`allow_partial` et `catalog`. Les chemins `production.multiband` et
`production.maps` désignent les produits publiés, y compris lorsque la
préparation est rangée dans un sous-dossier.

## Algèbre raster et indices spectraux

```python
import cartomize as cm

cm.spectral_indices("multibande.tif", "indices.tif",
                    ["NDVI", "EVI", "SAVI", "NDMI"], workers=4)
cm.calculate("where((nir-red)/(nir+red) > 0.4, 1, 0)",
             {"nir": ("multibande.tif", 4), "red": ("multibande.tif", 3)},
             "seuil.tif")
cm.focal("ndvi.tif", "moyenne_locale.tif", statistic="mean", size=5)
cm.reduce_rasters(["ndvi_2020.tif", "ndvi_2026.tif"], "moyenne_temporelle.tif")
```

Le catalogue comprend 18 indices documentés et accepte des définitions
supplémentaires avec `register_index`. Le calculateur accepte des expressions
arithmétiques, logiques, conditionnelles et statistiques. Les bandes doivent
être nommées ou affectées explicitement, et leurs valeurs correctement calibrées.

Les calculs utilisent des blocs et partagent la lecture des bandes entre indices. Les paramètres de concurrence et de mémoire sont décrits dans le guide des moteurs de calcul.

- [Formules, opérations, masques et paramètres](RASTER_CALCULATIONS.md)
- [Protocole et résultats de performances](PERFORMANCE.md)

## Produire une carte

```python
import cartomize as cm

villages = cm.read_file("villages.gpkg")
carte = cm.Map(
    title="Localisation des villages",
    subtitle="District de Mvouti",
    crs="EPSG:32733",
    credits="Sources : données de terrain | Auteur : Cédrick Belmich",
)
carte.add_layer(villages, name="Villages", labels="nom", color="#254f54")
carte.export("villages.pdf", dpi=300)
```

Les légendes, la flèche du nord vrai et l'échelle sont activées par défaut.
Les exports PDF, PNG et SVG conservent le format physique de la page.
Pour un raster, déclarer explicitement les libellés et couleurs des classes :

```python
carte = cm.Map(title="Occupation du sol", crs="EPSG:32733")
carte.add_layer("occupation.tif", name="Occupation du sol", classes={
    1: ("Forêt dense", "#1b5e20"),
    2: ("Forêt perturbée", "#81c784"),
    3: ("Agriculture", "#e8c46a"),
})
carte.export("occupation.png", dpi=300)
```

## Des scènes satellite à la carte

La chaîne de préparation reconnaît les bandes Landsat C2 L2 et Sentinel-2 L2A,
aligne les grilles, applique les facteurs de calibration et masques de qualité,
assemble les scènes en GeoTIFF multibande et découpe selon la zone d'étude.
Elle exporte aussi l'origine des pixels et un rapport de couverture.

```python
scenes = cm.discover_scenes("donnees/scenes")
image = cm.prepare_imagery(
    scenes, "resultats/multibande.tif", aoi="zone.gpkg",
    band_order=["blue", "green", "red", "nir"],
    target_crs="EPSG:32733",  # SCR de la zone d’étude.
)
carte = cm.compose_map([
    {"data": "routes.gpkg", "name": "Routes"},
    {"data": "localites.gpkg", "name": "Localités", "labels": "auto"},
    {"data": image.path, "rgb": "natural"},
], aoi="zone.gpkg", title="Carte de la zone d’étude")
carte.export("resultats/carte.pdf")
```

Les couches sont ordonnées automatiquement par rôle; `role` et `zorder`
permettent de corriger l'inférence. Une composition colorée n'est pas une
classification d'occupation du sol. Les sources sans métadonnées reconnues
peuvent être décrites explicitement par `Scene` et `Band`.

Voir le [guide détaillé et les principes cartographiques](IMAGERY_WORKFLOW.md)
et la démonstration `python examples/imagery_workflow.py`.

## Traitements vectoriels compatibles avec GeoPandas

Les fonctions retournent des **GeoDataFrame/GeoSeries standards** : les
méthodes habituelles de GeoPandas restent utilisables.

```python
zones = cm.buffer(villages, 500, metric_crs="EPSG:32733")  # mètres
zones["surface_ha"] = cm.area(zones, metric_crs="EPSG:32733")
intersection = cm.overlay(zones, cm.read_file("forets.gpkg"))
jointure = cm.sjoin(villages, cm.read_file("districts.gpkg"), predicate="within")
fusion = cm.dissolve(intersection, by="nom")
rapport = cm.vector.analyze(villages, name="Villages")
```

Également disponibles : `clip`, `reproject`, `from_xy`, `length`, `validate`,
`make_valid`. Les fonctions combinant deux couches alignent le CRS de la
seconde sur celui de la première. Les mesures exigent un CRS projeté, fourni
par les données ou par `metric_crs`; les distances ne sont jamais calculées
en degrés. Les surfaces sont planaires : choisir une projection adaptée à
l'étendue et au niveau de précision recherché.

## Traitements raster

```python
cm.raster.ndvi("multispectral.tif", "ndvi.tif", red=3, nir=4)
cm.raster.reclassify("classes.tif", "foret.tif", {1: 1, 2: 0, 3: 0})
statistiques = cm.raster.zonal_stats("ndvi.tif", zones)
surfaces = cm.raster.class_areas("classes.tif", unit="ha")
changements = cm.raster.change_matrix("classes_2000.tif", "classes_2026.tif")
diagnostic = cm.raster.inspect("classes.tif")
```

`ndvi` exige les numéros réels des bandes, à partir de 1; il ne devine pas le
capteur. Les facteurs d'échelle et décalages GDAL sont appliqués; utiliser
`scale=` et `offset=` si le produit les fournit séparément. `raster.clip` et
`raster.reproject` complètent les traitements. Les transformations de ce module écrivent
une seule bande; elles ne modifient pas les fichiers sources.

Les masques, NoData, NaN et Inf sont exclus des calculs. Un zéro valide est
conservé. Le diagnostic individuel `raster.inspect` propose des valeurs NoData potentielles
sans les appliquer. `prepare_project` applique les règles documentées de
préparation dans des copies ; `keep_values` protège les valeurs valides. Les matrices de changement exigent des grilles identiques.
La surface raster utilise le déterminant de la transformation et les unités
du CRS projeté. Les indices et reclassifications sont traités par fenêtres;
le découpage charge l'emprise découpée en mémoire.

## Les 24 maquettes de Cartomize

```python
print(cm.list_templates())
identifiant = cm.list_templates()[0]["id"]
carte = cm.Map(template=identifiant, title="Carte de la zone d’étude", crs="EPSG:32733")
carte.add_layer(villages, labels="nom")
print(carte.frame_ids)
# Configurer chaque cadre avec ses limites dans son CRS si nécessaire :
# carte.set_frame("main-map", extent=(xmin, ymin, xmax, ymax))
carte.export("maquette.pdf")
```

Les identifiants exacts sont fournis par `list_templates` et `frame_ids`.
`set_frame` permet aussi de sélectionner les couches par leur nom et un CRS
particulier. Sans configuration, les cadres partagent les données et
l'emprise par défaut : une carte de localisation exige des couches et
des emprises appropriées. `set_text`, `set_table` et `set_chart` remplissent
les éléments nommés des maquettes. Un tableau ou graphique non renseigné
reste vide. Le rendu Matplotlib peut différer du rendu natif Esri.

## Atlas et ligne de commande

```python
cm.atlas(carte, cm.read_file("zones.gpkg"), "atlas", name_column="nom")
```

```bash
cartomize --version
cartomize templates
cartomize inspect occupation.tif
cartomize map villages.gpkg villages.pdf --labels nom --title "Villages"
python examples/demo.py
```

La démonstration génère des **données fictives**, explicitement identifiées,
et des cartes PDF/PNG/SVG. Les fichiers existants sont protégés sauf demande
explicite `overwrite=True`. L'atlas vérifie les noms avant de produire les pages.

## Qualité des données vectorielles

`cm.audit_geometries()`, `cm.repair_geometries()`, `cm.check_topology()` et `cm.deduplicate()` renvoient un `VectorQualityResult` : couche principale, rapport par entité, synthèse et couches de diagnostic/exclusion. Les paramètres sont communs au terminal et à la fenêtre. Voir [G01–G03](VECTOR_QUALITY.md) et le [cours 14](../tutorials/notebooks/14_qualite_vectorielle.ipynb).

## Reprojection vectorielle par lot

```python
sources = "donnees/vecteurs"
inspection = cm.inspect_reprojection(sources, "EPSG:32733", recursive=True)
for couche in inspection["layers"]:
    print(couche["id"], couche["source_crs"], couche["catalogue"]["best_available"])

lot = cm.reproject_batch(sources, "resultats/reprojection_01", "EPSG:32733", recursive=True)
print(lot.manifest, lot.report)
for identifiant, chemin in lot.layers.items():
    print(identifiant, chemin)
```

`discover_vector_layers` découvre les couches, y compris celles d’un GeoPackage
multicouche. `inspect_reprojection` expose les opérations, leur précision annoncée
et les grilles disponibles ou manquantes. `reproject_batch` publie un nouveau
dossier contenant un GeoPackage par couche, le bilan CSV et le manifeste de
transformation. Les coordonnées sont transformées dans l’ordre SIG x/y ; les
attributs et les géométries enregistrées sont relus avant publication.

Les valeurs par défaut exigent la meilleure opération disponible et refusent
les approximations géodésiques. `operations={identifiant_couche: identifiant_operation}`
fixe les choix examinés ; la référence `@lot:identifiant_couche` transmet une
couche précise aux étapes suivantes d’un plan. Le module couvre les SCR
horizontaux statiques à deux axes ; Z est conservé sans transformation verticale.
Voir le [contrat M09/G04](VECTOR_REPROJECTION.md) et le
[cours 15](../tutorials/notebooks/15_reprojection_vectorielle_par_lot.ipynb).

## Harmonisation et fusion de couches

```python
sources = ["releve_A.gpkg", "releve_B.gpkg"]
inspection = cm.inspect_merge(sources)
for couche in inspection["layers"]:
    print(couche["id"], couche["fields"])

# Exemple de schéma pour des champs déjà nommés de façon identique.
schema = {"code": "string", "nom": "string", "habitants": "int64"}
fusion = cm.merge_layers(sources, "resultats/fusion_01", schema=schema)
couche = cm.vector.read_file(fusion.data)
print(fusion.manifest, fusion.report, fusion.issues)
```

`field_maps={identifiant_source: {champ_source: champ_cible}}` raccorde les noms
différents ; une cible `None` supprime explicitement un champ. Le schéma peut
préciser `nullable` et `default`. Les conversions invalides sont refusées par
défaut ; `conversion_errors="null"` les consigne et crée une absence soumise
aux obligations du schéma. Les paramètres `missing_fields` et `extra_fields`
rendent également explicites les champs manquants ou non retenus.

L’inspection expose les conflits de noms tels que `Name`/`name` et les attributs
métier nommés `geometry`, afin de pouvoir les remapper avant la fusion. Un champ
`object` entièrement nul sans type déclaré peut adopter le type concret d’une
autre source ; un champ déclaré `TEXT` conserve son type texte même entièrement
nul. Le [guide des schémas](VECTOR_MERGE.md) décrit ces décisions.

`MergedVectors` expose `data`, `manifest`, `report`, `issues` et `summary`.
Les enregistrements conservent cinq colonnes de provenance et leurs géométries.
Sans `target_crs`, les SCR doivent déjà être identiques ; une cible explicite
réutilise les règles de M09. L’opérateur `vector.merge_layers` expose notamment
`@fusion:data` dans les plans. Voir le [guide M10/G05](VECTOR_MERGE.md) et le
[cours 16](../tutorials/notebooks/16_harmonisation_fusion_vectorielle.ipynb).

## Conversion et conditionnement G06

```python
inspection = cm.inspect_vector_conversion("donnees.gpkg")
vecteur = cm.convert_vector("donnees.gpkg", "livraison_vecteur", layer="villages", driver="GPKG")
raster = cm.convert_raster("classes.tif", "livraison_cog", driver="COG", dtype="uint8", nodata=255)
print(vecteur.data, vecteur.report, raster.data, raster.report)
```

Les dossiers de sortie doivent être nouveaux. Les deux résultats exposent `data`, `report`, `manifest` et `summary`. Une couche multicouche exige une sélection explicite. La politique `loss_policy="error"` refuse une perte de représentation ; `report` autorise seulement les changements mesurés et consignés. Les contrôles de plage, coordonnées, projection et validité restent obligatoires. Voir les [paramètres et formats G06](DATA_CONVERSION.md).

## Extraction attributaire et spatiale avec audit

`cm.extract_features(data, filters=[{"field": "valeur", "comparison": "gt", "value": 0}], mask=masque)` renvoie un `VectorSelectionResult` avec `data`, `rejected`, `report`, `summary`. `cm.execute_operation("vector.extract_features", parametres, dossier_neuf)` publie les partitions et rapports vérifiés. Voir les conventions, types et exemples dans le [guide G07](VECTOR_SELECTION.md).

## Table croisée des surfaces polygonales

`cm.tabulate_area(zones, classes, zone_field="code", class_field="classe",
metric_crs="EPSG:32733", area_unit="ha")` renvoie un `AreaTabulationResult`
avec `data`, `table`, `matrix`, `zones`, `categories`, `gaps`, `overlaps`,
`summary`. Choisir une projection adaptée à l’étude. Les groupes de même
identité sont dissous ; les recouvrements entre catégories sont refusés par
défaut. `overlap_policy="report"` les conserve avec un bilan explicite.
`cm.execute_operation("vector.tabulate_area", parametres, dossier_neuf)`
publie et vérifie tous les produits. Voir le [contrat G09](VECTOR_TABULATION.md).

## Anneaux de distance avec bilan

```python
result = cm.buffer_rings(
    "villages.gpkg", [100, 250, 500, 1000],
    layer="villages", metric_crs="EPSG:32733",
    id_field="code", mode="dissolved", area_unit="ha",
)
result.data       # Anneaux polygonaux dans le SCR du calcul
result.table      # Tous les intervalles, même de surface nulle
result.sources    # Identités typées et positions sources
result.balances   # Contrôles par groupe
result.summary["totals"]
```

Les distances sont des bornes supérieures positives croissantes en mètres. `mode="independent"` conserve une série par source et rapporte leurs recouvrements ; `include_input=True` ajoute l’intérieur des polygones au premier intervalle. `quad_segs` règle l’approximation des arcs. Les sources restent intactes. Le SCR de cet exemple doit être adapté au territoire étudié. `execute_operation("vector.buffer_rings", paramètres, nouveau_dossier)` publie tous les produits vérifiés. [Contrat G12](VECTOR_RINGS.md).
