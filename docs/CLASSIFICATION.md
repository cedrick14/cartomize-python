# Classification : références, identité des classes et modèles

Cartomize propose une classification supervisée par forêt aléatoire ou arbres
extrêmement aléatoires, puis une prédiction par blocs. Les K-moyennes produisent
des groupes spectraux dont l’interprétation thématique doit être attribuée par
l’expert. Les bandes du raster scientifique constituent les variables ; une
composition colorée étirée destinée à l’affichage ne remplace pas ce raster.

## Identité des classes

Le champ des classes est une nomenclature. Cartomize distingue le type de chaque
identifiant pour éviter les fusions involontaires :

| Références | Comportement |
|---|---|
| Nombre `1` et nombre `1.0` | Même classe, y compris entre apprentissage et validation. |
| Texte `"01"` et texte `"1"` | Deux classes distinctes ; les zéros initiaux sont conservés. |
| Nombre `1` et texte `"1"` | Deux classes distinctes. |
| Booléen `True` et nombre `1` | Deux classes distinctes. |
| Classe absente ou identifiant numérique non fini | Erreur explicite avant apprentissage. |

Les classes numériques entières comprises entre zéro inclus et `2**24` exclu
conservent leurs codes lorsque toutes les classes sont numériques. Dans les
autres cas, une affectation déterministe crée des codes entiers distincts à partir
de 1. Le champ `class_encoding` du rapport relie le type et la valeur source au
code produit. Les valeurs numériques y sont écrites comme texte afin de préserver
les grands identifiants dans les lecteurs JSON.

Le paramètre `label_column` fournit les noms lisibles de la légende. Il doit
attribuer un seul libellé à chaque classe canonique. Deux identifiants distincts
peuvent avoir des représentations textuelles proches : fournir des libellés
explicites facilite alors la lecture de la carte. La correspondance des classes
se fonde sur leurs identifiants typés, et non sur les libellés.

## Exemple Python et Jupyter

```python
import cartomize as cm

modele = cm.fit_classifier(
    "multibande_scientifique.tif",
    "apprentissage.gpkg",
    "classe",
    label_column="libelle",
    validation="validation_independante.gpkg",
    algorithm="random_forest",
    n_estimators=100,
    random_state=42,
)
print(modele.report["class_encoding"])
print(modele.report["validation"])

classification = cm.classify_landcover(
    "multibande_scientifique.tif", None, "resultats/classification",
    model=modele,
)
```

Le nouveau dossier contient `classification.tif`, `confidence.tif`,
`classification.json` et le modèle sous `model/`. La sortie de confiance décrit
la probabilité calculée par le modèle ; elle ne constitue pas une mesure
indépendante de l’exactitude cartographique.

Dans la fenêtre, choisir **Classification supervisée**, le raster, les références,
le champ des classes et, si disponible, la validation indépendante. L’opération
enregistrée `classify` utilise ce même moteur dans **Chaîne de traitements**,
`cm.execute_operation`, `cm.processing_plan` et `cartomize process`.

## Références spatiales et validation

Les références sont reprojetées vers le raster et échantillonnées sur sa grille.
Les recherches spatiales utilisent les quatre coins affines des blocs, ce qui
conserve les échantillons sur les images tournées ou cisaillées. Les contrôles de
recouvrement entre apprentissage et validation utilisent les mêmes emprises.

Des classes incompatibles sur un même pixel, des références sans pixel valide ou
un recouvrement de pixels entre apprentissage et validation entraînent une erreur.
Les entités ou groupes sont séparés avant l’échantillonnage. Une séparation de
groupes adaptée reste à définir par l’étude ; elle n’élimine pas automatiquement
l’autocorrélation spatiale. Lorsque les données ne permettent pas de constituer
une validation, le rapport l’indique au lieu de publier une précision inventée.

## Modèles existants et traçabilité

Les modèles `cartomize.classifier.v1` déjà enregistrés restent lisibles avec leurs
codes d’origine. Ils ne sont pas renumérotés. Les nouveaux modèles enrichissent le
rapport avec `class_encoding`, sans changer le format des arbres numériques NPZ
ni autoriser des objets Python sérialisés exécutables.

Un ancien rapport peut ne pas contenir cette table. Ses libellés ne permettent pas
de reconstituer avec certitude les types des identifiants d’origine. Conserver les
références d’apprentissage et le rapport avec le modèle.

Les régressions sont vérifiées par `tests/test_classification_integrity.py` et
`tests/test_classification_interfaces.py`, avec apprentissage réel, validation,
exécution en chaîne, commande terminal et rechargement du modèle.
