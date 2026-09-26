# Publication de Cartomize sur PyPI

Paquet : `cartomize` · Version publiée : `0.9.0a1` · Auteur : ONDON NKOUA Cédrick Belmich.

La version alpha [0.9.0a1](https://pypi.org/project/cartomize/0.9.0a1/) a été publiée le 26 septembre 2026 depuis le commit `8cac235ac786b700cbe126a0314fb406ed746077`. Le [workflow de publication](https://github.com/cedrick14/cartomize-python/actions/runs/36270662681) et la [matrice Linux/Windows](https://github.com/cedrick14/cartomize-python/actions/runs/36270662493) ont réussi : **340 tests et 2 ignorés** par configuration principale, **50 tests Windows Conda**, avec un vrai noyau Jupyter. Les 19 contrôles des vues et du prétraitement ont aussi réussi avant la suite complète de publication.

Les deux fichiers publics ont été téléchargés et comparés aux distributions validées :

| Fichier | Taille | SHA256 |
|---|---:|---|
| `cartomize-0.9.0a1-py3-none-any.whl` | 336 969 octets | `890d161bce5775096452af34512130ae2f51eda214cbcc57486da13b50870c4a` |
| `cartomize-0.9.0a1.tar.gz` | 407 013 octets | `ea82448bf8b2ce0da07412173f6b621d4879110c31300ab15aa15c6e3199689f` |

Cette version ajoute un [espace de travail intégré](RESULTS_WORKSPACE.md) : commandes et paramètres à gauche, résultats explorables à droite, comparaisons géographiques, métadonnées, légendes, tableaux, graphiques et sauvegarde des vues. Les lectures utilisent des travailleurs Python persistants ; les options `gui` et `notebook` sélectionnent la série Qt 6.9 validée. La fenêtre nécessite Python 3.11 à 3.13.

Le premier candidat n’a pas été publié : les contrôles Python 3.11 ont bloqué sa publication après un plantage des lecteurs vectoriels. Le commit indiqué ci-dessus contient la correction et a passé les contrôles complets. Les versions précédentes, dont [0.8.2a1](https://pypi.org/project/cartomize/0.8.2a1/), restent disponibles.

## Dépôt autonome

La bibliothèque Python utilise son propre dépôt, `cedrick14/cartomize-python`. Le plugin QGIS reste un projet distinct. Ne pas utiliser le dépôt du plugin comme éditeur de confiance du paquet Python.

Le code, `pyproject.toml`, les tests, la documentation et les workflows GitHub Actions sont à la racine de ce dépôt autonome.

## Éditeur de confiance PyPI

La première publication a utilisé les paramètres ci-dessous. L’éditeur est désormais associé au projet `cartomize` sur PyPI ; il n’est pas nécessaire d’ajouter un nouvel éditeur en attente pour les versions suivantes.

| Champ PyPI | Valeur |
|---|---|
| Nom du projet PyPI | `cartomize` |
| Propriétaire | `cedrick14` |
| Nom du dépôt | `cartomize-python` |
| Nom du flux de travail | `pypi-publish.yml` |
| Nom de l’environnement | `pypi` |

Saisir le nom du fichier sans le chemin `.github/workflows/`. Cette configuration autorise le workflow du dépôt autonome à publier le paquet. Elle ne réserve pas le nom. Au premier téléversement accepté, le compte qui a enregistré l’éditeur devient propriétaire du projet PyPI.

La connexion, la vérification de l’adresse et la double authentification sont gérées sur PyPI ; ne pas communiquer de secrets dans une conversation. Pour TestPyPI, créer une configuration distincte avec l’environnement `testpypi`.

## Workflow GitHub

Le fichier `.github/workflows/pypi-publish.yml` exécute les tests, construit les deux distributions, les contrôle avec Twine et `scripts/check_release.py`, puis les conserve comme artefact GitHub. Le contrôle Windows Conda est également obligatoire : il vérifie un import dans un processus neuf et l’ouverture depuis un vrai noyau Jupyter. Seul le travail de publication reçoit l’autorisation OIDC `id-token: write`.

Un push ordinaire sur `main` effectue la validation sans publier. La publication est autorisée uniquement dans `cedrick14/cartomize-python`, avec l’une des commandes de lancement suivantes :

- Exécution manuelle **Run workflow**, destination `pypi`, après configuration de l’éditeur de confiance.
- Tag `python-v0.9.0a1`, dont le numéro doit correspondre au `pyproject.toml`.
- Commit explicite sur `main` dont le message contient `[publish pypi]`.

Utiliser une seule méthode pour une version. La destination manuelle `check` ne publie rien ; `testpypi` utilise l’index de test. Le workflow doit être présent sur la branche par défaut pour proposer l’exécution manuelle.

La matrice `.github/workflows/python-library.yml` vérifie Linux/Windows et Python 3.11/3.12. Un travail séparé contrôle l’interopérabilité facultative avec QGIS ; le moteur principal reste autonome.

## Construction locale

Depuis la racine du dépôt, choisir un répertoire vide réservé à la publication :

```bash
python -m pip install build twine
python -m build --outdir pypi-dist
python -m twine check --strict pypi-dist/*
python scripts/check_release.py pypi-dist
```

Les deux fichiers attendus sont :

- `cartomize-0.9.0a1-py3-none-any.whl`
- `cartomize-0.9.0a1.tar.gz`

La description publique provient de `README_PYPI.md`. Les métadonnées de distribution doivent pointer vers le dépôt de la bibliothèque Python. Les références au dépôt historique sont conservées uniquement lorsqu’elles documentent la provenance ou des validations antérieures.

## Après publication

Vérifier la version, les deux fichiers et leurs SHA256 sur PyPI, puis installer depuis l’index public dans un environnement distinct :

```bash
python -m pip install "cartomize[gui]==0.9.0a1"
python -m cartomize gui
```

Le suffixe `a1` désigne une version alpha. La présence sur PyPI est une distribution publique, pas une certification scientifique. Les fichiers déjà publiés ne peuvent pas être remplacés sous le même nom.

Références officielles :

- https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
- https://docs.pypi.org/trusted-publishers/using-a-publisher/
- https://packaging.python.org/en/latest/tutorials/packaging-projects/
