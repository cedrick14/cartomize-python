# Espace de travail Cartomize 1.0

## Installation

Utiliser un environnement Python 3.11 ou 3.12 dédié à Cartomize. L’option `gui` installe PySide6 et le lecteur PDF nécessaires à l’interface.

Depuis PyPI :

```bash
python -m pip install "cartomize[gui]"
python -m cartomize gui
```

Depuis une archive source extraite :

```bash
python -m pip install ".[gui]"
python -m cartomize gui
```

Sous Ubuntu, les bibliothèques natives Qt doivent être présentes :

```bash
sudo apt-get install libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-image0 libxcb-render-util0
```

L’interface ne nécessite pas QGIS ni ArcGIS Pro. Une installation de QGIS ne remplace pas l’installation des dépendances Python de Cartomize.

## Organisation

La disposition initiale comprend **l’explorateur et le catalogue à gauche, les vues au centre, les paramètres à droite et la console en bas**. Chaque panneau garde son contenu lorsque son emplacement change.

**Explorateur de projet** : fichiers locaux, dossier de travail et importation. Le bouton Parent remonte d’un niveau. Un double-clic ouvre un fichier compatible. Une archive CMZ ou un fichier `.cartomize.json` ouvre le projet correspondant.

**Traitements** : catalogue de 21 pages, classées par catégories, avec une recherche sans distinction de casse ou d’accents. Le menu Traitements donne aussi accès à ces pages. Les opérations sont également disponibles dans les chaînes de traitement.

**Carte et résultats** : onglets raster, vectoriels, tableaux, graphiques, PDF et SVG. Les données chargées restent accessibles après fermeture de leur onglet.

**Paramètres** : formulaire du traitement sélectionné, moteur de calcul, sortie, Exécuter et Annuler. Les fichiers sources ne sont pas modifiés par un changement de thème ou de disposition.

**Console et résultats** : console Python, journaux, données chargées et environnement.

## Déplacer les panneaux et les vues

Faire glisser la **barre de titre** d’un panneau : les guides proposent les quatre côtés de l’espace de travail et le regroupement au centre d’un autre panneau. Relâcher sur la cible souhaitée. Le menu **Positionner** permet aussi de choisir un côté ou **Grouper avec** un autre panneau. **Échap** annule le déplacement en cours.

Les commandes de la barre de titre permettent de **Détacher**, **Agrandir**, **Rétablir** ou **Fermer** un panneau. Une vue de résultat détachée propose **Réintégrer dans les vues** pour revenir aux onglets centraux. Fermer une vue conserve son fichier et son entrée dans les données chargées.

**F11** agrandit l’espace central en masquant temporairement les panneaux ; **F11** ou **Échap** retrouve le placement précédent. Le menu **Affichage** rouvre les panneaux fermés. **Affichage > Rétablir la disposition** réintègre les vues détachées et restaure l’organisation initiale.

Le [guide des panneaux et vues mobiles](DYNAMIC_WORKSPACE.md) détaille ces gestes et leur enregistrement.

## Parcours de traitement

1. Importer les fichiers depuis l’explorateur ou la barre d’outils.
2. Sélectionner une donnée dans Données chargées, puis utiliser Transmettre au traitement avec une destination compatible.
3. Définir les paramètres et le fichier de sortie dans le panneau droit.
4. Exécuter le traitement. La progression et les journaux restent accessibles.
5. Ouvrir le résultat, le comparer ou le transmettre au traitement suivant.

La préparation multispectrale conserve son tableau de scènes et de bandes. La mise en page conserve la configuration des couches, les cadres, la légende, l’échelle et les formats d’export. Les instructions détaillées de chaque domaine restent disponibles dans [DESKTOP.md](DESKTOP.md) et [SIG_WORKFLOWS.md](SIG_WORKFLOWS.md).

### Aide dans les formulaires

