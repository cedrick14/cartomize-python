# Cartomize 1.6.0 — Reprojection vectorielle par lot

Le module **M09** termine la procédure **G04** de l’inventaire. Il découvre
les couches d’un fichier, d’un dossier ou d’une liste de sources, présente
les opérations géodésiques disponibles, puis publie le lot reprojeté avec
les emprises, paramètres et opérations effectivement utilisés.

## Changements

- **Découverte multicouche :** lecture de chaque couche spatiale des fichiers
  compatibles, parcours facultatif des sous-dossiers et identifiants stables
  pour sélectionner les transformations et réutiliser les sorties.
- **Choix géodésique explicite :** catalogue par couche, précision annoncée,
  zone d’emploi, grilles nécessaires, meilleure opération disponible et
  opérations indisponibles. L’utilisateur peut retenir un identifiant précis.
- **Règles strictes par défaut :** meilleure opération exigée, transformations
  approximatives *ballpark* refusées et domaine des SCR/opérations contrôlé.
  Les assouplissements demandés sont enregistrés dans le manifeste.
- **Intégrité des données :** attributs, grands entiers et champ métier `fid`
  conservés ; sortie GeoPackage relue et contrôlée avant publication. Les
  coordonnées non finies et les écritures altérant les géométries sont refusées.
- **Livraison du lot :** un GeoPackage par couche, un bilan CSV et un manifeste
  JSON, dans un nouveau dossier publié atomiquement. Les emprises source et
  cible correspondent aux sommets réellement transformés.
- **Interfaces communes :** fonctions Python exportées par `cartomize`,
  opérateur `vector.reproject_batch` pour le terminal et les plans, formulaire
  graphique avec inspection et choix d’opération, produits nommés utilisables
  par une étape suivante avec `@etape:identifiant_de_couche`.
- **Cours 15 :** huit cellules autonomes, sources pédagogiques de SCR différents,
  contrôle indépendant des coordonnées, choix explicite, plan de tampons et
  comparaison graphique avant/après.
- **Archive source complète :** le parcours pédagogique et ses fichiers de
  support sont inclus, avec exclusion des sorties de cours générées.

Le [guide M09](VECTOR_REPROJECTION.md) décrit l’API et les conventions.
Le périmètre concerne les **transformations horizontales de SCR statiques à
deux axes**, dans l’ordre SIG x/y. Les valeurs Z sont conservées sans conversion
verticale. Les mesures M, SCR dynamiques, verticaux, composés ou géocentriques
sont refusés. La reprojection ne répare ni ne densifie les géométries et ne les
découpe pas automatiquement à l’antiméridien. Une précision exigée doit être
strictement positive ; `None` signifie qu’aucun filtre numérique n’est demandé.

## Vérifications locales de M09

| Vérification | Résultat observé le 26 octobre 2026 |
|---|---|
| Suite locale complète, Python 3.12 | **940 tests réussis**, 2 exclusions prévues, 0 échec |
| Régressions ajoutées pour M09 | **74 tests**, inclus dans la suite complète : 51 moteur, 6 terminal/plans, 17 fenêtre |
| Parcours autonome complet | **14 notebooks, 89 cellules exécutées**, 50,56 s cumulées dans des noyaux neufs |
| Wheel 1.6.0 installée hors des sources | **14 contrôles réussis**, environnement neuf, API/fenêtre/console ; 90 modules identiques aux sources vérifiées |
| Données réelles épinglées | **12 contrôles réussis**, 0 échec, 7,276 s |
| Intégrité des entrées et du code pendant ces contrôles | 10 fichiers d’entrée et 90 modules Python inchangés |
| Cours 15 dans un noyau Jupyter neuf | **8 cellules exécutées**, aucune erreur, 4,22 s |

Les deux exclusions de la suite générale concernent CUDA sans matériel adapté
et le moteur QGIS natif absent de cet environnement ; QGIS possède son job
dédié dans la matrice distante. Les contrôles de la wheel comprennent sa
relecture, `pip check` et `twine check --strict`. La restauration complète
des sessions existantes est vérifiée sans modifier son test historique.

