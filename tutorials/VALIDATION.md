# Validation du parcours

Le parcours courant installe les sources **Cartomize 1.3.0** de la copie du dépôt utilisée. Les résultats historiques ci-dessous concernent le paquet 1.0.1 et sont conservés avec leur date ; ils ne constituent pas une validation de la version courante. Voir aussi la [validation 1.3.0](../docs/RELEASE_1.3.0.md).

## Résultats locaux du 26 octobre 2026 — sources 1.3.0

Sous Linux / Python 3.12.14, les cours **00 à 10 et 13** passent dans des noyaux Jupyter réels et indépendants : **12 notebooks, 73 cellules de code exécutées, aucun échec**. Les onze cours existants représentent 66 cellules ; le nouveau diagnostic en représente sept. Les fichiers des cours 00–07, 09 et 10 ont été vérifiés sans réécrire leurs sorties enregistrées. Les cours 08 et 13 conservent leurs nouvelles sorties.

Le cours 08 vérifie désormais la présence des opérateurs utiles et l’unicité de leurs identifiants, au lieu de figer un ancien total de 34. Le cours 13 contrôle successivement les lacunes, la recommandation, la mosaïque complète, le NDVI et la couverture des zones. `ipywidgets`, déclaré dans les dépendances du parcours, est nécessaire au cours 03.

L’édition HTML des 14 cours a été construite. Les cours privés 11 et 12 n’ont pas été réexécutés lors de cette vérification ; leurs données n’étaient pas fournies dans cet environnement. La disponibilité de Binder n’est pas testée. Le [rapport machine de la version](../docs/VALIDATION_1.3.0.json) conserve le périmètre des essais locaux ; les résultats Windows du parcours restent ceux des jobs GitHub Actions associés au commit.

## Résultats du 26 septembre 2026

Commit du parcours : `08d711189b77451f9c79e026063193e06dee6aa6`.

Le [workflow Tutoriels](https://github.com/cedrick14/cartomize-python/actions/runs/36277324209) a réussi sous Python 3.12 :

| Environnement | Parcours exécuté | Résultat |
|---|---|---|
| Ubuntu, noyaux Jupyter indépendants | Cours 00 à 10 | 11 notebooks réussis |
| Windows, noyaux Jupyter indépendants | Cours 00 à 10 | 11 notebooks réussis |
| Python 3.12 / IPython local, données fournies | Cours 11 et 12 | 2 notebooks réussis |

Lors de cette validation historique, la construction HTML a réussi sur les deux systèmes. Les deux cas réels ont été contrôlés localement sans redistribution de leurs données ou sorties dans le dépôt. L’exécution utilisait alors le paquet publié `cartomize==1.0.1` et l’intitulé **Version 1.0**. Les dépendances courantes installent désormais la copie des sources, et le cours 13 complète le parcours autonome.

## Vérifications

- Chaque notebook s’exécute dans un noyau indépendant, avec des entrées synthétiques régénérées et un nouveau dossier de sorties.
- Les contrôles portent sur les bandes, le SCR, la résolution, les masques, les codes, les superficies, les transitions, l’égalité de deux calculs et la présence des livrables.
- Les références de classification simulées sont séparées entre apprentissage et validation. Les scores ne constituent pas une validation sur le terrain.
- Le cours STAC utilise un serveur HTTP local de démonstration. La disponibilité d’un catalogue distant et de Binder est hors du périmètre de ces contrôles.
- Les cas Mvouti et okapis sont exécutés localement avec les fichiers fournis. Ils ne sont pas exécutés par le workflow public, qui ne dispose pas du ZIP.
- L’examen des cartes vérifie les titres, légendes, tables et rendus. Les mesures liées aux données sources restent soumises aux limites indiquées dans [DATA.md](DATA.md).

## Reproduire les contrôles

```bash
python tutorials/scripts/execute.py
python tutorials/scripts/execute.py --include-tuto
```

Le rapport `tutorials/site/execution.json` enregistre les notebooks exécutés, les durées, les erreurs éventuelles et les cours nécessitant les données locales. Le workflow [Tutoriels](https://github.com/cedrick14/cartomize-python/actions/workflows/tutorials.yml) conserve ce rapport.

Les fichiers source conservent les résultats enregistrés pour la lecture sur GitHub. Les figures de référence sont également accessibles dans `tutorials/gallery/`.
