# Espace de travail intégré : Cartomize 1.0

La disposition initiale place **l’explorateur et le catalogue à gauche, les vues au centre, les paramètres à droite et la console en bas**. Les cartes, couches, tableaux, graphiques et rapports s’ouvrent dans les onglets centraux. Chaque vue peut ensuite être détachée, ancrée sur un côté ou regroupée avec un autre panneau. Ce guide et le [guide de l’espace de travail dynamique](DYNAMIC_WORKSPACE.md) décrivent la construction **2026103001** de la version publique **1.0** ; l’état de distribution est suivi dans [PUBLICATION.md](PUBLICATION.md).

## Configurer et exécuter

1. Rechercher ou sélectionner un outil dans le catalogue de gauche.
2. Importer les données, cocher les opérations nécessaires et définir les paramètres à droite. Les formulaires défilent indépendamment des vues. **Aide** ouvre les explications repliées ; les unités, les choix, les erreurs et les diagnostics restent visibles.
3. Ouvrir **Paramètres de calcul et de sortie** lorsque ces réglages sont disponibles, puis lancer le traitement.
4. Consulter la progression. Les résultats précédents restent navigables pendant le calcul.
5. À la fin du traitement, le résultat s’ouvre dans une vue centrale. Les fichiers d’un traitement transactionnel sont affichés après sa réussite, pas pendant leur écriture.

Les aperçus et les contrôles cartographiques s’ouvrent aussi dans cet espace. **Détacher** permet d’afficher une vue dans une fenêtre indépendante tout en conservant ses réglages et son résultat.

## Placer et agrandir une vue

Ouvrir le menu de l’onglet pour **Détacher**, **Agrandir** ou **Fermer** la vue. Une fois détachée, faire glisser sa barre de titre : les guides indiquent les quatre côtés et le centre d’un panneau pour le regrouper en onglets. Le menu **Positionner** offre les mêmes choix de côté et **Grouper avec**. **Échap** annule le déplacement.

La commande **Réintégrer dans les vues** ramène le résultat aux onglets centraux. **Agrandir**, puis **Rétablir**, permet de consacrer temporairement l’espace à une vue. **F11** agrandit l’espace central ; **F11** ou **Échap** retrouve le placement précédent.

**Affichage** rouvre les panneaux de l’application. **Affichage > Rétablir la disposition** réintègre les vues détachées et remet les panneaux à leur place initiale. Les fichiers et leurs valeurs sont conservés.

## Explorer les résultats

| Produit | Vue et fonctions |
|---|---|
| GeoTIFF, JP2, VRT, IMG | Lecture de l’emprise visible, changement de bande, canaux RVB, palettes, interpolation d’affichage et identification des pixels |
| Classification | Couleurs et libellés enregistrés, légende catégorielle, rééchantillonnage au plus proche voisin et NoData transparents |
| NDVI et indices normalisés reconnus | Échelle d’affichage −1 à 1 ; les valeurs du raster restent intactes |
| GeoPackage, Shapefile, GeoJSON | Géométries de l’emprise visible, coordonnées, légende et table attributaire |
| Carte SVG | Rendu vectoriel à chaque niveau de zoom, avec les images incorporées à leur résolution d’export |
| Carte PDF | Pages sélectionnables et rendu de la portion visible à la résolution de la vue |
| PNG, JPEG et images prises en charge | Zoom à partir de l’image originale et déplacement |
| CSV et TSV | Tableau paginé, tri, filtre et graphiques intégrés |
| Rapports JSON | Tableaux structurés, matrices, propriétés et texte du rapport |

La molette contrôle le zoom ; le glissement déplace la vue. **Étendue** revient au cadrage initial. **1:1** règle une unité du document sur un pixel logique de l’écran ; pour un raster, il s’agit d’un pixel source. **Actualiser** relit le résultat. Cliquer sur un raster affiche la ligne, la colonne et les valeurs stockées des bandes sélectionnées ; les valeurs NoData sont identifiées explicitement.

**Style** donne accès aux bandes et aux palettes, y compris dans une comparaison. **Infos** affiche la légende et les métadonnées : système de coordonnées, résolution, dimensions, type numérique, unités, descriptions des bandes, facteurs radiométriques et pyramides disponibles. Une orientation et une échelle géodésique approximative au centre de la vue sont dessinées pour les couches géoréférencées. L’habillage définitif appartient à la carte exportée.

Les rasters scientifiques sont séparés de leur représentation. Le contraste automatique utilise des percentiles 2–98 % calculés sur un échantillon fixe par bande ; il ne change pas lors d’un simple déplacement. Le choix d’une palette, d’un contraste ou d’une interpolation ne réécrit jamais les pixels scientifiques. Les codes de classification restent discrets et la valeur zéro reste visible lorsqu’elle est valide.

## Comparer plusieurs résultats

Sélectionner **Comparer** après avoir chargé au moins deux cartes ou couches. Les deux sélecteurs permettent de choisir les résultats ; chaque vue conserve sa légende, ses bandes, ses métadonnées et sa navigation.

- **Synchroniser les emprises** relie le zoom et le déplacement par coordonnées géographiques, en transformant les emprises lorsque les SCR diffèrent. L’ajustement respecte les proportions de chaque vue ; selon leur format, une marge supplémentaire peut être visible. Ce n’est pas un rééchantillonnage analytique des fichiers.
- Pour un PDF, un SVG ou une image sans géoréférencement, la comparaison reste visuelle et la synchronisation géographique est désactivée.
- **Échelle colorimétrique commune** applique les mêmes limites et la même palette à deux rasters continus compatibles avec ce mode. Vérifier qu’ils représentent la même grandeur et les mêmes unités. Cette option ne calibre ni n’harmonise automatiquement des capteurs différents.

