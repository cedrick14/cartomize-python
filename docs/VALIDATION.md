# Tests et validation

## Cartomize 1.0, révision 1.0.1

Validation du 26 septembre 2026 sur le commit `b97e2193aee630b40740a621b1dafa625937514f`.

- [Matrice Linux et Windows, Python 3.11 et 3.12](https://github.com/cedrick14/cartomize-python/actions/runs/36273414787) : **340 tests réussis et 2 ignorés dans chacune des quatre configurations**. Le contrôle natif QGIS réussit dans son environnement dédié.
- [Publication et environnement Windows Conda](https://github.com/cedrick14/cartomize-python/actions/runs/36273414966) : **50 tests Conda réussis**, dont l’exécution dans un noyau Jupyter. Les 19 contrôles des vues et du prétraitement ont réussi avant la suite complète Linux de publication.
- Les distributions ont passé les contrôles Twine et `check_release.py`.
- Les fichiers téléchargés depuis PyPI correspondent aux empreintes SHA256 de publication. Les 71 modules Python du paquet correspondent aux sources. Le lancement du paquet installé confirme l’affichage « Version 1.0 » dans la fenêtre.

## Contrôles automatisés

La suite vérifie les traitements raster et vectoriels, les masques NoData, la calibration, les scènes multispectrales, la classification, les projets, les maquettes et les exports. Les tests d’intégration exercent les connexions entre outils, la sauvegarde des sessions et l’exécution en arrière-plan.

Les tests de visualisation couvrent les valeurs de pixels, les classes, les pixels noirs valides, les lectures au zoom, les comparaisons entre résolutions et systèmes de coordonnées, les échelles colorimétriques, les tableaux, les graphiques, les PDF et le cycle de vie des vues.

| Environnement | Contrôles |
|---|---|
| Linux et Windows, Python 3.11 et 3.12 | Suite complète, construction et vérification des distributions |
| Windows Conda, Python 3.12 | Démarrage, traitements, interface et réactivité dans un noyau Jupyter |
| QGIS | Inventaire, import, copie et export dans le moteur natif |
| CUDA | Exécution matérielle lorsque le GPU et les dépendances sont disponibles |

Les résultats par version sont accessibles dans [GitHub Actions](https://github.com/cedrick14/cartomize-python/actions). La [fiche de publication](PUBLICATION.md) identifie les distributions.

## Reproduction

```bash
python -m pip install -e ".[dev,notebook,distributed]"
python -m pytest
python -m build
python -m twine check --strict dist/*
```

Les tests graphiques utilisent `QT_QPA_PLATFORM=offscreen` sur les machines sans écran.

## Portée

Les tests utilisent des données synthétiques et des résultats de référence. Ils vérifient le comportement logiciel sans constituer une validation thématique sur le terrain ni une mesure de performance sur de grandes scènes.

Les contrôles graphiques hors écran ne couvrent pas toutes les configurations de bureau. La passerelle ArcGIS Pro nécessite une validation dans une installation licenciée. Le test CUDA matériel est ignoré lorsqu’aucun GPU compatible n’est accessible.

Les limites des méthodes sont décrites dans le [catalogue des outils](TOOL_AUDIT.md) et les [principes de traitement](SIG_WORKFLOWS.md).
