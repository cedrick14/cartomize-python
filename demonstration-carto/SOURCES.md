# Sources et traçabilité

## Imagerie

- Catalogue STAC : Earth Search, collection `sentinel-2-l2a`.
- Produit : Sentinel-2 Level-2A, réflectance de surface.
- Sélection : période fixe `2024-06-01/2024-09-30`, puis classement par pourcentage de pixels SCL utilisables sur l'emprise.
- Bandes utilisées : B02, B03, B04, B08 et SCL.

Le fichier `data/provenance.json`, généré pendant l'exécution, enregistre l'identifiant exact du produit, la date d'acquisition, la plateforme, la tuile MGRS, la couverture nuageuse déclarée, la couverture SCL mesurée sur l'emprise, les URLs des assets sources et les SHA-256 des fichiers locaux.

## Signification des bandes

- B02 : bleu
- B03 : vert
- B04 : rouge
- B08 : proche infrarouge
- SCL : classification de scène Sentinel-2 L2A

Les rôles spectraux et la calibration ne sont pas déduits de l'ordre des fichiers : Cartomize les lit dans les métadonnées STAC / produit et enregistre les paramètres appliqués dans ses rapports.

## Indices

Les formules utilisées sont celles enregistrées dans le catalogue Cartomize :

- NDVI : `(nir-red)/(nir+red)`
- NDWI (McFeeters) : `(green-nir)/(green+nir)`
- EVI : `2.5*(nir-red)/(nir+6*red-7.5*blue+1)`

Les références bibliographiques associées sont disponibles par `cartomize.list_indices()`.

## Ce qui n'est pas revendiqué

- l'emprise de démonstration n'est pas une limite administrative ;
- les groupes spectraux éventuels ne sont pas des classes d'occupation du sol sans validation ;
- aucune classification supervisée n'est présentée sans échantillons de référence ;
- aucune précision thématique n'est annoncée sans matrice de validation.
