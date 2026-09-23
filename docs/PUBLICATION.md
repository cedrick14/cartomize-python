# Publication de Cartomize sur PyPI

Paquet : `cartomize` · Version préparée : `0.8.1a1` · Auteur : ONDON NKOUA Cédrick Belmich.

## Dépôt autonome

La bibliothèque Python utilise son propre dépôt, `cedrick14/cartomize-python`. Le plugin QGIS reste un projet distinct. Ne pas utiliser le dépôt du plugin comme éditeur de confiance du paquet Python.

Le code, `pyproject.toml`, les tests, la documentation et les workflows GitHub Actions sont à la racine de ce dépôt autonome. L’acceptation de la première publication PyPI doit être vérifiée avant de présenter les liens d’installation comme disponibles.

## Éditeur de confiance PyPI

Dans le compte PyPI du fondateur, ouvrir **Édition / Publishing**, puis **GitHub** sous **Ajouter un nouvel éditeur en attente** :

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

Le fichier `.github/workflows/pypi-publish.yml` exécute les tests, construit les deux distributions, les contrôle avec Twine et `scripts/check_release.py`, puis les conserve comme artefact GitHub. Seul le travail de publication reçoit l’autorisation OIDC `id-token: write`.

Un push ordinaire sur `main` effectue la validation sans publier. La publication est autorisée uniquement dans `cedrick14/cartomize-python`, avec l’une des commandes de lancement suivantes :

- Exécution manuelle **Run workflow**, destination `pypi`, après configuration de l’éditeur de confiance.
- Tag `python-v0.8.1a1`, dont le numéro doit correspondre au `pyproject.toml`.
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

- `cartomize-0.8.1a1-py3-none-any.whl`
- `cartomize-0.8.1a1.tar.gz`

La description publique provient de `README_PYPI.md`. Les métadonnées de distribution doivent pointer vers le dépôt de la bibliothèque Python. Les références au dépôt historique sont conservées uniquement lorsqu’elles documentent la provenance ou des validations antérieures.

## Après publication

Vérifier la version, les deux fichiers et leurs SHA256 sur PyPI, puis installer depuis l’index public dans un environnement distinct :

```bash
python -m pip install "cartomize[gui]==0.8.1a1"
python -m cartomize gui
```

Le suffixe `a1` désigne une version alpha. La présence sur PyPI est une distribution publique, pas une certification scientifique. Les fichiers déjà publiés ne peuvent pas être remplacés sous le même nom.

Références officielles :

- https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
- https://docs.pypi.org/trusted-publishers/using-a-publisher/
- https://packaging.python.org/en/latest/tutorials/packaging-projects/
