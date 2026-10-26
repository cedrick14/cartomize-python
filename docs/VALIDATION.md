# Tests et validation

## Cartomize 1.4.0 — module M07, validation locale du 26 octobre 2026

La suite complète passe **722 tests**, avec deux essais conditionnels ignorés
(CUDA et QGIS natif), sous Linux / Python 3.12.14. Le cours 13 corrigé passe
dans un noyau Jupyter neuf, avec **7 cellules de code exécutées**.

Le module automatique est aussi vérifié avec un extrait Sentinel-2 réel du
Mayombe : **16 384 pixels utiles**, calibration confrontée aux fenêtres du même
produit dans une seconde collection et NDVI exact à la précision numérique
attendue. Le même extrait traverse le travailleur de la fenêtre. Une zone
agrandie laisse **256 pixels manquants** : la production est refusée et le
diagnostic reste accessible. Les fichiers de référence et leur provenance sont
inclus dans [tests/data/sentinel2_mvouti](../tests/data/sentinel2_mvouti/README.md).

La [note 1.4.0](RELEASE_1.4.0.md), le [guide M07](IMAGERY_AUTOMATIC.md) et le
[rapport machine](VALIDATION_1.4.0.json) détaillent la portée, les résultats et
la reproduction. Les contrôles Windows, Linux et QGIS distants sont identifiés
par les commits dans [GitHub Actions](https://github.com/cedrick14/cartomize-python/actions).

La wheel 1.4.0 est installée avec l’option graphique dans un environnement neuf.
L’import provient de `site-packages`, hors du dépôt : contrôle de couverture et
mosaïque automatiques, calculs raster/vectoriels, 20 pages graphiques, trois
thèmes, exports, projet et noyau de console passent les contrôles.

## Cartomize 1.3.0 — validation locale du 26 octobre 2026

Les sources complétées passent **626 tests**, avec deux essais conditionnels ignorés (CUDA et QGIS natif), sous Linux / Python 3.12.14. Les douze notebooks autonomes passent également dans de vrais noyaux Jupyter, soit 73 cellules de code. La wheel construite est installée dans un environnement neuf et vérifiée hors du dépôt : calculs, 20 pages graphiques, exports, projet et console.

La [note de version](RELEASE_1.3.0.md) détaille les contrats modifiés et les contrôles. Le [rapport machine](VALIDATION_1.3.0.json) conserve les dépendances, les limites et l’empreinte de la wheel testée. Les résultats ci-dessous restent des preuves historiques de la version 1.0.1 ; les résultats CI de 1.3.0 sont à lire sur les commits correspondants dans GitHub Actions.

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

Les tests utilisent des données synthétiques et des résultats de référence,
ainsi qu’un petit extrait public Sentinel-2 et ses références indépendantes à
partir de la version 1.4.0. Ils vérifient le comportement logiciel sans
constituer une validation thématique sur le terrain ni une mesure de
performance sur de grandes scènes.

Les contrôles graphiques hors écran ne couvrent pas toutes les configurations de bureau. La passerelle ArcGIS Pro nécessite une validation dans une installation licenciée. Le test CUDA matériel est ignoré lorsqu’aucun GPU compatible n’est accessible.

Les limites des méthodes sont décrites dans le [catalogue des outils](TOOL_AUDIT.md) et les [principes de traitement](SIG_WORKFLOWS.md).
