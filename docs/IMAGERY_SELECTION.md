# Prétraitement multispectral à options

La rubrique **Prétraitement multispectral** propose par défaut **Automatique : contrôler et préparer**. Elle contrôle la couverture et choisit la mosaïque avant de produire les sorties demandées. **Expert : choisir les opérations** conserve le parcours manuel. Ces modes fonctionnent avec les dépendances Python de Cartomize, sans QGIS ni ArcGIS Pro.

## Parcours dans la fenêtre

1. Cliquer sur **Sélectionner les bandes…**, ou choisir un répertoire puis **Analyser les bandes**. Les noms Landsat Collection 2 L2 et Sentinel-2 L2A sont reconnus avec leurs métadonnées d’origine. Les manifestes de scènes Cartomize sont également acceptés. Conserver les masques QA/SCL et les métadonnées Sentinel dans le produit d’origine.
2. Vérifier le tableau : scène, bande spectrale, fichier, numéro interne, échelle, décalage et date. Cocher les bandes à traiter. L’ordre du tableau détermine l’ordre des bandes dans le GeoTIFF scientifique.
3. Charger le shapefile de délimitation, ou une autre couche polygonale prise en charge. Cette zone est obligatoire en mode automatique. En mode expert, **Extraction par masque** s’active lors de sa sélection ; la décocher pour conserver l’emprise complète.
4. Choisir la **Couverture utile minimale (%)**, 100 % par défaut. **Accepter moins que le seuil** autorise explicitement un résultat partiel non vide. Choisir les produits souhaités selon le tableau ci-dessous.
5. Pour une composition colorée, choisir explicitement les bandes affectées aux **canaux rouge, vert et bleu**. Exemple : `red / green / blue` pour les couleurs naturelles ; `nir / red / green` pour une représentation de la végétation en fausses couleurs.
6. Choisir le répertoire de sortie, donner un **nouveau nom de dossier**, puis **Exécuter**. Le mode automatique recalcule le diagnostic, retient les scènes, applique le seuil et produit les sorties. Les produits apparaissent dans **Résultats du projet** et peuvent être transmis à la mise en page et aux autres traitements.

| Option | Résultat |
|---|---|
| Mode automatique | Le moteur choisit une scène suffisante ou les scènes contributrices et décide de leur mosaïque. |
| Mode expert, mosaïque cochée | Les scènes sont assemblées spatialement ; les mêmes bandes doivent être sélectionnées dans chaque scène. |
| Mode expert, mosaïque décochée | Chaque scène produit son propre dossier ; aucune fusion entre scènes. |
| Assemblage multibande coché | Le GeoTIFF scientifique `multibande.tif` est conservé. |
| Composition colorée cochée | Un fichier `composition_coloree.tif` distinct contient trois canaux de visualisation et un canal alpha de transparence. |
| Extraction des bandes cochée | Un GeoTIFF monobande est enregistré pour chaque bande, avec la même grille, les masques et les métadonnées. |

Au moins un produit doit être demandé : multibande, bandes séparées ou composition colorée. Si l’assemblage multibande n’est pas conservé, le fichier intermédiaire nécessaire aux autres produits est supprimé après traitement. En mode automatique, `preprocessing.json` décrit la décision, la couverture et les sorties ; il référence le rapport de préparation `imagery.json`. En mode expert, ce dernier est le manifeste principal.

**Compléter depuis un catalogue** permet de préciser l’adresse STAC, les
collections, la période et les limites de scènes et de téléchargement. Les
compléments ne sont recherchés que si la couverture manque. Sans scène locale,
renseigner aussi les bandes à obtenir, le SCR projeté et la résolution. Les
masques et métadonnées des produits pris en charge sont raccordés à la préparation.

## Vérifier la couverture avant de produire les images

Après sélection des bandes, de la zone et du répertoire de sortie, cliquer sur
**Diagnostiquer la couverture**. Le diagnostic calcule les emprises communes
aux bandes, les données présentes et les pixels utilisables après les masques
de qualité. Il affiche une recommandation et enregistre les cartes de couverture
et de lacunes dans un dossier distinct.

