# Validation du parcours

Le parcours courant installe les sources **Cartomize 1.5.0** de la copie du dépôt
utilisée. Les résultats des versions précédentes sont conservés ci-dessous avec
leur version et leur date ; ils ne constituent pas une nouvelle exécution de
tous les cours avec la version courante.

## Résultats locaux du 26 octobre 2026 — sources 1.5.0

Le nouveau [cours 14](notebooks/14_qualite_vectorielle.ipynb) a été exécuté
dans un véritable noyau Jupyter : **8 cellules, aucune erreur, 4,62 secondes**.
Il vérifie le diagnostic et la réparation des géométries, la déduplication,
la topologie et les produits d’une chaîne complète. Ses sorties sont enregistrées.
Le registre courant comprend **48 opérateurs**.

Le parcours autonome comprend désormais **13 notebooks (00 à 10, 13 et 14)**,
soit **81 cellules de code**. La réexécution complète sur Windows et Ubuntu
est suivie par le workflow de la demande d’intégration M08 ; le résultat local
ci-dessus concerne le cours 14. Les cours 11 et 12 nécessitent des données locales.
La [validation 1.5.0](../docs/VALIDATION_1.5.0.json) décrit aussi la suite
logicielle complète : **865 tests réussis et 2 exclusions**.

## Historique du 26 octobre 2026 — sources 1.4.0

Les cours **00 à 10 et 13** ont été exécutés dans des noyaux Jupyter réels
indépendants sous Linux / Python 3.12.14 : **12 notebooks, 73 cellules de code,
aucune erreur**. Les sorties corrigées des cours 00 et 13 sont enregistrées ;
les sorties historiques des autres fichiers sont conservées.

Le [cours 13](notebooks/13_diagnostic_automatique.ipynb), avec ses sept cellules,
utilise maintenant le [module M07](../docs/IMAGERY_AUTOMATIC.md) : la
première zone, couverte à **83,28 %** en données utiles, est refusée avec un
diagnostic conservé. Un second cas pédagogique distinct atteint **100 %** avec
deux scènes ; le moteur sélectionne la mosaïque, puis les cellules calculent le
NDVI et les statistiques zonales. Le registre de cette version comporte **44 opérateurs**.

Le cours 00 accepte explicitement les données pédagogiques partielles avec
`allow_partial=True`. Le seuil reste 100 %, le rapport vérifie `status="partial"`
et `threshold_met=False`, et le sous-titre de la carte annonce cette couverture
partielle. Cette acceptation pédagogique ne modifie pas le comportement strict
du module pour les autres utilisateurs.

La suite logicielle locale de cette version a également réussi : **722 tests
réussis, 2 ignorés**, en **163,27 secondes**. Les tests ignorés nécessitent CUDA
ou le runtime QGIS absent de cet environnement. Ce bilan ne décrit pas une
exécution Windows ni une disponibilité vérifiée de Binder ou de catalogues
distants. Voir la [validation courante](../docs/VALIDATION.md).

Les résultats des sections suivantes restent ceux de leurs versions respectives.
Les données privées des cours 11 et 12 n’ont pas été fournies pour cette
vérification 1.4.0. L’édition HTML des 14 cours est construite, en conservant les
sorties historiques de ces deux cours privés.

## Historique du 26 octobre 2026 — sources 1.3.0

Sous Linux / Python 3.12.14, les cours **00 à 10 et 13** passent dans des noyaux Jupyter réels et indépendants : **12 notebooks, 73 cellules de code exécutées, aucun échec**. Les onze cours existants représentent 66 cellules ; le nouveau diagnostic en représente sept. Les fichiers des cours 00–07, 09 et 10 ont été vérifiés sans réécrire leurs sorties enregistrées. Les cours 08 et 13 conservent leurs nouvelles sorties.

Le cours 08 vérifie désormais la présence des opérateurs utiles et l’unicité de leurs identifiants, au lieu de figer un ancien total de 34. Le cours 13 contrôle successivement les lacunes, la recommandation, la mosaïque complète, le NDVI et la couverture des zones. `ipywidgets`, déclaré dans les dépendances du parcours, est nécessaire au cours 03.

L’édition HTML des 14 cours a été construite. Les cours privés 11 et 12 n’ont pas été réexécutés lors de cette vérification ; leurs données n’étaient pas fournies dans cet environnement. La disponibilité de Binder n’est pas testée. Le [rapport machine de la version](../docs/VALIDATION_1.3.0.json) conserve le périmètre des essais locaux ; les résultats Windows du parcours restent ceux des jobs GitHub Actions associés au commit.

## Historique du 26 septembre 2026 — paquet 1.0.1

Commit du parcours : `08d711189b77451f9c79e026063193e06dee6aa6`.

Le [workflow Tutoriels](https://github.com/cedrick14/cartomize-python/actions/runs/36277324209) a réussi sous Python 3.12 :

| Environnement | Parcours exécuté | Résultat |
|---|---|---|
| Ubuntu, noyaux Jupyter indépendants | Cours 00 à 10 | 11 notebooks réussis |
| Windows, noyaux Jupyter indépendants | Cours 00 à 10 | 11 notebooks réussis |
| Python 3.12 / IPython local, données fournies | Cours 11 et 12 | 2 notebooks réussis |

Lors de cette validation historique, la construction HTML a réussi sur les deux systèmes. Les deux cas réels ont été contrôlés localement sans redistribution de leurs données ou sorties dans le dépôt. L’exécution utilisait alors le paquet publié `cartomize==1.0.1` et l’intitulé **Version 1.0**. Les dépendances courantes installent désormais la copie des sources, et les cours 13 et 14 complètent le parcours autonome.

## Vérifications

- Chaque notebook s’exécute dans un noyau indépendant, avec des entrées synthétiques régénérées et un nouveau dossier de sorties.
- Les contrôles portent sur les bandes, le SCR, la résolution, les masques, les codes, les superficies, les transitions, l’égalité de deux calculs et la présence des livrables.
- Les références de classification simulées sont séparées entre apprentissage et validation. Les scores ne constituent pas une validation sur le terrain.
- Le cours STAC utilise un serveur HTTP local de démonstration. La disponibilité d’un catalogue distant et de Binder est hors du périmètre de ces contrôles.
- Les cas Mvouti et okapis nécessitent les fichiers privés fournis localement. Leur validation historique est décrite ci-dessus ; ils n’ont pas été réexécutés avec la version 1.5.0 et ne sont pas exécutés par le workflow public, qui ne dispose pas du ZIP.
- L’examen des cartes vérifie les titres, légendes, tables et rendus. Les mesures liées aux données sources restent soumises aux limites indiquées dans [DATA.md](DATA.md).

## Reproduire les contrôles

```bash
python tutorials/scripts/execute.py
python tutorials/scripts/execute.py --include-tuto
```

Le rapport `tutorials/site/execution.json` enregistre les notebooks exécutés, les durées, les erreurs éventuelles et les cours nécessitant les données locales. Le workflow [Tutoriels](https://github.com/cedrick14/cartomize-python/actions/workflows/tutorials.yml) conserve ce rapport.

Les fichiers source conservent les résultats enregistrés pour la lecture sur GitHub. Les figures de référence sont également accessibles dans `tutorials/gallery/`.
