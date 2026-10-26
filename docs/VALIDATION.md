# Tests et validation

## Cartomize 1.5.0 — M08, qualité vectorielle

**865 tests réussis, 2 exclus, 0 échec**, en 176,94 s sur Python 3.12.
Les 136 tests ajoutés pour G01–G03 et leurs interfaces sont inclus dans ce total.
Le cours 14 exécute huit cellules et les essais sur trois jeux réels épinglés
réussissent leurs onze contrôles. La wheel est installée dans un environnement
neuf hors des sources, puis utilisée par l’API, la fenêtre et sa console.

Les preuves et conventions figurent dans la [note 1.5.0](RELEASE_1.5.0.md),
le [rapport machine](VALIDATION_1.5.0.json) et le
[rapport sur données réelles](VALIDATION_M08_REAL.json). Les états de GitHub
Actions restent attachés à la demande d’intégration et ne sont pas assimilés
aux résultats locaux. Les validations 1.4.0 et antérieures suivent ci-dessous.


## Cartomize 1.4.0 — module M07, validation locale du 26 octobre 2026

La suite complète locale initiale a validé **722 tests**, avec deux essais conditionnels ignorés
(CUDA et QGIS natif), sous Linux / Python 3.12.14. Les douze cours autonomes,
00 à 10 et 13, passent dans des noyaux Jupyter neufs, avec **73 cellules de code
exécutées**. Le cours 00 indique explicitement sa couverture partielle acceptée.

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

Après cette suite locale complète, les derniers essais CI ont révélé un
débordement typographique du formulaire sur Windows et l’acceptation implicite
de données partielles dans le cours 00. Le cours est corrigé et les douze
notebooks sont réexécutés. L’ajustement du formulaire passe ensuite **28 tests
GUI concernés** et **16 cas de géométrie** avec les métriques Qt habituelles et
celles reproduisant exactement le débordement Windows. Les libellés et boutons
restent intégralement lisibles, y compris avec les marges supplémentaires des
champs numériques de Windows 11. La wheel reconstruite est installée et vérifiée
à nouveau ; la matrice complète finale est celle du commit publié dans GitHub.

Un contrôle supplémentaire a révélé un échec intermittent lors de la récupération
d’un bouton interne de la barre d’outils. Les libellés sont désormais définis
sur les actions Qt, ce qui supprime cette récupération et les conserve après
activation ou désactivation. **21 cas ciblés** valident les actions, le diagnostic
d’images, l’espace de travail et le cycle de vie de la fenêtre. Ils comprennent
six créations/destructions avec clic sur Exécuter, dont trois avec le retour
Qt inattendu observé en CI. La wheel issue de cette correction est reconstruite,
installée et vérifiée à nouveau hors des sources.

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
