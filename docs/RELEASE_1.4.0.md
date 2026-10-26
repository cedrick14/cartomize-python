# Cartomize 1.4.0 — prétraitement optique automatique

Cette version complète **M07**, le parcours qui transforme une sélection de
scènes et une zone d’étude en produits optiques préparés, avec un contrôle
obligatoire de leur couverture utile. Elle part du commit
`243417da4cebafceaef58ec94db510529f910da9` de `cedrick14/cartomize-python`.

Le moteur est commun à Python/Jupyter, au terminal, à la fenêtre et aux chaînes
de traitements. Le registre compte désormais **44 opérateurs**, dont le nouvel
opérateur `imagery.preprocess`. Le [guide du module](IMAGERY_AUTOMATIC.md)
décrit les paramètres, les sorties et les contrats d’erreur.

## Ce que le module exécute

| Étape | Comportement livré |
|---|---|
| Lecture des entrées | Scènes locales ou STAC, rôles spectraux, calibration et masques de qualité/saturation reconnus ou associés explicitement. |
| Grille de calcul | Zone polygonale, projection et résolution validées ; grille conservée entre le diagnostic, la sélection et la production. |
| Couverture | Mesure des emprises, des données présentes et des pixels effectivement utilisables après masques. |
| Choix des scènes | Sélection d’une scène suffisante ou des scènes utiles à la mosaïque, avec vérification des bandes, unités, capteurs, niveaux et dates. |
| Complément facultatif | Recherche STAC dans la zone, téléchargement borné par nombre d’items et volume, puis mesure de l’apport réel de chaque candidate. |
| Production | Calibration, masquage, alignement, mosaïque si nécessaire et découpage ; multibande, bandes séparées et composition selon les options choisies. |
| Contrôle final | Couverture des produits confrontée au diagnostic ; arrêt si les sources ont changé pendant le traitement. |
| Traçabilité | `preprocessing.json`, diagnostic, cartes de couverture/lacunes, provenance des scènes et décisions de téléchargement. |

La recherche complémentaire nécessite un catalogue configuré et des URL
d’assets accessibles. Elle s’arrête au seuil demandé ou aux limites choisies.
Elle ne garantit pas l’existence d’images capables de combler toute lacune.
Les images d’un même pixel scientifique proviennent d’une même acquisition.

## Une couverture insuffisante reste visible

Le seuil vaut **100 %** par défaut. En dessous du seuil, le module interrompt la
production scientifique et conserve le diagnostic dans un dossier voisin.
Les chaînes et la production cartographique conservent aussi ces fichiers
après le nettoyage de leurs dossiers temporaires.

L’utilisateur peut abaisser le seuil ou autoriser explicitement un résultat
partiel. Le rapport continue alors d’indiquer `status="partial"` tant que la
couverture réelle est inférieure à 100 %. `threshold_met` indique séparément
si le seuil choisi est satisfait. Une couverture utile nulle n’autorise jamais
la fabrication d’une image scientifique vide présentée comme réussie.

Le diagnostic `audit_imagery()` adopte la même distinction :
`coverage_status="complete"` signifie désormais 100 % de couverture réelle.
Les traitements qui utilisaient ce champ pour vérifier un seuil inférieur
doivent lire `threshold_met`.

## Fenêtre, terminal et notebooks

Dans **Prétraitement multispectral**, le mode automatique est activé par défaut.
L’utilisateur choisit ses scènes, sa zone, les produits souhaités et sa politique
de couverture. Il peut associer les masques par scène et configurer un catalogue
complémentaire. Le mode expert conserve la préparation manuelle.

Les paramètres sont enregistrés dans les projets. Une couverture refusée
affiche les diagnostics disponibles ; un résultat accepté mais partiel reste
identifié comme tel. Les produits scientifiques sont transférables aux indices
et aux autres traitements.

```python
import cartomize as cm

produit = cm.preprocess_imagery(
    "donnees/scenes", "resultats/pretraitement_01",
    aoi="donnees/zone_etude.gpkg",
    band_order=["red", "nir"],
    coverage_threshold=100,
)
print(produit.report["status"])
print(produit.report["selected_scene_ids"])
print(produit.products[0]["multiband"])
```

```bash
cartomize preprocess-imagery donnees/scenes resultats/pretraitement_01 --aoi donnees/zone_etude.gpkg --bands red,nir
```

Le [cours 13](../tutorials/notebooks/13_diagnostic_automatique.ipynb) exécute le
même moteur dans un véritable noyau Jupyter : refus d’une couverture
insuffisante, mosaïque suffisante, NDVI et statistiques zonales.

