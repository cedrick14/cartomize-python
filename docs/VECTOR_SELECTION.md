# Extraction attributaire et spatiale — M12 / G07

G07 sélectionne des **enregistrements entiers** et conserve aussi tous les
enregistrements exclus. Chaque décision est expliquée dans un rapport séparé.
Les critères peuvent porter sur plusieurs attributs, sur la localisation,
ou sur les deux. La sélection ne découpe pas les géométries.

Le moteur commun est `cartomize.extract_features`, enregistré sous
`vector.extract_features` pour les plans, le terminal et la fenêtre.
Les fonctions historiques `select_attributes` et `select_location` restent
disponibles et renvoient directement une couche GeoDataFrame.

## Python : préparer les critères et examiner le résultat

```python
import cartomize as cm

resultat = cm.extract_features(
    "visites.gpkg",
    layer="visites",
    filters=[
        {"field": "projet", "comparison": "contains", "value": "IPIS"},
        {"field": "effectif", "comparison": "gt", "value": 0},
        {"field": "date_visite", "comparison": "ge", "value": "2020-01-01"},
    ],
    attribute_match="all",
    mask="aires_protegees.gpkg",
    mask_layer="aires",
    predicate="within",
    combination="and",
)

retenus = resultat.data
exclus = resultat.rejected
decisions = resultat.report
print(resultat.summary)
```

Les chemins locaux et les GeoDataFrame sont acceptés. Un fichier multicouche
exige le nom de couche explicite ; `mask_layer` concerne le masque et `layer`
la source. Le SCR doit être défini. Les objets fournis ne sont pas modifiés.
Un identifiant métier peut être choisi avec `id_field` ; il doit alors être
unique et renseigné. Sans identifiant métier, les positions sources restent
la correspondance de référence.

Les deux partitions conservent les colonnes, valeurs, géométries, SCR et
ordre relatifs de la source. En mémoire, leurs index et types sont également
conservés. Un index dupliqué ne fusionne pas deux lignes : les décisions sont
calculées par position. Aucun champ de diagnostic n'est injecté dans les
attributs métier.

## Critères attributaires

Chaque élément de `filters` est un objet `field`, `comparison`, `value`.
`value` peut être omis pour `is_null` et `not_null`. Les noms de champs sont
exacts ; le champ de géométrie ne constitue pas un attribut filtrable.

| Comparaison | Sens |
|---|---|
| `eq`, `ne` | Égal, différent |
| `lt`, `le`, `gt`, `ge` | Inférieur, inférieur ou égal, supérieur, supérieur ou égal |
| `contains`, `starts_with` | Texte littéral contenu, préfixe littéral ; aucune expression régulière |
| `in`, `not_in` | Appartenance, non-appartenance à une liste de valeurs |
| `is_null`, `not_null` | Valeur manquante, valeur renseignée |

Les entiers signés ou non signés de 64 bits sont comparés sans passage par
un flottant. Un seuil décimal peut être fourni comme texte pour conserver
tous ses chiffres. Les champs booléens demandent de vrais booléens ; un
texte `"false"` ou le nombre `0` ne remplace pas implicitement `False`.
Les dates natives acceptent des dates ISO `AAAA-MM-JJ`. Les horodatages
textuels doivent aussi être ISO explicites ; les valeurs relatives comme
`now`, les heures seules et les dates ambiguës à barres sont refusées.
Les colonnes numériques objet ou catégorielles conservent également leurs
grands entiers lors de la comparaison. Un horodatage n'est
pas tronqué pour devenir une date ; les heures et fuseaux sont contrôlés
pour les champs temporels. Une date lue depuis GeoPackage reste utilisable
dans un critère après sa restitution en type natif.

Une comparaison ordinaire n'attribue pas une valeur numérique aux manquants.
Utiliser `is_null` ou `not_null` pour les cibler explicitement. Le rapport
indique les valeurs manquantes séparément des critères non satisfaits.
Une liste `in` contenant explicitement `null` en JSON ou `None` en Python
sélectionne aussi les manquants ; `not_in` les exclut toujours.
Les paramètres ne sont jamais exécutés comme du Python ou du SQL.

## Combiner les critères

`attribute_match="all"` exige tous les critères attributaires ; `"any"`
accepte au moins un critère. Quand les deux blocs sont présents,
`combination="and"` exige aussi le prédicat spatial et `"or"` accepte
l'un des deux blocs. `invert=True` inverse le résultat final, une fois les
blocs évalués. Un seul bloc peut être utilisé ; au moins un est obligatoire.

| Bloc attributaire | Bloc spatial | Combinaison `and` | Combinaison `or` |
|---|---|---|---|
| Vrai | Vrai | Retenu | Retenu |
| Vrai | Faux | Exclu | Retenu |
| Faux | Vrai | Exclu | Retenu |
| Faux | Faux | Exclu | Exclu |

Le bilan conserve les quatre effectifs, avant inversion : `both`,
`attributes_only`, `spatial_only`, `neither`. Leur somme égale le nombre
d'entrées. Les totaux `output_features` et `rejected_features` correspondent
à la décision finale. Les nombres de correspondances de chaque critère et
de chaque bloc sont également conservés.

## Convention spatiale

