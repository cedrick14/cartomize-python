# Publication de Cartomize 1.0 — espace de travail dynamique

**Construction courante : `2026103001`, publiée le 30 octobre 2026 à 23 h 46 à Kinshasa (22 h 46 UTC) sur [PyPI](https://pypi.org/project/cartomize/1.0/#files) et dans la [livraison GitHub](https://github.com/cedrick14/cartomize-python/releases/tag/cartomize-1.0-2026103001).** La version publique reste exactement **1.0**.

Cette construction ajoute les panneaux et vues mobiles, les repères de placement, la restauration de la disposition et les descriptions repliées dans **Aide**. Elle conserve les modules de l’édition consolidée jusqu’à G12. Le [guide de l’espace dynamique](DYNAMIC_WORKSPACE.md) décrit son utilisation ; le [rapport de validation](VALIDATION_DYNAMIC_1.0.json) rassemble la provenance, les résultats et les empreintes.

## Installer la construction courante

Python **3.11 ou ultérieur** est nécessaire. Dans un environnement Python activé, installer l’interface :

```bash
python -m pip install --index-url https://pypi.org/simple "cartomize[gui]==1.0"
python -m cartomize gui
```

Pour l’API seule, utiliser `cartomize==1.0`. Pour Jupyter et les composants de l’interface, utiliser `cartomize[notebook]==1.0`, puis lancer `python -m jupyter lab`. Une fenêtre native demande une session graphique sur la machine qui exécute Python.

Une installation antérieure peut déjà porter la version `1.0`. Pour la remplacer par la construction courante, demander une réinstallation explicite :

```bash
python -m pip install --index-url https://pypi.org/simple --force-reinstall --no-cache-dir "cartomize[notebook]==1.0"
```

Contrôler ensuite le paquet réellement importé :

```bash
python -c "import cartomize; from importlib.metadata import distribution; d = distribution('cartomize'); print('Module :', cartomize.__version__); print('Paquet :', d.version); print(d.read_text('WHEEL'))"
```

Les deux versions doivent être **`1.0`** et le fichier `WHEEL` doit indiquer **`Build: 2026103001`**. Le [numéro de construction du wheel](https://packaging.python.org/en/latest/specifications/binary-distribution-format/) distingue les fichiers de cette même version. Un simple `pip install --upgrade cartomize` ne garantit pas le remplacement d’une installation déjà numérotée `1.0`.

Une installation par l’URL fixe du wheel GitHub, dont les octets sont identiques à ceux de PyPI, est également possible :

```bash
python -m pip install --force-reinstall --no-cache-dir "cartomize[notebook] @ https://github.com/cedrick14/cartomize-python/releases/download/cartomize-1.0-2026103001/cartomize-1.0-2026103001-py3-none-any.whl#sha256=595754d33bea43d4aa70e1891061a9c2300dc2b3195f8a591957eaf88d1344fd"
```

Le [parcours de démonstration](DEMONSTRATION_1.0.md) explique l’utilisation du dossier portable et des notebooks.

## Fichiers publiés et empreintes

Les trois fichiers de la [release `cartomize-1.0-2026103001`](https://github.com/cedrick14/cartomize-python/releases/tag/cartomize-1.0-2026103001) ont été téléchargés et leurs SHA-256 recalculés. Le wheel GitHub est identique au fichier PyPI ; le ZIP de présentation contient exactement ce wheel et cette archive source.

| Fichier | Taille | Destination |
|---|---:|---|
| [cartomize-1.0-2026103001-py3-none-any.whl](https://github.com/cedrick14/cartomize-python/releases/download/cartomize-1.0-2026103001/cartomize-1.0-2026103001-py3-none-any.whl) | 552 185 octets | PyPI et GitHub : bibliothèque, commandes et interface selon les options installées. |
| [cartomize-1.0.tar.gz](https://github.com/cedrick14/cartomize-python/releases/download/cartomize-1.0-2026103001/cartomize-1.0.tar.gz) | 2 209 988 octets | Sources complètes de cette construction, sur GitHub. |
| [cartomize-1.0-presentation.zip](https://github.com/cedrick14/cartomize-python/releases/download/cartomize-1.0-2026103001/cartomize-1.0-presentation.zip) | 3 439 905 octets | Wheel, sources, guides, notebook 22, captures et données pédagogiques synthétiques. |

| Fichier | SHA-256 |
|---|---|
| Wheel | `595754d33bea43d4aa70e1891061a9c2300dc2b3195f8a591957eaf88d1344fd` |
| Sources | `b6d8770148c7d3ef00c04316a9b8bbc25415ee313b57791ebe289c00712dd2e1` |
| Présentation | `329f85778416aca3ceda3f86a8f8a601d6522177baa08c7d0e6e7067a67fa25f` |

Les données de démonstration sont simulées ; elles ne sont pas présentées comme des observations satellitaires réelles.

## Provenance de la publication

La [PR 15](https://github.com/cedrick14/cartomize-python/pull/15) a été fusionnée puis publiée depuis le commit [`7d4dc8510fbd1d7aaa147587149f0766769d62c9`](https://github.com/cedrick14/cartomize-python/commit/7d4dc8510fbd1d7aaa147587149f0766769d62c9). Son arbre `7c9cad9fd61d72dd5ca271d1f9289d700d6f8345` est identique à l’arbre validé du head `83c7dfd1790115a3485480182bc2409907249959` et du commit de test natif `d83ee5ab223a618ba559801c964c7d9d4593b7a4`.

| Élément | Preuve |
|---|---|
| Workflow de publication | [41139569567](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567), terminé en succès. |
| Construction | [Job 124350264530](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567/job/124350264530), succès. |
| Windows Conda | [Job 124350264938](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567/job/124350264938), succès. |
| Publication PyPI | [Job 124352502209](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567/job/124352502209), succès ; téléversement accepté avec réponse HTTP 200. |
| Livraison GitHub | [Job 124352502234](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567/job/124352502234), succès ; release publiée à `2026-10-30T22:46:06Z`. |
| Fichier PyPI | [cartomize-1.0-2026103001-py3-none-any.whl](https://files.pythonhosted.org/packages/20/0d/fa7e601036003022f8e250bdd8d3505eb45122b89a0a7ed748e5e129de25/cartomize-1.0-2026103001-py3-none-any.whl) ; 552 185 octets. |
| Date de téléversement PyPI | `2026-10-30T22:46:27.115192Z`, selon les [métadonnées de la release](https://pypi.org/pypi/cartomize/1.0/json?build=2026103001). |
| Versions publiques constatées | `1.0` uniquement, selon les métadonnées consultées à 22:50:46 UTC. |
| Correspondance du code | **103 fichiers Python sur 103 identiques octet pour octet** entre le wheel publié, les sources contrôlées et le commit de publication ; aucun fichier manquant ni écart. |

## Validation du code et de l’interface

Les résultats sont conservés par environnement et par suite. Les précontrôles, suites complètes et workflows répétés se recouvrent : leurs comptes ne sont pas additionnés en un nombre de tests distincts.

| Domaine | Résultats vérifiés | Exécution |
|---|---|---|
| Bibliothèque sous Linux, Python 3.11 et 3.12 | **1 878 réussites et 2 tests ignorés dans chacun des deux environnements.** | [41137159968](https://github.com/cedrick14/cartomize-python/actions/runs/41137159968) |
| Bibliothèque sous Windows, Python 3.11 et 3.12 | **1 898 réussites et 2 tests ignorés dans chacun des deux environnements.** Un précontrôle de formulaires compacts réussit aussi 46 tests par environnement ; il recouvre la suite complète. | [41137159968](https://github.com/cedrick14/cartomize-python/actions/runs/41137159968) |
| Passerelle QGIS native | **1 test réussi.** | [Job QGIS](https://github.com/cedrick14/cartomize-python/actions/runs/41137159968/job/124342900707) |
| Workflow Projets réels | Suite : **1 878 réussites / 2 ignorés sous Linux**, **1 898 réussites / 2 ignorés sous Windows**. Les deux jobs terminent en succès. | [41137160019](https://github.com/cedrick14/cartomize-python/actions/runs/41137160019) |
| Interface native Windows et Linux | **69 tests réussis par plateforme, soit 138 exécutions réussies** ; 4 configurations, 46 états et 74 PNG par plateforme. | [41137159917](https://github.com/cedrick14/cartomize-python/actions/runs/41137159917) |
| Construction du paquet publié | Précontrôle de vues : **19 réussites** ; suite complète : **1 878 réussites et 2 ignorés**. | [Job de construction](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567/job/124350264530) |
| Windows Conda du workflow de publication | **52 tests réussis** sur le paquet installé, la boucle notebook et les traitements de bureau. | [Job Windows Conda](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567/job/124350264938) |

Les workflows exécutés après fusion sur `7d4dc851…` ont également terminé en succès : [Bibliothèque](https://github.com/cedrick14/cartomize-python/actions/runs/41139569384), [Projets réels](https://github.com/cedrick14/cartomize-python/actions/runs/41139569336), [bureau multiplateforme](https://github.com/cedrick14/cartomize-python/actions/runs/41139569368) et [publication](https://github.com/cedrick14/cartomize-python/actions/runs/41139569567). Leurs états sont consignés dans le rapport JSON ; leurs comptes ne sont pas ajoutés à ceux du tableau.

La CI native utilise les plugins Qt **`windows`** et **`xcb`**. Elle couvre les thèmes clair et sombre, les fenêtres 1100 × 750 et 1440 × 940, les repères, le détachement, le redimensionnement et le réancrage, avec conservation des panneaux, documents, canvas et valeurs. Après le correctif de mise en page des titres et de l’aide, les quatre vues initiales demandées ont été inspectées sur Windows et Linux : aucun espace artificiel ajouté autour du titre n’a été observé.

Le runner Windows déclare un écran de 1024 × 768. Les fenêtres plus grandes sont contrôlées par leurs géométries Qt et leurs rendus `QWidget.grab`, avec événements `QTest` ; les images ne prouvent pas qu’une fenêtre de 1440 × 940 est entièrement visible sur ce moniteur. Cette portée est conservée dans le [rapport JSON](VALIDATION_DYNAMIC_1.0.json).

## Installation réelle et sélection depuis l’index

**L’installation réelle du nouveau fichier PyPI est vérifiée.** Le wheel a été téléchargé depuis son URL `files.pythonhosted.org`, avec SHA-256 imposé, puis installé dans un environnement neuf sous Python **3.12.14**, hors du dépôt source et sans paquets système. Cette installation utilise la méthode **`direct_pypi_wheel`**.

Le contrôle ciblé, lancé à 22:52:37 UTC, a réussi en **21,329 secondes**. Il confirme :

- les versions de module et de métadonnées `1.0`, et `Build: 2026103001` ;
- l’origine des imports dans le paquet installé et les **103 sources Python identiques** au commit publié ;
- les modules G12 et les anneaux attendus de **42 m²** et **46 m²**, soit **88 m²**, sans chevauchement ; l’inclusion du polygone d’entrée porte le premier anneau à **142 m²** ;
- la véritable fenêtre du paquet installé, en **Qt offscreen**, sur le cas sombre 1100 × 750 : détachement des paramètres et du résultat, redimensionnement, retour, repères et réinitialisation ;
- l’installation et l’import des composants `gui`, `notebook` et `distributed`, dont PySide6 6.9.3 et JupyterLab **4.6.5** ;
- `pip check` sans incohérence, la commande d’aide Cartomize et l’affichage de la version JupyterLab avec code de sortie nul.

Ce contrôle du paquet installé est distinct de la CI native. Il ne réexécute pas la suite complète du dépôt. L’option GPU est déclarée ; aucune exécution CUDA/CuPy n’a été effectuée dans cet environnement CPU.

**La sélection normale depuis l’index PyPI a été vérifiée séparément à 22:54:44 UTC.** Un `pip dry-run` avec `--ignore-installed --no-deps --no-cache-dir --require-hashes` a choisi le nouveau wheel, à la même URL et avec le même SHA-256, avec `is_direct=false`. Cette preuve établit le choix de l’index ; l’exécution réelle du paquet provient de l’installation directe décrite plus haut.

Un premier relevé à 22:50:12 UTC recevait encore l’ancien fichier depuis un cache de l’index. La vérification d’empreinte a empêché son installation. Le contrôle réussi de 22:54:44 UTC clôt cet incident initial ; il ne constitue plus un blocage de distribution.

## Construction et distribution

Le numéro `2026103001` est défini dans `setup.cfg`. Le [workflow de distribution](../.github/workflows/pypi-publish.yml) valide la construction et Windows Conda, conserve le wheel et les sources dans `cartomize-complete-distributions`, puis sélectionne le wheel seul pour PyPI dans `cartomize-pypi-distributions`. Le dossier portable est conservé dans `cartomize-demonstration-delivery`.

Les jobs GitHub et PyPI ont été exécutés depuis le même commit de fusion, avec les marqueurs `[publish delivery]` et `[publish pypi]`. Le nouveau fichier a été ajouté à la release `1.0` recréée le 30 octobre. Son nom inédit respecte la séparation des constructions sans changer le numéro public.

Pour reproduire les archives depuis ce commit, avec un répertoire de sortie propre :

```bash
python -m build --outdir pypi-dist
python -m twine check --strict pypi-dist/*
python scripts/check_release.py pypi-dist
python scripts/verify_installed_release.py --wheel pypi-dist/cartomize-1.0-2026103001-py3-none-any.whl --output reports/installed-2026103001.json
```

## Limites de distribution

### Description de la release PyPI

Les métadonnées de la release sont établies par son premier fichier ; les fichiers suivants ne les remplacent pas, selon la [documentation de PyPI](https://docs.pypi.org/api/json/). Les métadonnées consultées après publication mentionnent encore le wheel initial `20261030`, alors que l’API des fichiers, l’index normal et les octets téléchargés confirment la nouvelle construction `2026103001`.

La récupération HTML directe n’a pas exposé les noms des fichiers ; aucune conclusion sur leur présence n’est tirée de cette réponse HTML. Le champ `Build` du paquet installé, les URL et les empreintes établissent la construction utilisée. Le [guide des panneaux](DYNAMIC_WORKSPACE.md) et ce document décrivent la version dynamique.

### Sources `1.0` conservées sur GitHub

PyPI [interdit de réutiliser un nom de fichier déjà employé](https://docs.pypi.org/publishing/troubleshooting/), même après suppression. Le nom `cartomize-1.0.tar.gz` a déjà été utilisé. La [validation de Warehouse](https://github.com/pypi/warehouse/blob/main/warehouse/forklift/legacy.py) n’accepte pas de le remplacer, pour cette version exacte, par un sdist ZIP ou par un sdist portant le numéro de construction du wheel.

Cette édition est donc distribuée sur PyPI **par wheel seul**. Les sources de la nouvelle construction sont disponibles dans sa livraison GitHub ; une installation imposant les sources de Cartomize avec `--no-binary cartomize` ne peut pas les obtenir depuis PyPI.

### Piwheels : nouvelle construction non constatée

À **22:55:21 UTC**, la [page piwheels](https://www.piwheels.org/project/cartomize/?build=2026103001) et son [API JSON](https://www.piwheels.org/project/cartomize/json?build=2026103001) montrent encore six éditions historiques, dont le fichier `1.0` du 26 septembre ; le nouveau wheel n’y est pas présent. Piwheels n’est donc pas annoncé comme source de cette construction.

La publication PyPI ne garantit pas sa mise à jour sur piwheels. Le collecteur [classe les releases sans sdist comme des distributions binaires seules](https://github.com/piwheels/piwheels/blob/main/piwheels/master/cloud_gazer.py), sans reconstruction normale depuis les sources. Déposer le sdist sur GitHub ne déclenche pas cette reconstruction. La [FAQ piwheels](https://www.piwheels.org/faq.html) décrit aussi le suivi des suppressions PyPI, qui peut être différé.

Utiliser PyPI ou le wheel vérifié de la livraison GitHub pour cette construction. Le suffixe `py3-none-any` du wheel Cartomize ne garantit pas la disponibilité de toutes ses dépendances sur chaque plateforme.

## Historique compact

| Édition antérieure | Références de traçabilité | Portée |
|---|---|---|
| **1.0, construction `20261030`** | [Livraison GitHub initiale](https://github.com/cedrick14/cartomize-python/releases/tag/cartomize-1.0-20261030), [publication 41124811288](https://github.com/cedrick14/cartomize-python/actions/runs/41124811288), [commit `b65c2ffd…`](https://github.com/cedrick14/cartomize-python/commit/b65c2ffd9a2992a0279a7053fe8480c618e832dd). | Première édition consolidée, publiée le 30 octobre 2026 à 20:43:55 UTC après recréation de la release historique `1.0` ; modules terminés jusqu’à G12. |
| **1.0.1** | [Publication 36273414966](https://github.com/cedrick14/cartomize-python/actions/runs/36273414966), [matrice 36273414787](https://github.com/cedrick14/cartomize-python/actions/runs/36273414787), [commit `b97e2193…`](https://github.com/cedrick14/cartomize-python/commit/b97e2193aee630b40740a621b1dafa625937514f). | Publication du 26 septembre 2026, retirée de PyPI le 30 octobre ; le numéro du paquet était distinct du numéro d’application alors annoncé. |

Le retrait des préversions `0.8.1a1`, `0.8.1a2`, `0.8.2a1` et `0.9.0a1` appartient à l’opération initiale du 30 octobre. Les preuves de la construction courante `2026103001` sont consignées dans ce document et dans [VALIDATION_DYNAMIC_1.0.json](VALIDATION_DYNAMIC_1.0.json).