**Appliquer la sélection proposée** conserve les bandes cochées des scènes
retenues. Une modification des données ou des paramètres invalide la
recommandation précédente. **Exécuter** recalcule toujours le contrôle en mode
automatique ; le diagnostic préalable est facultatif. Une couverture sous le
seuil bloque la production, sauf acceptation explicite, et laisse un rapport
avec les cartes de lacunes accessibles. Voir le [diagnostic](IMAGERY_AUDIT.md)
et le [parcours automatique](IMAGERY_AUTOMATIC.md).

## Bandes personnalisées

Choisir **Bandes personnalisées : correspondance manuelle** pour des fichiers renommés ou un autre capteur. L’identité spectrale doit être renseignée explicitement. Les noms de bandes et les facteurs inscrits dans les fichiers sont repris lorsqu’ils existent ; les autres noms doivent être corrigés dans le tableau.

Les fichiers sont initialement rattachés à `scene_1`. Donner le même identifiant aux bandes d’une acquisition, et des identifiants différents aux acquisitions distinctes. Utiliser les mêmes noms spectraux entre scènes. Deux bandes portant le même nom dans la même scène sont refusées. Le numéro indique la bande à lire à l’intérieur du fichier source. Les facteurs de calibration proviennent des métadonnées du fichier, avec les valeurs usuelles 1 et 0 lorsque rien n’est déclaré ; renseigner les facteurs documentés du produit si nécessaire.

Le tableau **Masques associés aux scènes** permet d’indiquer un fichier de
qualité, son type et un éventuel masque de saturation pour chaque acquisition.
Les types comprennent QA_PIXEL Landsat, SCL Sentinel-2 et un masque personnalisé
dont les valeurs non nulles sont valides. Le choix de bandes personnalisées ne
désactive pas silencieusement le masquage : fournir un masque ou décocher
explicitement l’option si le produit en est dépourvu. Les manifestes et l’API
`Scene`/`Band` permettent les mêmes déclarations. Une mosaïque à dates différentes
ou inconnues exige l’option explicite correspondante.

## Valeurs et contrôles

La calibration et le masque de qualité précèdent le rééchantillonnage. La mosaïque, l’assemblage et le découpage utilisent une grille commune. Dans les recouvrements, une seule scène valide fournit toutes les bandes d’un pixel. La résolution par défaut est la plus grossière des bandes sélectionnées. Pour des entrées en coordonnées géographiques, renseigner un système projeté adapté.

Le multibande scientifique conserve les valeurs calibrées en `float32`, sans étirement de visualisation. La composition colorée est en `uint8` avec transparence ; elle ne doit pas remplacer le multibande pour les indices. Les valeurs zéro valides restent valides. L’étirement par défaut utilise les percentiles 2 et 98 estimés sur un aperçu borné.

Le traitement s’exécute en arrière-plan et peut être annulé. Une erreur ou une
annulation ne publie pas de dossier scientifique incomplet. Un refus pour
couverture insuffisante conserve son diagnostic dans un dossier distinct. Les
sources locales restent intactes. Les sélections, correspondances, cases et
canaux sont conservés dans la session et le projet portable.

## Utilisation Python

```python
import cartomize as cm

resultat = cm.preprocess_imagery(
    "donnees/scenes",
    "resultats/pretraitement",  # nouveau dossier
    aoi="limites.shp",
    coverage_threshold=100,
    multiband=True,
    separate_bands=True,
    composition=("nir", "red", "green"),
)
print(resultat.manifest)

# Extraction ultérieure d’un multibande existant :
fichiers = cm.split_bands("multibande.tif", "resultats/bandes_extraites")
```

`composition=None` désactive la composition colorée. Pour choisir manuellement
la mosaïque, utiliser `process_imagery(..., mosaic=True)` ou `mosaic=False` pour
conserver les acquisitions séparées. `prepare_imagery()` demeure disponible pour
une préparation directe. Avec une zone d’étude, `cartographic_workflow()` utilise
désormais le contrôle automatique avant de rendre les cartes.