Le prédicat est évalué dans le sens **géométrie source → réunion du masque**.
Les géométries présentes et non vides du masque sont réunies avant comparaison.
Les recouvrements du masque ne dupliquent jamais un enregistrement source.
Si les SCR diffèrent, le masque est transformé dans le SCR source ; la
géométrie source et son SCR de sortie restent identiques.

Les prédicats sont `intersects`, `within`, `contains`, `covers`, `covered_by`,
`touches`, `overlaps`, `crosses`, `disjoint`. `within` exclut un point posé
sur la frontière ; `covered_by` l'inclut. Les relations sont planaires et
ne constituent pas des mesures géodésiques. La reprojection géodésique
contrôlée peut être préparée séparément avec [G04](VECTOR_REPROJECTION.md).

Une géométrie source manquante ou vide ne satisfait aucun prédicat spatial,
y compris `disjoint`. Son état reste indiqué dans le rapport. Une inversion
finale ou un bloc attributaire combiné par `or` peut néanmoins la retenir.
Si la réunion du masque est vide, une géométrie source présente et non vide
est disjointe de cet ensemble vide ; les autres prédicats sont faux.
Les géométries invalides ou à coordonnées non finies sont refusées quand
le bloc spatial est actif. Le filtrage attributaire seul ne les répare pas
et ne les transforme pas. Utiliser [G01](G01_GEOMETRY_QUALITY.md) pour un
contrôle ou une réparation explicite.

Cette convention de réunion est propre au contrat Cartomize. La référence
[QGIS — sélection vectorielle](https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/vectorselection.html)
décrit les extractions et les relations par rapport aux entités du masque ;
elle ne garantit pas une équivalence universelle avec une réunion, notamment
pour `contains`, `within` et `disjoint` sur plusieurs polygones.

## Publication et réouverture

```python
livraison = cm.execute_operation(
    "vector.extract_features",
    {"data": "visites.gpkg", "layer": "visites",
     "filters": [{"field": "effectif", "comparison": "gt", "value": 0}]},
    "resultats/extraction_01",  # dossier neuf
)
print(livraison["products"])
```

| Produit nommé | Fichier | Contenu |
|---|---|---|
| `primary`, `data` | `data.gpkg` | Entités retenues, couche `features` |
| `rejected` | `rejected.gpkg` | Entités exclues, couche `features` |
| `report` | `report.csv` | Une décision par ligne source |
| `audit` | `audit.json` | Même audit, identifiants et index typés |
| `summary` | `summary.json` | Paramètres, critères, blocs et effectifs |
| Manifeste d'opération | `operation.json` | Chemins des produits et métadonnées |

Le rapport contient `source_row`, `source_index`, `source_id`, `output_row`,
`rejected_row`, les correspondances et motifs de chaque critère, les deux
blocs, `combined_match`, `selected`, `geometry_status` et `reason`.
Les positions sont **numérotées à partir de zéro**, dans l'ordre de la couche
lue. `output_row` ou `rejected_row` est renseigné selon la partition.
Ce lien ne dépend pas du FID interne d'un pilote SIG.

Le compagnon `report.csv.schema.json` permet à la fenêtre de conserver les
identifiants textuels comme `001` ou `NA`. Dans l'audit JSON, les identifiants
entiers sont des objets `{type: "integer", value: "..."}` afin de ne pas
perdre leurs chiffres dans un lecteur JavaScript. Les dates et les tuples
d'index possèdent aussi une représentation typée. Les attributs d'origine
restent disponibles dans les deux GeoPackage.

Les deux couches sont écrites et intégralement relues : attributs, géométries
WKB, coordonnées, dimensions, ordre, effectifs et SCR doivent être conservés.
Une partition vide reste une couche ouvrable avec son schéma. Les dates
natives restent des champs DATE. Une valeur non représentable par ce writer
(par exemple un entier hors plage GeoPackage ou un horodatage trop précis)
fait échouer la livraison ; elle n'est pas silencieusement convertie en texte.
Le dossier n'est publié qu'une fois tous les produits terminés. Une erreur,
une annulation ou un dossier déjà existant ne remplace aucun résultat source.

## Terminal, plans et interface

Enregistrer les critères dans `criteres.json`, puis :

```bash
cartomize extract-features visites.gpkg resultats/extraction_01 --layer visites --filters criteres.json --mask aires.gpkg --predicate within
```

La voie commune est aussi `cartomize process vector.extract_features
parametres.json resultats/extraction_01`. Dans un plan, `@selection:data` et
`@selection:rejected` peuvent alimenter deux étapes différentes, et les
produits `report`, `audit`, `summary` restent accessibles.

Dans **Vecteur → Extraction avec bilan**, choisir les couches, ajouter les
critères avec le formulaire, puis sélectionner les combinaisons et le dossier
de livraison. Les valeurs multiples se saisissent une par ligne. Les choix
du formulaire sont capturés au lancement ; modifier le formulaire ensuite
ne change pas le calcul en cours. Les boutons de résultats ouvrent les deux
couches et le rapport. Les paramètres et références sont conservés lors de
l'enregistrement de session, y compris dans un projet portable.

Le [cours 19](../tutorials/notebooks/19_extraction_attributaire_spatiale.ipynb)
exécute les combinaisons, l'inversion, les dates natives, la publication et
une chaîne réutilisant les exclus. Les contrôles sur Paris et la RDC sont
reproduits par `scripts/validate_vector_selection_real.py` ; leurs références
et limites sont consignées dans le rapport généré.
