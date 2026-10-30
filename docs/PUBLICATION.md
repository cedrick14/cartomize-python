# Distribution de l’édition consolidée 1.0

**État au 30 octobre 2026 : publiée sur PyPI et disponible sur GitHub.** L’édition consolidée **Cartomize 1.0**, construction **20261030**, réunit les modules terminés jusqu’à G12. La release historique `1.0` a été supprimée, puis remplacée sur PyPI par la roue `cartomize-1.0-20261030-py3-none-any.whl`. Les sources complètes et le dossier de présentation sont conservés dans la [livraison GitHub](https://github.com/cedrick14/cartomize-python/releases/tag/cartomize-1.0-20261030). Les preuves de publication et le suivi de l’installation figurent plus bas.

Le paquet reste `cartomize`. Sa version publique, la version des métadonnées et `cartomize.__version__` sont toutes **`1.0`**. Le numéro de construction de la roue, **`20261030`**, distingue les nouveaux fichiers des distributions historiques sans changer la version publique.

Voir la [note de l’édition consolidée](RELEASE_1.0.md), le [guide de démonstration](DEMONSTRATION_1.0.md) et le [guide d’utilisation](WORKBENCH.md).

## Fichiers de cette livraison

| Fichier | Destination et usage |
|---|---|
| `cartomize-1.0-20261030-py3-none-any.whl` | Installation de la bibliothèque, des commandes et, avec l’option `gui`, de l’interface ; fichier publié sur PyPI pour cette édition `1.0`. |
| `cartomize-1.0.tar.gz` | Sources complètes conservées dans la livraison GitHub ; cette archive n’est pas publiée sur PyPI. |
| `cartomize-1.0-presentation.zip` | Dossier portable de présentation : roue, sources, guides, notebook et données pédagogiques synthétiques. |

La roue contient `Version: 1.0` dans `METADATA` et `Build: 20261030` dans `WHEEL`. Le numéro de construction est défini dans `setup.cfg`. La taille et l’empreinte SHA-256 du fichier publié sur PyPI sont consignées dans la section des preuves ; le dossier de présentation conserve également les empreintes des archives qu’il contient.

La bibliothèque nécessite Python **3.11 ou ultérieur**. Python **3.11 ou 3.12** est recommandé pour l’interface et correspond aux configurations de validation du dépôt. Les options `gui` et `notebook` utilisent Qt 6.9. QGIS et ArcGIS Pro restent facultatifs ; seules leurs passerelles natives les nécessitent.

## Construction et validation

Depuis la racine du dépôt, avec un dossier `pypi-dist` réservé à cette construction :

```bash
python -m pip install -e ".[dev,notebook,distributed]"
python -m pytest
python -m build --outdir pypi-dist
python -m twine check --strict pypi-dist/*
python scripts/check_release.py pypi-dist
python scripts/verify_installed_release.py --wheel pypi-dist/cartomize-1.0-20261030-py3-none-any.whl --output reports/installed-1.0.json
```

Le contrôle de livraison doit vérifier les deux archives, les modules attendus, les versions et le numéro de construction. L’installation isolée doit être exécutée hors du code source. Les résultats Linux, Windows, interface, notebooks et traitements sont associés au commit et aux fichiers vérifiés ; une réussite ancienne ne remplace pas la validation de ces archives.

Pour cette édition, **les deux archives ont été validées et seule la roue avec le numéro de construction `20261030` a été envoyée à PyPI**. Le dossier transmis à l’éditeur de confiance est distinct de celui contenant l’ensemble de la livraison.

La CI conserve les deux archives dans l’artefact `cartomize-complete-distributions`. Le script `scripts/stage_pypi_upload.py` sélectionne la nouvelle roue seule pour la version `1.0` ; l’artefact `cartomize-pypi-distributions` contient les fichiers destinés à l’envoi. La présence de ces artefacts ne signifie pas que le job de publication a été exécuté.

## Livraison téléchargeable sur GitHub

La [livraison `cartomize-1.0-20261030`](https://github.com/cedrick14/cartomize-python/releases/tag/cartomize-1.0-20261030) est publiée et contient les trois fichiers décrits plus haut.

Le script suivant réunit les deux archives vérifiées, les guides, le notebook 22
et des scènes synthétiques dans un dossier portable. Il refuse d’écraser un ZIP
existant et enregistre les empreintes des archives.

```bash
python scripts/build_demo_delivery.py --dist-dir pypi-dist --output delivery-dist/cartomize-1.0-presentation.zip
```

Après les contrôles de construction et Windows Conda, le workflow peut publier
la livraison complète sous le tag GitHub `cartomize-1.0-20261030`. Cette action
demande un commit sur `main` contenant `[publish delivery]`, ou l’option manuelle
`delivery` sur `main`. Elle est indépendante de l’envoi PyPI ; le tag ne correspond
pas au déclencheur `python-v*`. La création de la release GitHub ne modifie donc
pas les anciennes releases de PyPI ou de piwheels.

La release comporte le wheel, l’archive source et le paquet de présentation en
fichiers téléchargeables. Les données incluses sont simulées, avec leurs noms de
produits et leur calibration de démonstration ; elles ne sont pas présentées
comme des observations USGS réelles.

## Installation depuis PyPI

Dans un environnement Python activé, installer les composants de Jupyter et de l’interface locale :

```bash
python -m pip install --index-url https://pypi.org/simple "cartomize[notebook]==1.0"
python -m cartomize gui
```

Pour l’interface seule, utiliser `cartomize[gui]==1.0` ; pour l’API Python seule, `cartomize==1.0`. La commande `python -m jupyter lab` ouvre Jupyter. Les notebooks, les données synthétiques et les sources complètes sont disponibles dans la livraison GitHub. L’ouverture d’une fenêtre native demande un environnement graphique sur la machine qui exécute Python.

Si une ancienne version `1.0` est déjà installée, demander explicitement sa réinstallation :

```bash
python -m pip install --index-url https://pypi.org/simple --force-reinstall --no-cache-dir "cartomize[notebook]==1.0"
```

Vérifier ensuite la version et la construction :

```bash
python -c "import cartomize; from importlib.metadata import distribution; d = distribution('cartomize'); print(cartomize.__version__); print(d.version); print(d.read_text('WHEEL'))"
```

Les deux versions doivent être `1.0` et le fichier `WHEEL` doit indiquer `Build: 20261030`. Le seul affichage de `1.0` ne distingue pas cette livraison de l’ancienne distribution.

Le [guide de démonstration](DEMONSTRATION_1.0.md) décrit également l’installation du wheel téléchargé depuis GitHub.

## Publication PyPI confirmée sous le numéro exact 1.0

### Situation historique vérifiée

La release PyPI historique `1.0`, publiée le **26 septembre 2026**, utilisait les fichiers `cartomize-1.0-py3-none-any.whl` et `cartomize-1.0.tar.gz`. Elle a été retirée le 30 octobre 2026. La [page PyPI `1.0`](https://pypi.org/project/cartomize/1.0/#files) et ses [métadonnées JSON](https://pypi.org/pypi/cartomize/1.0/json) décrivent désormais la release recréée.

PyPI interdit de réutiliser un nom de fichier, même après suppression. Il refuse aussi l’ajout de fichiers aux releases âgées de plus de **14 jours**. Au 30 octobre 2026, la release historique `1.0` dépassait ce délai : elle a donc été supprimée et recréée avec un nouveau nom de roue.

### Remplacement par une release recréée

Le remplacement a été réalisé en conservant le projet `cartomize` :

1. Les archives ont été validées et la livraison complète a été publiée sur GitHub.
2. La **release historique `1.0`** a été supprimée. Cette opération a retiré les anciens fichiers sans libérer leurs noms.
3. Seule la roue `cartomize-1.0-20261030-py3-none-any.whl` a été publiée sur PyPI, le **30 octobre 2026 à 21 h 43 à Kinshasa** (**20 h 43 UTC**). Son nom inédit a permis de recréer une release dont la version demeure exactement `1.0`.

La suppression et la publication sont séparées : le remplacement n’est pas atomique. Les anciens noms restent définitivement réservés, et les fichiers de verrouillage qui utilisent les anciennes empreintes ne sont pas transférés au nouveau fichier.

Le job de publication et les métadonnées du fichier PyPI confirment cette publication. Le contrôle de l’installation depuis l’index est suivi séparément dans la section des preuves.

### Archive source distribuée hors de PyPI

Pour un sdist de version exacte `1.0`, la validation actuelle de Warehouse exige `cartomize-1.0.tar.gz`. Ce nom a déjà été utilisé. La variante `cartomize-1.0.zip` et l’ajout d’un numéro de construction au nom du sdist ne satisfont pas cette validation.

Cette édition `1.0` est distribuée sur PyPI **par roue seule**. Les sources complètes restent disponibles dans la livraison GitHub. Une commande imposant une construction de `cartomize` depuis les sources de PyPI, par exemple avec `--no-binary cartomize`, ne peut pas utiliser cette distribution.

### Utilisateurs d’anciennes installations

Un numéro de construction ne crée pas une version supérieure à `1.0`. Un simple `pip install --upgrade cartomize` ne garantit donc pas le remplacement d’une ancienne installation `1.0`. Utiliser la réinstallation explicite depuis PyPI avec `--force-reinstall --no-cache-dir` indiquée plus haut, puis contrôler le champ `Build`.

Les anciennes éditions **`1.0.1`, `0.9.0a1`, `0.8.2a1`, `0.8.1a2` et `0.8.1a1`** ont été retirées. Le 30 octobre 2026 à **21 h 45 min 49 s à Kinshasa** (**20 h 45 min 49 s UTC**), les [métadonnées globales de PyPI](https://pypi.org/pypi/cartomize/json), au numéro de série `42985509`, n’indiquent plus qu’une seule release, **`1.0`**, contenant la nouvelle roue ; la version courante y est également `1.0`. Le contrôle de résolution depuis l’index confirme ensuite que `pip` sélectionne cette roue `1.0` pour `cartomize`, même sans numéro imposé.

## Conséquence pour piwheels

Piwheels suit les événements de PyPI. Sa [FAQ officielle](https://www.piwheels.org/faq.html) indique qu’une suppression de version sur PyPI entraîne aussi son retrait de piwheels, avec suppression des fichiers correspondants. Cette propagation peut demander un délai et doit être vérifiée.

Au 30 octobre 2026 à **21 h 49 min 30 s à Kinshasa** (**20 h 49 min 30 s UTC**), les [métadonnées publiques de piwheels](https://www.piwheels.org/project/cartomize/json/) contiennent encore les six éditions historiques. Leur retrait sur PyPI n’y est donc pas encore reflété.

Une nouvelle version ne contenant qu’une roue est classée `binary only` par le collecteur piwheels ; sa reconstruction automatique est désactivée. La nouvelle archive source `1.0` ne peut pas être envoyée à PyPI : **la publication de cette roue `1.0` ne déclenche donc pas de reconstruction automatique sur piwheels**. Publier l’archive source sur GitHub ne déclenche pas cette reconstruction normale.

L’installation de la roue vérifiée ou depuis PyPI reste possible sur une plateforme disposant des dépendances requises. Le suffixe `py3-none-any` concerne la roue Cartomize ; il ne garantit pas à lui seul la disponibilité de ses dépendances sur chaque machine. Ne pas annoncer une nouvelle distribution piwheels sans vérifier les fichiers effectivement disponibles.

## Intégration continue et preuves de publication

Le workflow `.github/workflows/pypi-publish.yml` valide la construction et Windows Conda. Les autres workflows couvrent notamment Linux et Windows, les notebooks, l’interface et les projets réels. La publication utilise un éditeur de confiance PyPI avec l’environnement GitHub `pypi`.

Les déclencheurs sont un tag `python-v*`, un commit contenant `[publish pypi]`, ou une exécution manuelle dont la destination est `pypi`. Un lancement de validation seule ou un job de publication marqué `skipped` ne constitue pas une publication. Le tag doit correspondre à la version du paquet.

### Preuves de la publication du 30 octobre 2026

| Élément | Preuve |
|---|---|
| Commit publié | [`b65c2ffd9a2992a0279a7053fe8480c618e832dd`](https://github.com/cedrick14/cartomize-python/commit/b65c2ffd9a2992a0279a7053fe8480c618e832dd) |
| Arbre Git du code publié | `cd15154969856c9b560b521aafb53eb7758e562d` |
| Exécution GitHub Actions | [41124811288](https://github.com/cedrick14/cartomize-python/actions/runs/41124811288) |
| Construction | [Job 124300338865](https://github.com/cedrick14/cartomize-python/actions/runs/41124811288/job/124300338865) : `success` |
| Windows Conda | [Job 124300339826](https://github.com/cedrick14/cartomize-python/actions/runs/41124811288/job/124300339826) : `success` |
| Publication PyPI | [Job 124302714006](https://github.com/cedrick14/cartomize-python/actions/runs/41124811288/job/124302714006) : `success` |
| Fichier PyPI | [cartomize-1.0-20261030-py3-none-any.whl](https://files.pythonhosted.org/packages/09/a0/7710d24be96bc28ef418cb06669b28e5946202863e6ffcf75f6cd8f89774/cartomize-1.0-20261030-py3-none-any.whl) |
| Taille | **539 775 octets** |
| SHA-256 | `895dd297b0c2e6cb9c5949311eed18e48f9929a3162b86809705495e4cbc2cb8` |
| Téléversement PyPI | `2026-10-30T20:43:55.572529Z`, selon les [métadonnées PyPI `1.0`](https://pypi.org/pypi/cartomize/1.0/json) |
| Résolution depuis l’index | Simulation `pip` réussie sans numéro imposé : version `1.0`, URL et SHA-256 identiques au fichier ci-dessus, `is_direct=false`. |

Le contrôle de résolution a utilisé la commande suivante :

```bash
python -m pip --isolated install --dry-run --ignore-installed --no-deps --no-cache-dir --index-url https://pypi.org/simple cartomize
```

**Installation du fichier publié sur PyPI dans un environnement neuf : vérifiée.** Le wheel a été téléchargé depuis l’URL PyPI ci-dessus, son SHA-256 a été recalculé, puis son installation a été effectuée sous **Python 3.12.14**, avec l’empreinte imposée, sans paquets système et hors du dépôt source. La résolution depuis l’index et l’installation du fichier téléchargé sont ainsi vérifiées séparément.

- Les versions des métadonnées et du module importé sont `1.0` ; le fichier installé indique `Build: 20261030`.
- Les **102 fichiers Python** du wheel sont identiques octet pour octet aux **102 fichiers Python** des sources validées ; aucun fichier ne manque.
- Les modules `vector_rings` et `desktop_rings` sont importés depuis le nouvel environnement. Sur un carré de 10 m de côté, les anneaux de 1 m et 2 m avec `quad_segs=1` ont les surfaces attendues de **42 m²** et **46 m²**, soit **88 m²** au total et aucun chevauchement. L’inclusion du polygone d’entrée porte le premier anneau à **142 m²**.
- Les composants des options `gui`, `notebook` et `distributed` sont installés et importés : PySide6, pypdfium2, ipykernel, JupyterLab et Dask/distributed.
- `pip check` ne signale aucune dépendance incohérente ; `python -I -m cartomize --help` réussit ; `python -I -m jupyterlab --version` retourne **4.6.5**.

Ce contrôle cible le fichier réellement publié. Les suites complètes de traitement, d’interface et de notebooks restent rattachées aux exécutions GitHub validées ; elles n’ont pas été relancées dans cet environnement d’installation.

## Références des règles de distribution

- [Format officiel des roues : version et construction](https://packaging.python.org/en/latest/specifications/binary-distribution-format/) ; [source de la spécification](https://github.com/pypa/packaging.python.org/blob/main/source/specifications/binary-distribution-format.rst).
- [PyPI : noms de fichiers déjà utilisés](https://docs.pypi.org/publishing/troubleshooting/) ; [source de la documentation](https://github.com/pypi/warehouse/blob/main/docs/user/publishing/troubleshooting.md).
- [PyPI : annonce du 22 juillet 2026 sur le délai de 14 jours](https://github.com/pypi/warehouse/blob/main/docs/blog/posts/2026-07-22-releases-now-reject-new-files-after-14-days.md).
- [Warehouse : validation des fichiers et du nom du sdist](https://github.com/pypi/warehouse/blob/main/warehouse/forklift/legacy.py), [constante du délai](https://github.com/pypi/warehouse/blob/main/warehouse/constants.py) et [gestion authentifiée des releases](https://github.com/pypi/warehouse/blob/main/warehouse/manage/views/__init__.py).
- [Pip : classement des versions et des constructions](https://github.com/pypa/pip/blob/main/src/pip/_internal/index/package_finder.py).
- [Piwheels : événements PyPI](https://github.com/piwheels/piwheels/blob/main/piwheels/pypi.py) et [traitement des versions sans sdist](https://github.com/piwheels/piwheels/blob/main/piwheels/master/cloud_gazer.py).

## Annexe : publication historique 1.0.1

La précédente fiche documentait **1.0.1**, publiée le **26 septembre 2026** depuis le commit `b97e2193aee630b40740a621b1dafa625937514f`, avec un numéro d’application annoncé `1.0` distinct du numéro du paquet. Le [workflow historique de publication](https://github.com/cedrick14/cartomize-python/actions/runs/36273414966) et la [matrice historique](https://github.com/cedrick14/cartomize-python/actions/runs/36273414787) concernent cette édition antérieure, retirée de PyPI le 30 octobre 2026.

Ces références sont conservées pour la traçabilité. Elles ne prouvent ni la publication ni la validation de la nouvelle construction `1.0-20261030`.
