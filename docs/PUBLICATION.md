# Distribution de l’édition consolidée 1.0

**État au 30 octobre 2026 : préparation.** Cette fiche décrit la livraison de l’édition consolidée **1.0**, qui réunit les fonctionnalités déjà intégrées au dépôt, jusqu’au module G12. Elle ne constitue pas une preuve de publication. À la date de rédaction, aucune nouvelle distribution n’a été publiée sur PyPI et aucune ancienne édition n’a été supprimée dans le cadre de cette préparation.

Le paquet reste `cartomize`. Sa version publique, la version des métadonnées et `cartomize.__version__` sont toutes **`1.0`**. Le numéro de construction de la roue, **`20261030`**, distingue les nouveaux fichiers des distributions historiques sans changer la version publique.

Voir la [note de l’édition consolidée](RELEASE_1.0.md), le [guide de démonstration](DEMONSTRATION_1.0.md) et le [guide d’utilisation](WORKBENCH.md).

## Fichiers de cette livraison

| Fichier | Destination et usage |
|---|---|
| `cartomize-1.0-20261030-py3-none-any.whl` | Installation de la bibliothèque, des commandes et, avec l’option `gui`, de l’interface ; seul fichier prévu pour la nouvelle publication PyPI `1.0`. |
| `cartomize-1.0.tar.gz` | Sources complètes, à distribuer avec la livraison GitHub ou sur le site du projet ; ne pas envoyer cette archive à PyPI. |

La roue contient `Version: 1.0` dans `METADATA` et `Build: 20261030` dans `WHEEL`. Le numéro de construction est défini dans `setup.cfg`. Les noms, tailles et empreintes SHA-256 des fichiers effectivement construits doivent être enregistrés avec le rapport de validation.

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

Pour cette édition, **les deux archives sont validées, mais seule la roue avec le numéro de construction `20261030` doit être envoyée à PyPI**. Le dossier transmis à l’éditeur de confiance doit donc être distinct de celui contenant l’ensemble de la livraison.

La CI conserve les deux archives dans l’artefact `cartomize-complete-distributions`. Le script `scripts/stage_pypi_upload.py` sélectionne la nouvelle roue seule pour la version `1.0` ; l’artefact `cartomize-pypi-distributions` contient les fichiers destinés à l’envoi. La présence de ces artefacts ne signifie pas que le job de publication a été exécuté.

## Installation avant publication PyPI

Depuis le dossier contenant la roue vérifiée :

```bash
python -m pip install "./cartomize-1.0-20261030-py3-none-any.whl[gui]"
python -m cartomize gui
```

Pour les notebooks qui doivent ouvrir l’interface locale, remplacer `gui` par `notebook`. Pour l’API Python seule, installer la roue sans option. L’ouverture d’une fenêtre native demande un environnement graphique sur la machine qui exécute Python.

Si une ancienne version `1.0` est déjà installée, demander explicitement sa réinstallation :

```bash
python -m pip install --force-reinstall --no-cache-dir "./cartomize-1.0-20261030-py3-none-any.whl[gui]"
```

Vérifier ensuite la version et la construction :

```bash
python -c "import cartomize; from importlib.metadata import distribution; d = distribution('cartomize'); print(cartomize.__version__); print(d.version); print(d.read_text('WHEEL'))"
```

Les deux versions doivent être `1.0` et le fichier `WHEEL` doit indiquer `Build: 20261030`. Le seul affichage de `1.0` ne distingue pas cette livraison de l’ancienne distribution.

## Publication PyPI sous le numéro exact 1.0

### Situation historique vérifiée

