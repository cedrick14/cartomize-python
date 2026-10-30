# Tests et validation

## Cartomize 1.11.0 — M13 / G09, table croisée des surfaces

La suite complète sur les sources figées réussit **1 619 tests**, avec
**2 exclusions prévues et aucun échec**, en **408.966 s** sous Linux/Python
3.12.14. Les 150 nouvelles régressions se répartissent entre le
moteur (99), les interfaces (14), la fenêtre (16) et l’oracle indépendant (21).
Les sources, tests, scripts et workflows restent identiques avant et après
la passe complète.

Les **13 scénarios réels** réussissent : 80 zones × 8 classes donnent 640 cellules,
dont 283 cellules nulles, avec 357 géométries d’intersection. Les sept fichiers
sources sont inchangés. Les produits sont rouverts avec contrôle des géométries,
attributs, tableaux et empreintes.

Le cours 20 exécute **11 cellules** dans un noyau neuf (7.08 s) ; le site
exporte **21 leçons**. La wheel installée hors du dépôt dans un environnement
neuf réussit **29 contrôles**, avec `pip check` réussi et **100 modules identiques
aux sources**. Les deux exclusions locales concernent CUDA et QGIS. Les
matrices Windows/Ubuntu et le contrôle QGIS distant restent attachés au commit
exact testé sur GitHub ; ce rapport local précède leur lancement.

Les références analytiques utilisent un découpage rectangulaire Python et la
formule des lacets sur les limites réelles. La comparaison des polygones
d’occupation du sol partage GEOS avec un ordre d’opérations différent ; la
reprojection partage PROJ. Les budgets de comparaison et les résidus observés
figurent dans [VALIDATION_G09_REAL.json](VALIDATION_G09_REAL.json). Le moteur
conserve sa tolérance de fermeture `1e-6 m² + 1e-8 × surface de référence`.

Les résultats détaillés, versions et empreintes sont dans
[VALIDATION_1.11.0.json](VALIDATION_1.11.0.json). Voir la
[note 1.11.0](RELEASE_1.11.0.md) et le [guide G09](VECTOR_TABULATION.md).

## Cartomize 1.10.0 — M12 / G07, extraction avec bilan

La suite finale sur les sources figées réussit **1 469 tests, 2 exclusions
prévues et aucun échec** en **492,12 s** sous Linux/Python 3.12.14. Les
**155 nouvelles régressions** couvrent le moteur (109), les interfaces (14),
la fenêtre (21) et l'oracle géométrique indépendant (11). Les empreintes des
sources, tests, scripts et workflows sont identiques avant et après la passe.

Le [rapport réel G07](VALIDATION_G07_REAL.json) conserve **9 scénarios
réussis**, les partitions complètes de Paris/RDC, les décisions, les types
DATE vérifiés dans SQLite et **10 fichiers d'entrée inchangés**. Le prédicat
RDC est comparé à un ray casting Python ; la reprojection partage PROJ et
les intersections parisiennes partagent GEOS. Ces limites sont explicites.

Le cours 19 exécute **9 cellules** dans un noyau Jupyter neuf. La wheel
installée dans un environnement neuf hors du dépôt réussit **26 contrôles**,
avec `pip check` réussi et **98 modules identiques aux sources**. Le site
pédagogique exporte **20 leçons**. Les autres cours autonomes sont exécutés
par la matrice Windows/Ubuntu ; les deux cours demandant `Tuto.zip` restent
hors de cette passe autonome.

Les résultats détaillés et empreintes sont dans
[VALIDATION_1.10.0.json](VALIDATION_1.10.0.json). Ce rapport est créé avant
l'envoi GitHub ; les résultats distants appartiennent au commit testé de
la demande d'intégration. Les exclusions locales concernent CUDA et QGIS ;
QGIS possède un contrôle distant dédié. Voir la
[note 1.10.0](RELEASE_1.10.0.md) et le [guide G07](VECTOR_SELECTION.md).

