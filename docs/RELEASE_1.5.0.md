# Cartomize 1.5.0 — Qualité des données vectorielles

Le module **M08** termine les procédures **G01, G02 et G03** de l’inventaire.
Il ajoute quatre fonctions publiques et leurs opérateurs communs à Python,
Jupyter, au terminal, aux plans de traitement et à l’interface graphique.

## Changements

- **Diagnostic détaillé :** validité et motif GEOS, géométries manquantes,
  vides ou non finies, doublons exacts, identifiant et mesures par entité.
- **Réparation traçable :** méthodes linework/structure, décisions explicites
  pour les géométries manquantes/vides et changements de type, rapport
  avant/après et conservation séparée des exclusions.
- **Topologie :** doublons, chevauchements, lacunes, dépassements de référence,
  extrémités non raccordées et croisements non nœudés. Les trous légitimes,
  tolérances et seuils de surface sont explicites.
- **Doublons :** clés et/ou géométries, égalité exacte ou topologique,
  premier/dernier enregistrement suivant un tri stable ou exclusion de tout
  groupe répété, règles des valeurs manquantes et correspondance des décisions.
- **Fichiers :** GeoPackage, rapport CSV, synthèse JSON et manifeste dans un
  nouveau dossier publié atomiquement. Les attributs d’origine, notamment
  un champ métier nommé `fid`, sont conservés.
- **Fenêtre :** formulaires dans Traitements vectoriels, paramètres capturés
  avant exécution et produits intégrés à l’espace de résultats. La restauration
  d’un champ saisi dans une liste éditable est corrigée. Les formulaires
  tiennent dans une fenêtre de 1 100 × 740 pixels avec un texte de 12 ou 16 px.
- **Cours 14 :** huit cellules exécutables, données simulées, chaîne complète,
  mesures attendues et comparaison graphique.

Le [guide M08](VECTOR_QUALITY.md) précise les paramètres et conventions.
Le [cours 14](../tutorials/notebooks/14_qualite_vectorielle.ipynb) contient les
exemples exécutés. Les méthodes restent explicites : les changements de
coordonnées ne sont pas devinés et une impasse ne constitue pas à elle seule
une erreur métier.

## Vérifications

| Vérification | Résultat |
|---|---|
| Suite complète locale, Python 3.12 | **865 tests réussis**, 2 exclusions, 0 échec, 176,94 s |
| Tests ajoutés pour M08 et son intégration | **136 tests**, inclus dans la suite complète |
| Notebook 14 | **8 cellules exécutées**, 4,62 s |
| Données réelles épinglées | **11 contrôles réussis**, aucune mutation des sources |
| Paquet wheel installé dans un environnement neuf | Interface, 20 rubriques, trois thèmes, console, prétraitement optique, qualité vectorielle, exports et réouverture du projet réussis |

Les deux exclusions locales concernent CUDA sans matériel compatible et le
runtime QGIS natif non configuré. Les contrôles Windows/Ubuntu et QGIS de
GitHub Actions sont associés à la demande d’intégration, séparément de ces
résultats locaux. Le [rapport machine](VALIDATION_1.5.0.json) conserve les
empreintes des modules testés et du paquet installé.

### Données réelles

Le [rapport détaillé](VALIDATION_M08_REAL.json) et le
[script reproductible](../scripts/validate_vector_quality_real.py) utilisent
les instantanés historiques du tutoriel GeoPandas déjà employés dans le projet.
Les fichiers sources ne sont pas ajoutés au dépôt.

- **Aires protégées de RDC :** 50 entités, une auto-intersection à Itombwe
  détectée et réparée, 50 géométries valides après réparation. Les 49 géométries
  déjà valides sont conservées à l’identique, ainsi que les attributs.
- **Relevés miniers :** 3 687 visites conservées avec la clé site/date.
  La règle distincte « dernière visite par site » conserve 2 403 enregistrements
  entiers, y compris 292 effectifs manquants, et journalise les 1 284 exclusions.
- **Quartiers parisiens :** les 3 160 couples de 80 quartiers sont confrontés
  à une référence exhaustive. Sept fragments de recouvrement représentent
  0,0563243794 m² au total par paire ; aucun ne dépasse le seuil explicite de 1 m².

Ces contrôles partagent GeoPandas/GEOS avec Cartomize. Ils vérifient
l’intégration et la cohérence des résultats, sans constituer une certification
indépendante du moteur géométrique.

## Inventaire et suite

Les 123 procédures sont conservées : **14 disponibles, 46 partielles,
63 absentes**. Les quatre nouveaux opérateurs portent le registre à **48**.
Le bloc E01 reste en cours pour la reprojection par lot, l’harmonisation,
les échanges de formats, les grilles et les échanges raster-vecteur.
La prochaine procédure dans cet ordre est **G04 — Reprojection vectorielle
par lot**. Les autres statuts n’ont pas été relevés artificiellement.

## Installation

Depuis les sources GitHub téléchargées ou mises à jour :

```bash
python -m pip install -e ".[gui]"
python -m cartomize gui
```

Pour les cours :

```bash
python -m pip install -r tutorials/requirements.txt
python -m jupyterlab tutorials/notebooks
```

Cette version concerne les sources et les paquets construits et vérifiés.
Aucun paquet n’a été publié sur PyPI dans cette livraison.
