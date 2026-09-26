# Cartomize dans un notebook local

Cartomize nécessite Python 3.11 ou plus récent. Dans un notebook utilisant ce Python, installer les dépendances de la fenêtre et du noyau :

```python
%pip install --upgrade "cartomize[notebook]==0.8.1a2"
```

Après installation ou mise à jour, redémarrer le noyau. Ouvrir ensuite la fenêtre :

```python
import cartomize as cm
fenetre = cm.launch()
```

La fenêtre s'ouvre sur l'ordinateur qui exécute le noyau. Cartomize active l'intégration Qt d'IPython ; la cellule se termine et la fenêtre reste réactive. Aucune commande `%gui` supplémentaire n'est requise. Un noyau distant sans bureau graphique ne peut pas afficher cette fenêtre sur l'ordinateur du navigateur ; les traitements par l'API restent utilisables.

## Démarrage sous Windows avec Conda

La version 0.8.1a2 initialise le module XML standard avant le chargement de GeoPandas et Rasterio. Cette précaution vise les conflits de DLL Expat lors du chargement des bibliothèques SIG. Elle ne remplace pas la réparation d'un environnement où `from xml.parsers import expat` échoue déjà lorsqu'il est exécuté seul.

L'option d'installation `notebook` fournit également une version de `typing_extensions` compatible avec le paramètre `extra_items` utilisé par les versions récentes de Jupyter Client.

## Validation

Le commit `530154823f7ad9f5d78438c7d69003037068ea47` a passé les contrôles suivants :

- Windows, Conda du canal defaults, Python 3.12 et Expat 2.8.5 : import dans un interpréteur neuf, lecture et écriture raster/vectorielle, export de carte et ouverture de la fenêtre.
- Vrai noyau Jupyter : retour de `cm.launch()` et traitement d'un événement Qt après la fin de la cellule.
- Suite de tests sur Linux et Windows avec Python 3.11 et 3.12.

Le [contrôle Windows Conda](https://github.com/cedrick14/cartomize-python/actions/runs/36259248384) a également réussi avec la version 0.8.1a1 dans cet environnement neuf. Le conflit signalé sur un poste existant n'a donc pas été reproduit à l'identique ; sa résolution sur ce poste reste à vérifier après mise à jour et redémarrage du noyau. Les contrôles automatiques utilisent Qt en mode hors écran et ne valident pas l'affichage sur chaque configuration de bureau Windows.