La [release PyPI historique 1.0](https://pypi.org/project/cartomize/1.0/#files), publiée le **26 septembre 2026**, possède déjà `cartomize-1.0-py3-none-any.whl` et `cartomize-1.0.tar.gz`. Les [métadonnées JSON de PyPI](https://pypi.org/pypi/cartomize/1.0/json) permettent de vérifier leurs noms et dates.

PyPI interdit de réutiliser un nom de fichier, même après suppression. Il refuse aussi l’ajout de fichiers aux releases âgées de plus de **14 jours**. Au 30 octobre 2026, la release historique `1.0` dépasse ce délai : ajouter la nouvelle roue à cette release conservée n’est donc pas la procédure prévue.

### Remplacement par une release recréée

Le remplacement exige l’accès au **compte PyPI autorisé à gérer le projet**, puis la réauthentification demandée par l’interface de gestion. Le jeton d’une publication GitHub Actions ne remplace pas cet accès.

La procédure envisagée est la suivante :

1. Valider les deux archives, enregistrer leurs empreintes et rendre la livraison complète disponible par GitHub ou par le site du projet. Vérifier l’accès au compte PyPI et la configuration de l’éditeur de confiance avant d’entamer le retrait.
2. Depuis l’interface PyPI, supprimer la **release historique `1.0`**, sans supprimer le projet `cartomize`. Cette opération retire les anciens fichiers et ne libère pas leurs noms.
3. Publier uniquement `cartomize-1.0-20261030-py3-none-any.whl`. Ce nom inédit permet de créer une nouvelle release dont la version demeure exactement `1.0`.
4. Vérifier sur PyPI le fichier, son empreinte, sa description, ses dépendances, ses options et ses liens, puis réaliser une installation depuis l’index dans un environnement neuf. Les métadonnées de la release recréée proviennent de son premier fichier téléversé.
5. Retirer les autres anciennes éditions concernées par la décision de publication après vérification du remplacement. Contrôler ensuite la liste publique des versions et les installations sans numéro imposé.

La suppression et la publication sont séparées : le remplacement n’est pas atomique. Les anciens noms restent définitivement réservés, et les fichiers de verrouillage qui utilisent les anciennes empreintes ne sont pas transférés au nouveau fichier.

Le code de Warehouse distingue explicitement la protection des 14 jours des suppressions et recréations réalisées dans l’interface de gestion. La faisabilité de cette procédure ne prouve pas son exécution : tant que l’accès authentifié et les vérifications finales ne sont pas terminés, le statut demeure **préparation**.

### Archive source distribuée hors de PyPI

Pour un sdist de version exacte `1.0`, la validation actuelle de Warehouse exige `cartomize-1.0.tar.gz`. Ce nom a déjà été utilisé. La variante `cartomize-1.0.zip` et l’ajout d’un numéro de construction au nom du sdist ne satisfont pas cette validation.

La release recréée sur PyPI serait donc distribuée **par roue seule**. Les sources complètes resteraient disponibles dans la livraison GitHub ou sur le site du projet. Une commande imposant une construction de `cartomize` depuis les sources de PyPI, par exemple avec `--no-binary cartomize`, ne pourrait pas utiliser cette nouvelle livraison.

### Utilisateurs d’anciennes installations

Un numéro de construction ne crée pas une version supérieure à `1.0`. Un simple `pip install --upgrade cartomize` ne garantit donc pas le remplacement d’une ancienne installation `1.0`. Utiliser une réinstallation explicite de la roue vérifiée, puis contrôler son champ `Build`.

La version historique **`1.0.1`** est supérieure à `1.0` pour les installateurs. Si elle reste disponible et non retirée, une installation sans numéro imposé peut continuer à la sélectionner. Retirer seulement les préversions `0.8` et `0.9` ne résout pas ce point. Traiter explicitement la liste des anciennes éditions à retirer et vérifier le résultat avant d’annoncer `1.0` comme édition proposée par défaut.

## Conséquence pour piwheels

Piwheels suit les événements de PyPI. Sa [FAQ officielle](https://www.piwheels.org/faq.html) indique qu’une suppression de version sur PyPI entraîne aussi son retrait de piwheels, avec suppression des fichiers correspondants. Cette propagation peut demander un délai et doit être vérifiée.

Une nouvelle version ne contenant qu’une roue est classée `binary only` par le collecteur piwheels ; sa reconstruction automatique est désactivée. Puisque la nouvelle archive source `1.0` ne peut pas être envoyée à PyPI, **recréer `1.0` avec cette seule roue ne met pas automatiquement à jour le code distribué par piwheels**. Publier l’archive source sur GitHub ne déclenche pas cette reconstruction normale.

L’installation de la roue vérifiée ou depuis PyPI reste possible sur une plateforme disposant des dépendances requises. Le suffixe `py3-none-any` concerne la roue Cartomize ; il ne garantit pas à lui seul la disponibilité de ses dépendances sur chaque machine. Ne pas annoncer une nouvelle distribution piwheels sans vérifier les fichiers effectivement disponibles.

## Intégration continue et preuves de publication

Le workflow `.github/workflows/pypi-publish.yml` valide la construction et Windows Conda. Les autres workflows couvrent notamment Linux et Windows, les notebooks, l’interface et les projets réels. La publication utilise un éditeur de confiance PyPI avec l’environnement GitHub `pypi`.

Les déclencheurs prévus sont un tag `python-v*`, un commit contenant `[publish pypi]`, ou une exécution manuelle dont la destination est `pypi`. Un lancement de validation seule ou un job de publication marqué `skipped` ne constitue pas une publication. Le tag doit correspondre à la version du paquet.

Pour confirmer l’achèvement, consigner le commit publié, l’URL et la conclusion du job de publication, l’URL PyPI du fichier, son empreinte SHA-256 et le résultat de l’installation depuis l’index. Un artefact GitHub Actions, des tests réussis ou une fusion dans `main` ne suffisent pas à prouver la disponibilité sur PyPI.

## Références des règles de distribution

- [Format officiel des roues : version et construction](https://packaging.python.org/en/latest/specifications/binary-distribution-format/) ; [source de la spécification](https://github.com/pypa/packaging.python.org/blob/main/source/specifications/binary-distribution-format.rst).
- [PyPI : noms de fichiers déjà utilisés](https://docs.pypi.org/publishing/troubleshooting/) ; [source de la documentation](https://github.com/pypi/warehouse/blob/main/docs/user/publishing/troubleshooting.md).
- [PyPI : annonce du 22 juillet 2026 sur le délai de 14 jours](https://github.com/pypi/warehouse/blob/main/docs/blog/posts/2026-07-22-releases-now-reject-new-files-after-14-days.md).
- [Warehouse : validation des fichiers et du nom du sdist](https://github.com/pypi/warehouse/blob/main/warehouse/forklift/legacy.py), [constante du délai](https://github.com/pypi/warehouse/blob/main/warehouse/constants.py) et [gestion authentifiée des releases](https://github.com/pypi/warehouse/blob/main/warehouse/manage/views/__init__.py).
- [Pip : classement des versions et des constructions](https://github.com/pypa/pip/blob/main/src/pip/_internal/index/package_finder.py).
- [Piwheels : événements PyPI](https://github.com/piwheels/piwheels/blob/main/piwheels/pypi.py) et [traitement des versions sans sdist](https://github.com/piwheels/piwheels/blob/main/piwheels/master/cloud_gazer.py).

## Annexe : publication historique 1.0.1

La précédente fiche documentait **1.0.1**, publiée le **26 septembre 2026** depuis le commit `b97e2193aee630b40740a621b1dafa625937514f`, avec un numéro d’application annoncé `1.0` distinct du numéro du paquet. Le [workflow historique de publication](https://github.com/cedrick14/cartomize-python/actions/runs/36273414966), la [matrice historique](https://github.com/cedrick14/cartomize-python/actions/runs/36273414787) et les [anciens fichiers PyPI](https://pypi.org/project/cartomize/1.0.1/#files) concernent cette édition antérieure.

Ces références sont conservées pour la traçabilité. Elles ne prouvent ni la publication ni la validation de la nouvelle construction `1.0-20261030`.
