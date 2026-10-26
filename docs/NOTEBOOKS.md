# Utilisation dans Jupyter

Cartomize possède un seul moteur Python. Les cellules d’un notebook peuvent appeler ses fonctions sans interface graphique ; un notebook local peut aussi ouvrir la fenêtre de bureau si les dépendances graphiques sont installées. Les sources de ce dépôt correspondent à la version **1.4.0**.

## 1. Appeler les modules depuis les cellules

Cloner le dépôt, puis ouvrir un terminal dans son dossier avec Python 3.11 ou 3.12 :

```bash
git clone https://github.com/cedrick14/cartomize-python.git
cd cartomize-python
python -m venv .venv
```

Activer cet environnement avec `.venv\Scripts\Activate.ps1` sous PowerShell ou `source .venv/bin/activate` sous Linux/macOS, puis installer le parcours :

```bash
python -m pip install -r tutorials/requirements.txt
python -m ipykernel install --user --name cartomize --display-name "Python (Cartomize)"
python -m jupyterlab tutorials/notebooks
```

Le fichier de dépendances installe les **sources du dépôt courant** en mode modifiable, ainsi que Jupyter. Il doit être utilisé depuis la racine du dépôt. Sélectionner le noyau **Python (Cartomize)**. Aucun composant Qt n’est nécessaire à ces calculs.

Dans un notebook déjà ouvert, installer la copie locale dans l’environnement du noyau avec `%pip`, en adaptant le chemin :

```python
%pip install -e "C:/Projets/cartomize-python"
```

Redémarrer le noyau après installation ou modification de modules déjà importés. Les cellules utilisent ensuite directement les mêmes fonctions que l’interface :

```python
import cartomize as cm

try:
    images = cm.preprocess_imagery(
        "donnees/scenes", "resultats/pretraitement_01",
        aoi="donnees/zone_etude.gpkg",
        band_order=["red", "nir"], coverage_threshold=100,
    )
except cm.ImageryCoverageError as erreur:
    print(erreur.report["usable_percent"], erreur.diagnostic.gaps)
else:
    print(images.report["status"], images.report["selected_scene_ids"])
    print(images.products[0]["multiband"])
```

Les chemins désignent ici les données de l’étude ; le dossier de résultat doit
être nouveau. Le [module M07](IMAGERY_AUTOMATIC.md) contrôle la couverture et
effectue la sélection et la mosaïque dans le même appel. `audit_imagery()` reste
disponible pour un diagnostic seul.

Pour un exemple immédiatement exécutable sur des données générées, ouvrir le
[cours 13 — diagnostic et préparation automatiques](../tutorials/notebooks/13_diagnostic_automatique.ipynb).
Ses **sept cellules de code ont été exécutées avec Cartomize 1.4.0** : arrêt
pour couverture insuffisante, diagnostic conservé, mosaïque complète, NDVI et
statistiques zonales. Le [rapport du parcours](../tutorials/VALIDATION.md)
distingue cette exécution des validations des versions précédentes. Les
[règles de qualité, dates et couverture](IMAGERY_AUDIT.md) s’appliquent aussi
depuis les cellules.

## 2. Ouvrir la fenêtre depuis un notebook local

Le noyau doit fonctionner sur un ordinateur disposant d’un bureau graphique. Installer l’option `notebook` depuis la même copie des sources :

```python
%pip install -e "C:/Projets/cartomize-python[notebook]"
```

Redémarrer le noyau, puis exécuter :

```python
import cartomize as cm
fenetre = cm.launch()
```

Cartomize active l’intégration Qt d’IPython : la cellule se termine et la fenêtre reste réactive. Les résultats s’affichent dans le [panneau de visualisation](RESULTS_WORKSPACE.md). La fenêtre s’ouvre sur l’ordinateur qui exécute le noyau. Un notebook distant sans bureau graphique utilise l’API et les graphiques du parcours.

L’option `notebook` est donc utile pour cette intégration graphique ; elle n’est pas obligatoire pour appeler les modules de calcul depuis Jupyter.

## 3. Lancer la fenêtre depuis le terminal

Depuis la racine des sources, dans l’environnement activé :

```bash
python -m pip install -e ".[gui]"
python -m cartomize gui
```

La commande `cartomize-desktop` est une autre entrée vers la même fenêtre. Les traitements se choisissent ensuite dans les formulaires. L’[espace de travail](WORKBENCH.md) décrit les menus, le catalogue et les résultats.

## Environnement Conda

Depuis Anaconda Prompt, dans le dossier du dépôt :

```bash
conda create -n cartomize python=3.12 pip
conda run -n cartomize python -m pip install -r tutorials/requirements.txt
conda run -n cartomize python -m ipykernel install --user --name cartomize --display-name "Python (Cartomize)"
```

Ajouter `conda run -n cartomize python -m pip install -e ".[notebook]"` pour la fenêtre locale. Sélectionner ensuite le noyau **Python (Cartomize)**.

## Mise à jour et diagnostic

Une installation modifiable utilise les fichiers Python de cette copie GitHub. Après récupération de nouvelles sources, réinstaller les dépendances si elles ont changé, puis redémarrer le noyau. Sous Windows, fermer aussi les fenêtres qui ont chargé Qt avant la mise à jour de ses bibliothèques.

Pour identifier précisément l’environnement et le code chargés :

```python
import sys
import cartomize as cm

print(sys.executable)
print(cm.__version__)
print(cm.__file__)
```

L’installation d’une version publiée depuis PyPI reste possible ; sa version peut différer du dépôt. Les contrôles de [démarrage](../tests/test_startup.py) vérifient séparément l’API sans Qt, la GUI et le retour d’une cellule dans un véritable noyau Jupyter.