Les premières exécutions Windows ont révélé deux débordements horizontaux du
formulaire compact. Les libellés complets des cases à cocher tiennent désormais
sur deux lignes. Une régression supplémentaire simule des caractères de 24 px
et vérifie que les cases reçoivent toute leur largeur et leur hauteur requises.
Les trois cas compacts sont exécutés au début des jobs Windows, puis inclus
dans la suite générale. La suite locale complète et l'installation isolée ont
été réexécutées après cette correction.

Le [rapport réel](VALIDATION_M09_REAL.json) conserve les références, versions,
empreintes SHA256 et résultats numériques. Le
[rapport de livraison 1.6.0](VALIDATION_1.6.0.json) regroupe séparément la suite
logicielle complète, la réexécution du parcours et le paquet installé. Les
résultats Windows/Ubuntu et QGIS distants sont ceux des jobs associés au commit
de la demande d’intégration dans [GitHub Actions](https://github.com/cedrick14/cartomize-python/actions).

### Comparaisons numériques sur données réelles

Les entrées sont les instantanés historiques du tutoriel GeoPandas, épinglés
dans le [script reproductible](../scripts/validate_vector_reprojection_real.py).
Les fichiers sources ne sont pas redistribués dans le dépôt.

| Jeu | Entités | Coordonnées vérifiées | Référence | Écart absolu maximal |
|---|---:|---:|---|---:|
| Quartiers parisiens | 80 | 8 366 | Équations Web Mercator calculées avec NumPy | 4,657 × 10⁻⁹ m |
| Relevés miniers de RDC | 3 687 | 3 687 | Équations Web Mercator calculées avec NumPy | 1,761 × 10⁻⁹ m |
| Aires protégées de RDC, Mercator personnalisé | 50 | 148 651 | Appel direct séparé à PROJ | 0 m |

Les deux premières comparaisons calculent les coordonnées attendues sans appel
à PROJ, à partir des [équations documentées](https://proj.org/en/stable/operations/projections/webmerc.html).
La troisième partage le moteur PROJ : elle vérifie l’intégration du SCR source
personnalisé, la conservation des 44 Polygon et 6 MultiPolygon et les attributs.
La tolérance numérique est de 2 × 10⁻⁶ m ; elle mesure un accord de calcul et
ne représente pas la précision géodésique des données de terrain.

Trois points publiés dans la documentation PROJ, en
[Web Mercator](https://proj.org/en/stable/operations/projections/webmerc.html)
et dans les [zones UTM 32 Nord et 59 Sud](https://proj.org/en/stable/operations/projections/utm.html),
passent aussi à leur précision imprimée de 0,01 m. Le contrôle couvre ensuite
la sélection explicite des trois opérations, la découverte d’un GeoPackage
multicouche, la conservation de Z et d’un entier supérieur à 2⁵³ et le refus
d’un lot dont une couche n’a pas de SCR, sans publication partielle.

## Inventaire et suite

Les **123 procédures** et les **88 références** sont conservées. Le bilan
devient **15 disponibles, 45 partielles et 63 absentes** ; G04 passe de partiel
à disponible dans le périmètre documenté. Le registre comprend **49 opérateurs**.
Le parcours compte **14 notebooks autonomes** et deux cas nécessitant les
données locales de `Tuto.zip`.

Le bloc **E01** reste en cours pour ses autres procédures. La prochaine dans
l’ordre de l’inventaire est **G05 — Harmonisation et fusion de couches**,
puis les autres échanges, tables, grilles et conversions raster-vecteur.
Les preuves historiques M08 restent attachées à la version 1.5.0.

## Installation et reproduction

Depuis la copie des sources GitHub :

```bash
python -m pip install -e ".[gui]"
python -m cartomize gui
python -m pip install -r tutorials/requirements.txt
python tutorials/scripts/execute.py --select 15
python scripts/validate_vector_reprojection_real.py --data .m09-cache --output reports/m09-real.json
```

Le dernier contrôle télécharge les fichiers épinglés si le cache est absent.
Le script vérifie leurs empreintes avant de calculer les sorties temporaires.
La publication sur PyPI est une étape distincte de la construction et de la
vérification des sources et des distributions de cette version.
