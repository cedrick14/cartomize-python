# Publication de Cartomize sur PyPI

Paquet : `cartomize` · Version publiée : `0.8.2a1` · Auteur : ONDON NKOUA Cédrick Belmich.

La version alpha [0.8.2a1](https://pypi.org/project/cartomize/0.8.2a1/) a été publiée le 26 septembre 2026 depuis le commit `e704db4dfdfe6b47f307d768a5f4f82d1eb6a8cc`. Le [workflow de publication](https://github.com/cedrick14/cartomize-python/actions/runs/36266212081) et la [matrice Linux/Windows](https://github.com/cedrick14/cartomize-python/actions/runs/36266211867) ont réussi : 324 tests et 2 ignorés par configuration principale, 34 tests Windows Conda. Les deux fichiers publics ont été téléchargés et leurs SHA256 comparés aux distributions validées :

| Fichier | SHA256 |
|---|---|
| `cartomize-0.8.2a1-py3-none-any.whl` | `e59bd6a5174bad81a637f390a1b067416539ae082c23c7bbd1ae95ce3064c4c7` |
| `cartomize-0.8.2a1.tar.gz` | `d1fbb44d7a81f6e1dea5a9e4216875fb18954a22ee2b67b1f9be8662128be6e4` |

Cette version conserve les bandes scientifiques dans les plans, relie les références de validation à la classification, réordonne les outils et contrôle la carte avant les exports automatisés. L’[audit SIG](SIG_WORKFLOWS.md) décrit les corrections et les limites. Les versions [0.8.1a1](https://pypi.org/project/cartomize/0.8.1a1/) et [0.8.1a2](https://pypi.org/project/cartomize/0.8.1a2/) restent disponibles ; 0.8.1a2 avait introduit les améliorations XML et notebooks.

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
- Tag `python-v0.8.2a1`, dont le numéro doit correspondre au `pyproject.toml`.
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

- `cartomize-0.8.2a1-py3-none-any.whl`
- `cartomize-0.8.2a1.tar.gz`

La description publique provient de `README_PYPI.md`. Les métadonnées de distribution doivent pointer vers le dépôt de la bibliothèque Python. Les références au dépôt historique sont conservées uniquement lorsqu’elles documentent la provenance ou des validations antérieures.

## Après publication

Vérifier la version, les deux fichiers et leurs SHA256 sur PyPI, puis installer depuis l’index public dans un environnement distinct :

```bash
python -m pip install "cartomize[gui]==0.8.2a1"
python -m cartomize gui
```

Le suffixe `a1` désigne une version alpha. La présence sur PyPI est une distribution publique, pas une certification scientifique. Les fichiers déjà publiés ne peuvent pas être remplacés sous le même nom.

Références officielles :

- https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
- https://docs.pypi.org/trusted-publishers/using-a-publisher/
- https://packaging.python.org/en/latest/tutorials/packaging-projects/
