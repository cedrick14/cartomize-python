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