Plusieurs comparaisons et documents peuvent être ouverts. Huit vues actives sont conservées simultanément, en comptant les onglets centraux et les vues détachées. Les résultats des vues fermées restent dans le catalogue et peuvent être rouverts. Les fichiers ne sont pas supprimés.

## Tableaux, graphiques et rapports

Les CSV et tables attributaires sont lus par pages de 2 000 lignes. Le tri et le filtre concernent la page affichée. Les boutons **Précédent** et **Suivant** permettent de parcourir le fichier complet sans le charger intégralement en mémoire.

L’onglet **Graphique** propose barres, courbes, nuages de points et matrices. Choisir les colonnes et cliquer sur **Tracer**. Le graphique représente la page chargée ; il ne constitue pas une statistique automatique de tout un fichier paginé. Les barres sont limitées à 100 catégories et les matrices à 200 × 200 cellules. La barre Matplotlib intégrée permet de zoomer, déplacer et exporter le graphique.

Les rapports de classification conservent leurs matrices de confusion et leurs indicateurs. Les rapports associés à une couche sont ajoutés au catalogue. Les traitements produisant plusieurs fichiers enregistrent leurs produits déclarés ; les cartes exportées sont privilégiées pour l’affichage initial, puis les autres produits restent sélectionnables.

## Enregistrer un projet

Les sessions enregistrent les résultats, les vues ouvertes, les comparaisons, les bandes, les palettes et les emprises. Elles conservent aussi le placement des vues : onglet central ou panneau, côté d’ancrage, regroupement, fenêtre détachée et dimensions. Rouvrir le projet restaure ce placement avec les vues disponibles. Un projet portable emporte les fichiers référencés. Les anciennes sessions restent lisibles.

La disposition des panneaux de l’application est mémorisée localement entre les lancements, avec le thème et la taille du texte. Les thèmes **Clair**, **Sombre** et **Système** et les tailles de **11 à 16 pixels** restent disponibles.

Les aperçus et contrôles temporaires ne sont pas des exports persistants ; ils sont exclus des références de session pour ne pas créer de sources manquantes après fermeture. Exporter la carte pour la conserver. Les tableaux se rouvrent à leur première page.

## Rendu, précision et limites

Le rendu utilise deux travailleurs de lecture, un cache raster/PDF partagé de 64 Mio, des aperçus généraux et une relecture de la zone visible. Une requête de rendu est bornée à huit millions de pixels et 4 096 pixels par dimension. Les demandes devenues obsolètes après un changement de bande ou d’emprise n’écrasent pas la nouvelle vue. Les pyramides existantes peuvent accélérer les lectures raster ; la visionneuse ne modifie pas les fichiers pour en créer.

Le zoom retrouve les détails présents dans les pixels sources. Au-delà de leur résolution native, il agrandit les pixels sans augmenter la résolution des données. Les textes et traits vectoriels des cartes PDF/SVG sont rendus au niveau demandé ; leurs images incorporées restent limitées par la résolution choisie lors de l’export. L’aperçu cartographique utilise un SVG avec une résolution de 250 ppp pour les éléments rasterisés.

La vue vectorielle sert à explorer les géométries et les attributs ; elle ne reproduit pas tous les styles natifs d’un logiciel SIG. Elle limite chaque requête à 40 000 entités visibles et signale ce plafond ; zoomer réduit la zone interrogée. Les rapports JSON consultables sont limités à 16 Mio, avec un texte affiché jusqu’à 500 000 caractères. Les fichiers complets sont conservés.

La fluidité dépend du stockage, de la compression, des index spatiaux, des pyramides et du matériel. Les tests utilisent des données synthétiques. La mesure des performances et la validation thématique nécessitent des données représentatives de l’étude. La bibliothèque et la fenêtre restent indépendantes de QGIS et d’ArcGIS.

## Vérifications

Les lecteurs utilisent des threads Python persistants afin de conserver le contexte local des bibliothèques géospatiales entre deux tâches. Un test répète les lectures vectorielles sur ces travailleurs ; les tâches en attente d’un onglet fermé sont annulées. Les contrôles Python 3.11 et 3.12 sont exécutés sur Windows et Linux avant validation de la version.

Les options `gui` et `notebook` utilisent PySide6 6.9.3 à 6.9.x. Les tests vérifient les ouvertures et fermetures successives, y compris pendant une lecture. Les tâches en attente sont annulées et les réponses obsolètes sont ignorées. Après une mise à jour de Qt, fermer l’application et redémarrer le noyau pour charger les nouvelles bibliothèques.

Les tests couvrent les couleurs des classes et les NoData, les pixels noirs valides d’un RGBA, la lecture d’un détail au zoom, les valeurs originales au clic, les coordonnées liées entre SCR et résolutions différents, les échelles colorimétriques communes, les projets portables après suppression des sources originales, les tableaux paginés et graphiques, les matrices de confusion, le rendu PDF et image par région, l’affichage du résultat d’un calcul NDVI et le rejet des rendus devenus obsolètes. La suite Windows Conda inclut ces contrôles graphiques.

Références de conception : [Qt Graphics View](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsView.html), [lectures raster par fenêtres](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html), [rendu PDFium](https://pypdfium2.readthedocs.io/en/stable/python_api.html).
