# Couverture fonctionnelle

Version 1.0. Les paramètres et conditions d’utilisation sont décrits dans le [catalogue des outils](TOOL_AUDIT.md).

| Domaine | Fonctionnalités |
|---|---|
| API et interface graphique | API indépendante, 20 rubriques, traitements en arrière-plan |
| Assistant cartographique | Règles explicables, plan exécutable, propositions de maquettes et reprise de la carte |
| Scènes jusqu’à la carte | Calibration, QA/SCL, mosaïque, multibande, extraction, composition, couches et export |
| NoData et bordures noires | Détection conservatrice, masquage des composantes périphériques, protection des classes et des sources |
| Traitements vectoriels | GeoPandas, superpositions, jointures, proximités, mesures et réparations |
| Raster et indices | Algèbre extensible, 18 indices, statistiques, classification, terrain et convolution |
| Exécution | Calcul par blocs, lectures partagées, files bornées, échantillonnage borné, arbres parallèles |
| Mise en page | 24 maquettes d’origine, cadres, habillage, dimensions éditables, textes mesurés, étiquettes, aperçu et export |
| Persistance | État des outils, couches, résultats et maquettes ; JSON et archive CMZ ; historique des actions principales |
| Recettes, lots et révision | Variables, associations de couches, journaux, migration, empreintes et décision nominative |
| Chaînes de traitements | 34 opérateurs, dépendances vérifiées, produits secondaires et paramètres moteur transmis |
| Hydrologie, routage et STAC | Drainage D8, bassins, plus court chemin, recherche et téléchargement de scènes |
| Projets natifs | Inventaire QGS/QGZ et import des styles pris en charge opérationnels ; passerelle QGIS testée dans le moteur QGIS ; validation ArcPy encore requise |
| Identité visuelle | Icône originale en couleur ; titre et contrôles en noir, blanc et gris |
| Publication Python | Wheel, distribution source, métadonnées et documentation ; distribution sur PyPI |


Le [guide des moteurs](EXECUTION.md) précise les opérations compatibles avec Dask et CUDA. Le [guide de visualisation](RESULTS_WORKSPACE.md) décrit les vues, comparaisons et limites de rendu.
