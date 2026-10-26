# Références et choix pédagogiques

Consultation : 26 septembre 2026.

| Référence | Principe retenu |
|---|---|
| [GeoPandas, Examples Gallery](https://geopandas.org/en/stable/gallery/index.html) | Exemples ciblés associant une question, du code et un résultat visuel |
| [Geographic Data Science with Python, infrastructure du livre](https://geographicdata.science/infrastructure/2021/03/24/ci.html) | Exécution des chapitres par intégration continue pour détecter les ruptures de reproductibilité |
| [The Carpentries Workbench, Episode Structure](https://carpentries.github.io/sandpaper-docs/episodes.html) | Objectifs explicites, progression par étapes, exercices et éléments de correction |
| [GitHub, notebooks et fichiers scientifiques](https://docs.github.com/en/repositories/working-with-files/using-files/working-with-non-code-files) | Lecture des notebooks dans le dépôt ; séparation entre rendu statique et exécution interactive |
| [Jupyter Book, environnements interactifs](https://jupyter-book.readthedocs.io/v1/interactive/launchbuttons.html) | Accès à un environnement Binder ou Jupyter pour modifier et exécuter les exemples |
| [GeoPandas, opérations de superposition](https://geopandas.org/en/stable/docs/user_guide/set_operations.html) | Distinction entre intersection, union, différence et différence symétrique |
| [USGS, Landsat Collection 2 Level 2](https://www.usgs.gov/landsat-missions/landsat-collection-2-level-2-science-products) | Vérification du produit, de la calibration et des informations de qualité avant l’analyse spectrale |
| [Cartomize, registre des indices](../docs/RASTER_CALCULATIONS.md) | Formules et références des indices disponibles dans la version utilisée |

Les cours sont des créations propres à Cartomize. Les projets cités servent de références de structure et de méthode ; leurs textes et données ne sont pas reproduits.

Le parcours utilise directement des notebooks Jupyter et un export HTML avec nbconvert. Il ne dépend pas de Jupyter Book pour être lu sur GitHub. Cette structure permet de modifier, exécuter et relire chaque mini-projet séparément.

## Reprojection vectorielle — ajout du 26 octobre 2026

Le [cours 15](notebooks/15_reprojection_vectorielle_par_lot.ipynb) et la
[validation réelle M09](../docs/VALIDATION_M09_REAL.json) utilisent les
références primaires suivantes.

| Référence | Contrôle effectué |
|---|---|
| [PROJ, Web Mercator](https://proj.org/en/stable/operations/projections/webmerc.html) | Équations sphériques avec le demi-grand axe WGS84 ; calcul NumPy indépendant pour les sommets. Point publié : longitude 2°, latitude 49° → 222 638,98 m ; 6 274 861,39 m. |
| [PROJ, Universal Transverse Mercator](https://proj.org/en/stable/operations/projections/utm.html) | Points publiés des zones 32 Nord et 59 Sud, vérifiés dans le script réel à la précision centimétrique imprimée. |
| [pyproj, exemples avancés](https://pyproj4.github.io/pyproj/stable/advanced_examples.html) | Catalogue `TransformerGroup`, meilleure opération disponible, grilles absentes et zone d’intérêt. |

Les équations Web Mercator ne font pas appel à PROJ pour produire les valeurs
attendues. La comparaison du SCR Mercator personnalisé des aires protégées
utilise, elle, un appel direct séparé à PROJ : c’est une vérification
d’intégration du même moteur. Les exemples UTM publiés utilisent par défaut
GRS80 ; la comparaison WGS84 est limitée à leur précision imprimée de 0,01 m.

## Harmonisation et fusion — ajout du 26 octobre 2026

Le [cours 16](notebooks/16_harmonisation_fusion_vectorielle.ipynb) reprend
le principe de la [référence R016, Esri Merge](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/merge.html) :
associer les champs de plusieurs sources à un schéma commun, réunir les
enregistrements et conserver leur origine. La fusion maintient les géométries
et leurs éventuels recouvrements.

La lecture de contrôle utilise [SQLite et ses classes de stockage](https://www.sqlite.org/datatype3.html)
pour distinguer les entiers, textes et valeurs nulles enregistrés. Le script
sur données réelles examine aussi les coordonnées avec l’encodage WKB du
[standard OGC GeoPackage](https://www.geopackage.org/spec140/#gpb_format).
Les lignes attendues proviennent des JSON épinglés et de structures Python
simples, sans réutiliser la fusion Cartomize comme référence.
