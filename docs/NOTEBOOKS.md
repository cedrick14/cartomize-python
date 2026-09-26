# Utilisation dans Jupyter

## Installation

L’interface graphique de Cartomize 1.0 nécessite un noyau Python 3.11 à 3.13 installé sur un ordinateur disposant d’un bureau graphique.

```python
%pip install --upgrade "cartomize[notebook]==1.0.1"
```

Redémarrer le noyau après l’installation, puis exécuter :

```python
import cartomize as cm

fenetre = cm.launch()
```

Cartomize active la boucle d’événements Qt d’IPython. La cellule se termine et la fenêtre reste réactive. Les résultats s’affichent dans le [panneau de visualisation](RESULTS_WORKSPACE.md).

La fenêtre s’ouvre sur l’ordinateur qui exécute le noyau. Un notebook distant sans bureau graphique utilise les traitements par l’API Python ; il ne peut pas afficher la fenêtre dans le navigateur.

## Environnement Conda

Depuis l’invite de commandes Conda :

```bash
conda create -n cartomize python=3.12 pip
conda run -n cartomize python -m pip install "cartomize[notebook]==1.0.1"
conda run -n cartomize python -m ipykernel install --user --name cartomize --display-name "Python (Cartomize)"
```

Sélectionner le noyau **Python (Cartomize)** dans Jupyter.

## Mise à jour et diagnostic

Sous Windows, fermer Cartomize et arrêter les noyaux qui ont chargé Qt avant une mise à jour des dépendances graphiques. Les DLL chargées doivent être libérées pour permettre leur remplacement.

L’option `notebook` sélectionne Qt 6.9 et une version compatible de `typing_extensions`. Le démarrage initialise le parseur XML standard avant les bibliothèques géospatiales pour limiter les conflits de chargement Expat.

Pour identifier l’environnement du noyau :

```python
import sys
import cartomize as cm

print(sys.executable)
print(sys.version)
print(cm.__version__)
```

La [validation](VALIDATION.md) décrit les contrôles d’importation, de lancement et de réactivité de la fenêtre dans un noyau Jupyter.
