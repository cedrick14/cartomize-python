# Couverture fonctionnelle

Version des sources **1.9.0**. Les paramètres et conditions d’utilisation sont décrits dans le [catalogue des outils](TOOL_AUDIT.md).

| Domaine | Fonctionnalités |
|---|---|
| API et interface graphique | API indépendante, 21 rubriques, traitements en arrière-plan |
| Assistant cartographique | Règles explicables, plan exécutable, propositions de maquettes et reprise de la carte |
| Scènes jusqu’à la carte | M07 : diagnostic recalculé, compléments STAC facultatifs, sélection et mosaïque automatiques, seuil appliqué, calibration, QA/SCL, multibande, extraction, composition et export ; résultat partiel explicite et diagnostic conservé en cas d’arrêt |
| NoData et bordures noires | Détection conservatrice, masquage des composantes périphériques, protection des classes et des sources |
| Traitements vectoriels | GeoPandas, superpositions, jointures, proximités et mesures ; M08 : audit détaillé, réparation avant/après, topologie et doublons avec journal/exclusions ; M09 : reprojection multicouche, choix géodésique et bilan des emprises ; M10 : schémas harmonisés, conversions contrôlées, fusion et provenance |
| Conversion et formats | M11/G06 : couche choisie, quatre formats vectoriels, GeoTIFF/COG, encodage, précision, compression, NoData, rapport exhaustif et publication atomique |
| Raster et indices | Algèbre extensible, 18 indices, statistiques, classification, terrain et convolution |
| Exécution | Calcul par blocs, lectures partagées, files bornées, échantillonnage borné, arbres parallèles |
| Mise en page | 24 maquettes d’origine, cadres, habillage, dimensions éditables, textes mesurés, étiquettes, aperçu et export |
| Persistance | État des outils, couches, résultats et maquettes ; JSON et archive CMZ ; historique des actions principales |
| Recettes, lots et révision | Variables, associations de couches, journaux, migration, empreintes et décision nominative |
| Chaînes de traitements | 52 opérateurs, dépendances vérifiées, produits secondaires et paramètres moteur transmis |
| Hydrologie, routage et STAC | Drainage D8, bassins, plus court chemin, recherche et téléchargement de scènes |
| Projets natifs | Inventaire QGS/QGZ et import des styles pris en charge ; passerelles QGIS/ArcPy nécessitant leurs environnements natifs et une validation propre à la version |
| Identité visuelle | Icône originale en couleur ; titre et contrôles en noir, blanc et gris |
| Distribution Python | Construction de wheel et d’archive source, métadonnées et documentation ; publication sur PyPI distincte de la mise à disposition des sources |


Le [guide des moteurs](EXECUTION.md) précise les opérations compatibles avec Dask et CUDA. Le [guide de visualisation](RESULTS_WORKSPACE.md) décrit les vues, comparaisons et limites de rendu.

L’[inventaire expert](EXPERT_PROCEDURES.md) distingue 123 procédures expertes :
17 disponibles dans leur périmètre documenté, 44 partielles et 62 absentes. Les
52 opérateurs enregistrés désignent des fonctions composables, pas 52 procédures
expertes achevées. Le [module M07](IMAGERY_AUTOMATIC.md) termine le raccordement
automatique de l’imagerie optique ; les autres procédures conservent leurs
conditions et leur état propre.

Le [rapport de validation](VALIDATION.md) distingue la suite locale, les essais sur données réelles, les notebooks, le paquet installé et les contrôles GitHub Actions. Le [guide M08](VECTOR_QUALITY.md) décrit les règles et les paramètres de qualité vectorielle.

Le [guide M09](VECTOR_REPROJECTION.md) décrit G04 : découverte des couches, opérations et grilles disponibles, décisions explicites, coordonnées et attributs préservés, publication atomique du lot et produits nommés pour les plans.

Le [guide M10](VECTOR_MERGE.md) décrit G05 : inspection des schémas,
correspondance des champs, conversions contrôlées, valeurs nulles et valeurs
par défaut explicites, concaténation avec provenance et fidélité des sorties
enregistrées.

Le [guide M11/G06](DATA_CONVERSION.md) décrit la livraison vérifiée et les deux opérateurs communs à Python, aux plans, au terminal et à la fenêtre.