## Cartomize 1.9.0 — M11 / G06, conversion et conditionnement

Le dernier passage local de la suite complète, au commit `0dd9bf6`, réussit
**1 283 tests, avec 2 exclusions prévues et aucun échec**, en **371,923 s**
sous Linux / Python 3.12.14. Il comprend 152 nouveaux cas. Les exclusions
locales concernent le matériel CUDA et QGIS natif, qui possède un contrôle
distant. Ce passage précède le dernier ajustement des deux libellés de boutons.

Après ce passage, le seul changement applicatif est le texte des actions
de résultats. Les mesures natives Windows identifiaient deux boutons de
392 px, portant la page à 442 px pour 431 px disponibles. Les actions
**« Ouvrir le rapport »** et **« Afficher les données »** corrigent cette
contrainte, après le raccourcissement du sélecteur de couche. Les assertions
de lisibilité et d’absence de défilement horizontal sont conservées.

Les sources finales réussissent **22 tests G06 sous Linux**, puis **18
contrôles compacts sous Linux et 18 sous Windows natif**. Le
[contrôle Windows ciblé](https://github.com/cedrick14/cartomize-python/actions/runs/41037116801/job/124000572042)
utilise exactement la commande compacte de production. Le cas raster à 12 px
ajouté après la suite locale porte les régressions nouvelles à **153** :
44 vectorielles, 58 raster, 14 interfaces publiques, 22 graphiques et 15 pour
le lecteur vectoriel. Le diagnostic de géométrie reste disponible en cas
d’échec. La matrice complète du commit final est suivie dans la PR nº 9.

Les **17 notebooks autonomes exécutent 115 cellules**, sans erreur, dans
des noyaux Jupyter neufs. La wheel 1.9.0 réussit **23 contrôles** après
installation isolée hors du dépôt, avec `pip check` réussi. Ses **96 modules
Python** correspondent exactement aux sources finales, y compris les deux
libellés corrigés. Le parcours local des notebooks précède ce dernier
ajustement graphique ; les moteurs et les cours sont inchangés, et la matrice
de la PR exécute également le parcours avec la révision livrée. Les deux leçons
demandant les données privées de `Tuto.zip` restent hors de la passe autonome.

Les [contrôles G06 sur données réelles](VALIDATION_G06_REAL.json) réussissent
**12 contrôles, sans échec**. Pour chacun des quatre formats vectoriels,
les **80 quartiers de Paris, 240 valeurs attributaires et 8 366 couples de
coordonnées** sont comparés au JSON d’origine. SQLite/WKB et DBF/SHP sont
relus indépendamment du moteur de conversion. Les quatre conversions des
extraits Sentinel comparent **53 248 valeurs et autant de masques**, avec
grille et métadonnées conservées. Un cas analytique distinct vérifie les
4 096 pixels d’un COG, son compagnon PAM et leur reprise depuis un projet
portable après retrait des chemins d’origine. Les six fichiers sources
conservent leurs empreintes.

Le [rapport de livraison 1.9.0](VALIDATION_1.9.0.json) contient les résultats,
les empreintes des modules et des scripts, les versions des bibliothèques
et les limites. Le [guide G06](DATA_CONVERSION.md) décrit les paramètres et
les changements admissibles. Les contrôles GitHub restent attachés aux
commits testés dans la demande d’intégration.

## Cartomize 1.7.0 — M10, harmonisation et fusion de couches

La suite complète finale réussit **1 074 tests, avec 2 exclusions prévues et
aucun échec**, en **197,43 s** sous Linux / Python 3.12.14. Les **134 nouvelles
régressions** sont incluses : 84 pour le moteur, 10 pour le terminal, les plans
et les tableaux, 26 pour la fenêtre, et 14 pour la compatibilité du lecteur.
Les exclusions portent sur le matériel CUDA et le moteur QGIS natif locaux.

Les **15 notebooks autonomes exécutent 97 cellules** dans des noyaux neufs,
en **47,85 s cumulées**. La wheel 1.7.0 réussit **17 contrôles** après installation
isolée hors du dépôt. Ses **93 modules Python** sont identiques aux sources
testées ; `pip check` et Twine strict réussissent. La suite finale et les
notebooks utilisent les sources figées après la correction de compatibilité SQL.

Le [rapport réel M10](VALIDATION_M10_REAL.json) conserve **12 contrôles réussis,
0 échec**, en **2,535 s**, après arrêt des sources pour l’intégration, le
26 octobre 2026 à **20 h 40 UTC**. Les empreintes des deux fichiers d’entrée
épinglés et des **93 modules Python** restent inchangées pendant cette exécution.
Le rapport conserve l’empreinte du script et les empreintes applicatives,
confirmées après l’exécution ; le commit de base `4fbd322` précède M10 et ne
désigne pas à lui seul les sources de cette validation.

Les références sont calculées directement depuis les JSON sources. SQLite
contrôle chaque attribut, son type et la provenance enregistrée ; un lecteur
indépendant du binaire GeoPackage contrôle les coordonnées. Les **3 687 visites
minières**, leurs **658 effectifs manquants** et leurs **44 zéros** sont conservés.
Les **80 quartiers parisiens et 8 366 couples de coordonnées** restent identiques.
Le contrôle de deux copies distinctes conserve leurs 160 polygones ; la fusion
ne les dissout pas.

Les variantes de schéma et la conversion volontairement invalide sont des
entrées dérivées identifiées dans le rapport. Les politiques de refus,
conversion vers une valeur nulle, champ absent et valeur par défaut sont
contrôlées sans modifier les sources épinglées. La
[note 1.7.0](RELEASE_1.7.0.md) détaille cette validation et ses limites.

Le [cours 16](../tutorials/notebooks/16_harmonisation_fusion_vectorielle.ipynb)
réussit dans un noyau Jupyter neuf : **8 cellules, aucune erreur, 3,14 s**.
Il comprend la lecture SQLite des attributs, les deux politiques de conversion
et une chaîne de fusion puis tampons. Ses résultats sont enregistrés.

Le [rapport de livraison](VALIDATION_1.7.0.json) suit séparément la suite complète,
les 15 notebooks autonomes et le paquet installé. Les contrôles distants restent
attachés aux commits de la demande d’intégration dans GitHub Actions.

## Cartomize 1.6.0 — M09, reprojection vectorielle par lot

La suite locale complète valide **940 tests, avec 2 exclusions prévues et
aucun échec** sous Linux / Python 3.12.14. Les 74 nouvelles régressions M09
sont incluses. Les exclusions concernent le matériel CUDA indisponible et
le moteur QGIS natif, qui possède un contrôle distant dédié.

Cette suite complète correspond au commit `51201b9`. La seule modification
ultérieure du code ajoute un retour à la ligne dans une case à cocher. Les
17 tests de la fenêtre, les contrôles du paquet installé et les essais réels
sont réexécutés après ce changement ; la matrice distante couvre le commit final.

Les **14 notebooks autonomes** exécutent **89 cellules** dans des noyaux neufs,
en **50,56 s cumulées**. La wheel 1.6.0 est installée et utilisée dans un
environnement neuf hors du dépôt : ses **14 contrôles** API/fenêtre/console
réussissent, et ses **90 modules Python** sont identiques aux sources testées.

Le [rapport M09 sur données réelles](VALIDATION_M09_REAL.json) enregistre
**12 contrôles réussis, 0 échec**, en **6,824 s** le 26 octobre 2026.
Les trois jeux épinglés comprennent 80 quartiers parisiens, 3 687 relevés
miniers et 50 aires protégées de RDC. Les 10 fichiers d’entrée et les 90 modules
Python conservent leurs empreintes pendant l’exécution.

Les coordonnées Web Mercator de tous les sommets parisiens et de tous les sites
miniers sont confrontées aux équations calculées avec NumPy, sans appel de
référence à PROJ. Les écarts maximaux sont de **4,657 × 10⁻⁹ m** et
**1,761 × 10⁻⁹ m**. Le SCR Mercator personnalisé des aires protégées est
contrôlé par un appel direct séparé au même moteur PROJ. Les attributs, les
types géométriques, les choix explicites, les sorties multicouches, les
emprises et l’absence de publication partielle sont également vérifiés.
La [note 1.6.0](RELEASE_1.6.0.md) précise les références et la portée.

Le [cours 15](../tutorials/notebooks/15_reprojection_vectorielle_par_lot.ipynb)
réussit dans un noyau Jupyter indépendant : **8 cellules, aucune erreur,
4,22 s**. Le parcours autonome comprend 14 notebooks et 89 cellules.
Les résultats de la suite complète, du parcours réexécuté et du paquet installé
sont consignés séparément dans le [rapport de livraison](VALIDATION_1.6.0.json).
Les contrôles distants Windows/Ubuntu et QGIS restent associés au commit testé
dans [GitHub Actions](https://github.com/cedrick14/cartomize-python/actions).

Les sections suivantes et leurs rapports conservent les preuves historiques
de chaque version, avec leur propre code et leurs propres distributions.

## Cartomize 1.5.0 — M08, qualité vectorielle

La suite locale initiale, révision
[93954d9](https://github.com/cedrick14/cartomize-python/commit/93954d934d6e2c82330f54fce06ea63577ea7ba3),
compte **865 tests réussis, 2 exclus, 0 échec**, en 176,94 s sur Python 3.12.
Les 136 tests ajoutés pour G01–G03 et leurs interfaces sont inclus dans ce total.
Le cours 14 exécute huit cellules et les essais sur trois jeux réels épinglés
réussissent leurs onze contrôles. La wheel est installée dans un environnement
neuf hors des sources, puis utilisée par l’API, la fenêtre et sa console.

Les preuves et conventions figurent dans la [note 1.5.0](RELEASE_1.5.0.md),
le [rapport machine](VALIDATION_1.5.0.json) et le
[rapport sur données réelles](VALIDATION_M08_REAL.json). Les états de GitHub
Actions restent attachés à la demande d’intégration et ne sont pas assimilés
aux résultats locaux. Les validations 1.4.0 et antérieures suivent ci-dessous.

Les premiers contrôles Windows ont révélé un débordement horizontal d’un pixel
dans le formulaire compact de qualité vectorielle à 12 px. La révision
[d2889cb](https://github.com/cedrick14/cartomize-python/commit/d2889cb273f8387ecced75832247643a0b8bccd8)
autorise le retour à la ligne des titres, dont la largeur minimale imposée par
les métriques Windows dépassait celle du panneau. Le contrôle conserve
l’exigence d’absence de défilement horizontal après la mise en page et vérifie
les dimensions nécessaires à la lecture complète du titre. **19 tests
graphiques ciblés** passent après cette correction, en 19,876 s, sans échec ni
exclusion. Ils comprennent un nouveau cas avec un titre à 32 px, qui reproduit
le débordement même lorsque les polices du système sont plus étroites.
Le rapport machine distingue ces contrôles de la suite locale initiale de
865 tests et conserve les empreintes ainsi que la vérification isolée de la
wheel reconstruite, installée et exécutée avec succès dans un nouvel
environnement hors des sources. La
[matrice Windows/Ubuntu et QGIS de cette révision](https://github.com/cedrick14/cartomize-python/actions/runs/40364248966)
conserve les journaux d’exécution ; les conclusions vérifiées sont regroupées
dans la [demande d’intégration nº 5](https://github.com/cedrick14/cartomize-python/pull/5),
avec les contrôles des notebooks Windows/Ubuntu.


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
