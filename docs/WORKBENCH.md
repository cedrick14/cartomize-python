# Espace de travail Cartomize 1.4.0

## Installation

Utiliser un environnement Python 3.11 ou 3.12 dédié à Cartomize. Le paquet `gui` installe PySide6 et le lecteur PDF nécessaires à l’interface.

Depuis une archive source extraite :

```bash
python -m pip install ".[gui]"
python -m cartomize gui
```

Depuis le paquet wheel de la version :

```bash
python -m pip install "./cartomize-1.4.0-py3-none-any.whl[gui]"
python -m cartomize gui
```

Sous Ubuntu, les bibliothèques natives Qt doivent être présentes :

```bash
sudo apt-get install libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-image0 libxcb-render-util0
```

L’interface ne nécessite pas QGIS ni ArcGIS Pro. Une installation de QGIS ne remplace pas l’installation des dépendances Python de Cartomize.

## Organisation

**Explorateur de projet** : fichiers locaux, dossier de travail et importation. Le bouton Parent remonte d’un niveau. Un double-clic ouvre un fichier compatible. Une archive CMZ ou un fichier `.cartomize.json` ouvre le projet correspondant.

**Traitements** : catalogue par catégories et recherche sans distinction de casse ou d’accents. Le menu Traitements donne aussi accès à toutes les pages. Le registre commun comprend 44 opérateurs utilisables dans les chaînes.

**Carte et résultats** : onglets raster, vectoriels, tableaux, graphiques, PDF et SVG. Les données chargées restent accessibles après fermeture de leur onglet.

**Paramètres** : formulaire du traitement sélectionné, moteur de calcul, sortie, Exécuter et Annuler. Les fichiers sources ne sont pas modifiés par un changement de thème ou de disposition.

**Console et résultats** : console Python, journaux, données chargées et environnement. Les panneaux peuvent être déplacés, détachés et réaffichés depuis Affichage. Rétablir la disposition restaure l’organisation initiale.

## Parcours de traitement

1. Importer les fichiers depuis l’explorateur ou la barre d’outils.
2. Sélectionner une donnée dans Données chargées, puis utiliser Transmettre au traitement avec une destination compatible.
3. Définir les paramètres et le fichier de sortie dans le panneau droit.
4. Exécuter le traitement. La progression et les journaux restent accessibles.
5. Ouvrir le résultat, le comparer ou le transmettre au traitement suivant.

La préparation multispectrale conserve son tableau de scènes et de bandes. La mise en page conserve la configuration des couches, les cadres, la légende, l’échelle et les formats d’export. Les instructions détaillées de chaque domaine restent disponibles dans [DESKTOP.md](DESKTOP.md) et [SIG_WORKFLOWS.md](SIG_WORKFLOWS.md).

### Préparation automatique des images

Le [module M07](IMAGERY_AUTOMATIC.md) est le mode par défaut du prétraitement
multispectral. Sélectionner les bandes et la zone d’étude, fixer la couverture
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

Enregistrer le projet conserve les formulaires, les références aux fichiers, les résultats, les vues et la configuration de production. Exporter le projet portable crée une archive CMZ contenant les données prévues par le format de projet. Les sessions de la disposition antérieure restent prises en charge.

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
| Ctrl+Entrée | Exécuter le code de la console |

## Diagnostic

Aide > Diagnostic de l’environnement affiche l’interpréteur et les versions des paquets. Copier le diagnostic ou Enregistrer le diagnostic produit les informations à joindre à un signalement. Les données géospatiales de l’utilisateur ne sont pas incluses dans ce diagnostic.
