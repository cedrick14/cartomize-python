# Distribution de Cartomize 1.0

## État de publication

La construction **2026103101**, issue du commit [`ba092d534be1d0b5f3d19c4a827742709cd9a508`](https://github.com/cedrick14/cartomize-python/commit/ba092d534be1d0b5f3d19c4a827742709cd9a508), est disponible dans la [livraison GitHub](https://github.com/cedrick14/cartomize-python/releases/tag/cartomize-1.0-2026103101). La version du paquet et de l’application reste **1.0**.

| Destination | État vérifié |
|---|---|
| GitHub | Wheel, sources et exemples publiés le 30 octobre 2026 à 23:37 UTC ; fichiers téléchargés et contrôlés. |
| PyPI | La release `1.0` contient encore les constructions `20261030` et `2026103001`, avec la description initiale. La construction `2026103101` n’a pas été envoyée. |

Le nouveau wheel contient la présentation publique révisée, l’interface dynamique et les corrections de messages. Ses **103 fichiers Python** correspondent aux sources du commit de livraison. La description de ses métadonnées est identique à [README_PYPI.md](../README_PYPI.md). Le [rapport de vérification](VALIDATION_PUBLIC_DESCRIPTION_1.0.json) conserve les résultats et les empreintes.

## Fichiers de la livraison

| Fichier | Taille | SHA-256 |
|---|---:|---|
| [Wheel](https://github.com/cedrick14/cartomize-python/releases/download/cartomize-1.0-2026103101/cartomize-1.0-2026103101-py3-none-any.whl) | 549 795 octets | `7cae9238bfa8811f1cd3e2b2743917f4388619d995c32a96d700b16dc4862195` |
| [Sources](https://github.com/cedrick14/cartomize-python/releases/download/cartomize-1.0-2026103101/cartomize-1.0.tar.gz) | 2 214 310 octets | `36f95b2548b90b6298f9e8209d186d891b4213ee7c3e1046cf0648b9df5fb956` |
| [Exemples](https://github.com/cedrick14/cartomize-python/releases/download/cartomize-1.0-2026103101/cartomize-1.0-presentation.zip) | 3 436 588 octets | `4edbab9a6258843d4834ca9956d3f5f70d9bd37bdadc551c3b4ce3a5285c898c` |

Le ZIP contient exactement le wheel et l’archive source ci-dessus, ainsi que des guides et des données synthétiques explicitement identifiées. Pour installer le wheel téléchargé avec l’interface :

```bash
python -m pip install --force-reinstall "./cartomize-1.0-2026103101-py3-none-any.whl[gui]"
python -m cartomize gui
```

L’option `notebook` ajoute JupyterLab et son noyau. Utiliser un environnement Python isolé. Comme le numéro reste `1.0`, une installation portant déjà ce numéro nécessite une réinstallation explicite.

## Contrôles de livraison

Le [workflow 41144499000](https://github.com/cedrick14/cartomize-python/actions/runs/41144499000) a validé la suite Linux (**1 898 réussites, 2 tests ignorés**), les archives et leur description. Le contrôle Windows Conda a réussi **52 tests**, couvrant notamment le démarrage, Jupyter et les traitements de l’interface. Les contrôles ciblés sont détaillés dans le rapport ; leurs comptes ne sont pas additionnés à la régression générale.

La livraison GitHub a réussi. Le job PyPI s’est arrêté au contrôle de description, avant tout envoi : les étapes de téléversement sont marquées `skipped`.

## Remplacement de la description PyPI

PyPI conserve les métadonnées du premier fichier d’une release ; un fichier supplémentaire ne remplace pas sa description, selon la [documentation officielle](https://docs.pypi.org/api/json/). Le script `scripts/check_pypi_metadata.py` détecte cette différence avant publication.

Pour conserver exactement la version `1.0`, le propriétaire doit supprimer **la release `1.0` uniquement**, depuis sa [page de gestion](https://pypi.org/manage/project/cartomize/release/1.0/). Le projet et sa configuration de publication doivent être conservés. Supprimer seulement un fichier ne recrée pas les métadonnées de la release.

Après cette opération, reprendre uniquement le [job `publish` 124369613952](https://github.com/cedrick14/cartomize-python/actions/runs/41144499000/job/124369613952) du même workflow. Il réutilise le wheel vérifié de l’artefact `cartomize-pypi-distributions`, conservé jusqu’au **13 novembre 2026 à 23:36 UTC**. La reprise complète du workflow reconstruirait les fichiers et tenterait de recréer la livraison GitHub existante.

Le nom du nouveau wheel est inédit. PyPI interdit la réutilisation d’un nom de fichier déjà employé, même après suppression. L’archive source `cartomize-1.0.tar.gz` reste donc distribuée sur GitHub ; l’envoi PyPI préparé contient uniquement le wheel.

## Publications antérieures

Le [rapport de la construction 2026103001](https://github.com/cedrick14/cartomize-python/blob/21b83343c43e1c61f2b6158a72bbad4bd9f279bc/docs/PUBLICATION.md) conserve la preuve de publication de l’interface dynamique sur PyPI, ainsi que les limites de distribution vers piwheels. Les rapports antérieurs décrivent leurs constructions respectives.
