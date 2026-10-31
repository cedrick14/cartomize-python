# Démonstration Cartomize — données Sentinel-2 L2A réelles

Ce dossier prépare la démonstration technique de Cartomize avec **des données satellitaires réelles**. Aucune image synthétique, valeur d'indice ou statistique n'est écrite à l'avance.

## Données

Le script `download_real_data.py` interroge le catalogue public **Earth Search** pour la collection **Sentinel-2 Level-2A** sur une période fixe de saison sèche. Il évalue la couche **SCL** sur l'emprise de démonstration et retient une scène dont la couverture réellement utilisable sur l'emprise est au moins de 95 %.

L'emprise est une petite **fenêtre d'analyse située à Kinshasa**. Elle sert uniquement à limiter le volume de données de la démonstration et n'est jamais présentée comme une limite administrative.

Après validation par GitHub Actions, ce dossier contient :

- `data/B02.tif` — bleu ;
- `data/B03.tif` — vert ;
- `data/B04.tif` — rouge ;
- `data/B08.tif` — proche infrarouge ;
- `data/SCL.tif` — Scene Classification Layer ;
- `data/aoi.geojson` — emprise de démonstration ;
- `data/source_item.json` — item STAC retenu avec les métadonnées utiles ;
- `data/scenes.json` — manifeste explicite lu par Cartomize ;
- `data/provenance.json` — identifiant de scène, date, nuages, URLs sources et empreintes SHA-256.

## Tutoriel Jupyter

Ouvrir `Tutoriel_Demonstration_Cartomize.ipynb` et exécuter les cellules dans l'ordre.

Le parcours vérifié est :

1. lecture de la provenance ;
2. contrôle des bandes, projections, résolutions et calibration ;
3. prétraitement automatique avec masque SCL et découpage sur la zone d'étude ;
4. composition en couleurs naturelles ;
5. calcul réel de **NDVI**, **NDWI** et **EVI** ;
6. statistiques exactes sur les indices ;
7. statistiques zonales NDVI ;
8. bilan des classes SCL ;
9. export des résultats et d'un fichier `metrics.json`.

La classification supervisée **n'est volontairement pas exécutée**, car ce jeu de démonstration ne contient pas de vérité terrain indépendante. Cartomize dispose du module, mais présenter une précision ou des classes thématiques sans échantillons de référence serait méthodologiquement incorrect.

## Interface graphique

Le même parcours est décrit dans [GUIDE_INTERFACE.md](GUIDE_INTERFACE.md).

## Mise en page

La fonction de mise en page n'est **pas utilisée dans cette démonstration**. Les résultats scientifiques sont produits en GeoTIFF/GeoJSON/CSV ; leur finalisation cartographique peut ensuite être faite dans QGIS, ArcGIS Pro ou CartoMAP. La stratégie d'échange de projet sera traitée séparément après la démonstration.

## Reproduire la préparation

Dans un environnement Cartomize 1.0 :

```bash
python demonstration-carto/download_real_data.py
jupyter nbconvert --to notebook --execute demonstration-carto/Tutoriel_Demonstration_Cartomize.ipynb \
  --output Tutoriel_Demonstration_Cartomize.ipynb --output-dir demonstration-carto
python demonstration-carto/verify_demo.py
```

Le workflow `.github/workflows/demonstration-carto.yml` exécute ces étapes sur GitHub et refuse de publier les résultats si les contrôles échouent.


## Diagnostic hybride des nuages

La démonstration exécute le masquage Sentinel-2 avec la couche SCL comme source de qualité principale. Lorsque B02, B03, B04, B08/B8A et B11 sont disponibles, Cartomize applique également un contrôle spectral de secours pour identifier des nuages visibles qui auraient été laissés dans des classes SCL non nuageuses. Le rapport conserve séparément les statistiques SCL, les détections spectrales supplémentaires et les pixels finalement rejetés.