Les descriptions des 21 pages et les explications longues sont repliées derrière **Aide**. Cliquer sur le bouton, ou l’atteindre avec **Tab** puis appuyer sur **Espace**, affiche le texte complet. Les valeurs saisies, unités, erreurs, diagnostics et avertissements opérationnels restent visibles dans le formulaire.

### Préparation automatique des images

Le [mode automatique](IMAGERY_AUTOMATIC.md) est sélectionné par défaut dans le
prétraitement multispectral. Sélectionner les bandes et la zone d’étude, fixer la couverture
utile minimale, puis exécuter : le moteur recalcule le diagnostic, choisit les
scènes, décide de la mosaïque et prépare les sorties. Un catalogue STAC facultatif
permet de chercher des compléments dans les limites configurées.

Le seuil vaut 100 % par défaut. Un manque de couverture conserve un diagnostic
et ses cartes de lacunes, sans publier les images prétraitées. **Accepter moins
que le seuil** autorise explicitement un résultat non vide partiel ; son état
reste affiché. Le mode **Expert : choisir les opérations** conserve les choix
manuels. Les plans et la production cartographique avec zone d’étude appliquent
le même contrôle avant les analyses et les cartes.

## Apparence

Le sélecteur Thème propose Clair, Sombre et Système. Le mode Système suit les changements signalés par le système d’exploitation. La taille du texte est réglable de 11 à 16 pixels. Ces préférences et la disposition des panneaux sont conservées entre les lancements.

Les palettes de l’interface et les couleurs des cartes sont indépendantes. Les légendes, valeurs raster et styles enregistrés ne sont pas modifiés par le mode sombre.

## Console Python

Écrire le code dans l’éditeur, puis choisir Exécuter le code ou utiliser Ctrl+Entrée. Le noyau est créé à la première exécution et conserve les variables entre les commandes.

```python
cm.__version__
len(data_paths)
```

`cm` désigne Cartomize et `data_paths` contient les chemins des fichiers actuellement chargés. Le noyau de la console est distinct de l’état interne de la fenêtre : il n’expose pas ses objets Qt.

Interrompre arrête le processus de console et son calcul. L’exécution suivante démarre un nouveau noyau ; les variables précédentes sont alors perdues. Un script ouvert dans l’éditeur ne s’exécute pas automatiquement. Exécuter uniquement du code de confiance : la console utilise les droits du compte utilisateur.

## Projets

Enregistrer le projet conserve les formulaires, les références aux fichiers, les résultats, les vues et la configuration de production. Le placement des vues de résultats est enregistré avec la session : onglet central ou panneau, côté, regroupement, position et taille d’une fenêtre détachée. Le placement des panneaux de l’application est également mémorisé localement entre les lancements.

Exporter le projet portable crée une archive CMZ contenant les données prévues par le format de projet. Les sessions de la disposition antérieure restent prises en charge.

L’ouverture et l’enregistrement d’un projet sont désactivés pendant un traitement. Nouveau projet demande confirmation avant de remplacer la session ; les fichiers déjà produits sont conservés sur disque.

## Raccourcis

| Raccourci | Action |
|---|---|
| Ctrl+N | Nouveau projet |
| Ctrl+O | Ouvrir un projet |
| Ctrl+S | Enregistrer |
| Ctrl+Maj+S | Exporter un projet portable |
| Ctrl+I | Importer des données |
| Ctrl+K | Rechercher un traitement |
| F5 | Exécuter le traitement |
| Maj+F5 | Interrompre le traitement |
| F11 | Agrandir l’espace central ou retrouver le placement précédent |
| Échap | Annuler un déplacement ou quitter le mode focus |
| Ctrl+Entrée | Exécuter le code de la console |

## Diagnostic

Aide > Diagnostic de l’environnement affiche l’interpréteur et les versions des paquets. Copier le diagnostic ou Enregistrer le diagnostic produit les informations à joindre à un signalement. Les données géospatiales de l’utilisateur ne sont pas incluses dans ce diagnostic.
