# Interface graphique et extensions

## Lancer la fenêtre depuis un notebook local

Dans une cellule du notebook, avec le noyau Python de l’environnement choisi :

```python
%pip install "cartomize[notebook]==1.0.1"
```

Redémarrer le noyau, puis exécuter :

```python
import cartomize as cm
fenetre = cm.launch()
```

La fenêtre affiche **Version 1.0**. Le numéro 1.0.1 désigne la révision du paquet. Les services de notebooks distants n’ouvrent pas une fenêtre native sur l’ordinateur de l’utilisateur ; les cours API et leurs graphiques restent utilisables dans ces services.

## Parcours de travail

1. **Analyser les entrées.** Charger les rasters et couches vectorielles. Examiner SCR, résolutions, NoData, champs et classes. Consulter le cours 09 pour distinguer un fond périphérique et un zéro valide.
2. **Prétraiter les images.** Dans la rubrique multispectrale, vérifier les scènes et rôles des bandes, charger l’emprise puis sélectionner mosaïque, multibande, extraction de bandes et composition. Les paramètres correspondent au cours 02.
3. **Analyser les produits scientifiques.** Choisir les indices, l’algèbre ou la classification sur le multibande scientifique, avec une calibration et des références adaptées. Les sorties RVB étirées servent à l’affichage.
4. **Examiner les résultats.** Les sorties apparaissent dans les onglets du panneau droit. Utiliser zoom, déplacement, métadonnées et valeurs de pixels. Comparer les résultats avec des emprises liées et, pour les variables comparables, une échelle colorimétrique commune.
5. **Composer la carte.** Définir les rôles des couches, l’ordre, les classes, les étiquettes, les cadres et les éléments de page. Contrôler les unités, sources, dates et limites de l’interprétation.
6. **Automatiser et conserver.** Réutiliser la configuration dans un atlas, une recette ou un lot. Sauvegarder la session et les livrables.

Les filtres et comparaisons de la vue n’augmentent pas la résolution d’origine des données. Le zoom relit les pixels disponibles ; il ne crée pas de détail scientifique.

## Contrôle des vues

Après le cours 03, ouvrir le NDVI, le raster de seuil et le tableau zonal dans le catalogue des résultats. Vérifier successivement la légende, une valeur de pixel, le zoom sur une limite de classe et la comparaison NDVI/NDVI lissé. Après le cours 07, ouvrir les PDF et les pages d’atlas. Ces étapes sont des exercices manuels ; l’exécution des notebooks ne valide pas toutes les interactions de bureau.

## QGIS et ArcGIS Pro : modules facultatifs

Les cours ne nécessitent aucun de ces logiciels. Pour inventorier un projet QGIS local :

```python
inventaire = cm.inspect_qgis_project("projet.qgz")
```

Pour importer les éléments compatibles :

```python
resultat = cm.import_native_project("projet.qgz", "import_cartomize")
carte = cm.Map.load(resultat["map_file"])
```

Examiner les avertissements de transfert. Certaines propriétés et sous-couches demandent le moteur natif. Une équivalence visuelle avec le projet source n’est pas garantie par l’import autonome.

Pour une opération native, fournir l’interpréteur du moteur installé :

```python
rapport = cm.validate_native_runtime(
    "projet.qgz", "validation_native",
    python="chemin/vers/python_qgis", layout="Nom de la mise en page",
)
```

Les projets ArcGIS Pro nécessitent ArcPy et une installation licenciée. Les exemples natifs sont conditionnels et ne sont pas inclus dans la validation autonome du parcours.

## Dask et CUDA

`cm.execution_capabilities()` indique les dépendances accessibles. Les indices, l’algèbre et les réductions peuvent utiliser CUDA dans les configurations prises en charge. Les opérateurs documentés acceptent Dask. Tester l’égalité des sorties, le temps complet et la mémoire sur un jeu représentatif avant de choisir un moteur. Le cours 10 mesure les configurations CPU sur un petit jeu ; il ne constitue pas un benchmark GPU.