## Corrections STAC et calibration vérifiées

L’import distingue les rôles des bandes Sentinel-2, conserve les masques SCL
et les masques Landsat `QA_PIXEL`/`QA_RADSAT`, et évite de traiter les aperçus
visuels comme des bandes scientifiques. Les métadonnées de calibration sont
lues dans les assets ou dans les métadonnées Sentinel associées lorsque nécessaire.

Un extrait public Sentinel-2 du **21 juillet 2026**, près de Mvouti dans le
Mayombe, a révélé un cas où le décalage radiométrique était déjà appliqué dans
les pixels des anciens COG Earth Search, alors que l’asset déclarait encore
un offset négatif. L’import tient compte du marqueur du fournisseur dans ce
profil précis et conserve l’offset déclaré et l’offset effectif dans ses notes.

La correction est vérifiée sur **32 768 valeurs réelles**, rouge et proche
infrarouge, comparées à un second téléchargement du même produit ESA dans la
collection C1. La différence des valeurs brutes est exactement de 1 000 dans
les deux bandes ; leurs réflectances calibrées concordent. Les fenêtres natives,
masques, références indépendantes, empreintes et liens sources sont inclus dans
le [jeu de non-régression](../tests/data/sentinel2_mvouti/README.md).

## Validation

La [fiche de validation](VALIDATION.md) et le
[rapport machine](VALIDATION_1.4.0.json) distinguent les résultats locaux et les
contrôles distants attachés au commit dans
[GitHub Actions](https://github.com/cedrick14/cartomize-python/actions).

- Suite complète locale initiale Linux/Python 3.12 : **722 tests réussis, 2 ignorés**
  pour les environnements matériels CUDA et natif QGIS indisponibles localement.
- Parcours Jupyter : **12 notebooks et 73 cellules exécutés**, avec un noyau
  neuf par cours. Le cours 00 accepte et signale sa couverture partielle ;
  les sept cellules du cours 13 exercent le refus et une mosaïque complète.
- Scène Sentinel réelle : **16 384 pixels utiles sur 16 384**, masque SCL,
  calibration et NDVI vérifiés ; même résultat depuis le travailleur de la fenêtre.
- Zone étendue de 20 m : **256 pixels manquants** détectés ; production refusée
  et carte des lacunes conservée.
- Fenêtre : parcours automatique, catalogue, refus et résultat partiel,
  restauration de projet et transfert entre traitements couverts par les tests.
  Formulaire inspecté à 1440 × 940 avec textes de 12 et 16 pixels.
  Les actions de la barre d’outils conservent leurs libellés après changement
  d’état, sans récupération d’un bouton interne pendant l’initialisation ;
  21 cas ciblés vérifient les actions et les ouvertures/fermetures de fenêtre.
- Paquet installé dans un environnement neuf : contrôle de couverture,
  mosaïque et valeurs physiques exactes, 20 pages graphiques, trois thèmes,
  calcul du NDVI, tampon vectoriel, exports PDF/PNG/SVG, projet réouvert et
  noyau de console vérifiés hors des sources.
- Wheel et archive source construites, contrôles Twine strict et vérification
  des modules, métadonnées, documentation et données de référence réussis.
- Réseau : réponses HTTP tronquées ou invalides testées sur un serveur local ;
  diagnostics et acquisitions utiles antérieures conservés, transferts suivants arrêtés.

Les essais sur de petits extraits vérifient les contrats et les valeurs. Ils
ne mesurent pas les performances sur des scènes entières ni la disponibilité
continue d’un fournisseur distant. L’authentification privée, les traitements
SAR et la correction atmosphérique de produits de niveau 1 ne font pas partie
du périmètre M07.

## Installation depuis les sources corrigées

Dans le dépôt à jour, avec l’environnement Python voulu activé :

```bash
git pull
python -m pip install -e ".[gui]"
python -m cartomize gui
```

Pour l’API seule, installer `python -m pip install -e .`. Pour les cours,
installer `python -m pip install -r tutorials/requirements.txt` puis ouvrir
`python -m jupyterlab tutorials/notebooks`. La publication sur PyPI constitue
une opération distincte de cette mise à jour du dépôt.

L’[inventaire expert](EXPERT_PROCEDURES.md) conserve les autres procédures et
leurs limites : la clôture de ce module n’implique pas l’implémentation de toutes
les extensions thématiques inventoriées.
