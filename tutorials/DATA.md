# Données du parcours

## Jeux fournis dans Tuto.zip

| Jeu | Contenu vérifié | Utilisation | Information à compléter |
|---|---|---|---|
| `Mvouti_Composite_2024_2025_cloudmask.tif` | 3 833 × 5 140 pixels ; 6 bandes int16 ; EPSG:4326 ; blue, green, red, nir, swir1, swir2 | Composition colorée, superposition, groupes spectraux et atlas | Capteur, dates, méthode de composition, calibration et masque de qualité |
| `La Réserve de Faune à Okapis foret_RDC_2025.tif` | 12 329 × 16 895 pixels ; 1 bande uint8 ; EPSG:32634 déclaré ; aucun NoData déclaré | Inventaire exhaustif des codes et aperçu catégoriel | Signification des codes, statut du zéro, validation et géoréférencement |
| `Concession.shp` | 5 entités ; EPSG:32733 | Concessions dans l’emprise du composite, superficies planaires et atlas | Producteur, date de référence et licence |
| `CONGO_BZ_UTM_33S.shp` | 12 entités ; EPSG:32733 ; champs NAME_1 et GID | Contexte administratif | Source et version à confirmer ; les champs évoquent GADM sans établir la provenance |
| `WDPA_WDOECM_May2026_Public_13694_shp-polygons.shp` | 1 entité ; EPSG:4326 ; Dimonika, identifiant 13694 | Superposition locale du zonage fourni | Version conservée pour reproduire cet exercice ; consulter le producteur pour une utilisation actuelle |

Les superficies attributaires ne sont pas assimilées aux superficies recalculées. Après découpage, le cours mesure la partie située dans l’emprise de l’image, pas la superficie administrative totale de chaque concession. La limite rectangulaire du composite ne remplace pas la limite officielle du district.

Le raster d’Okapi est conservé dans son SCR déclaré. Sa position loin du méridien central de la zone UTM déclarée doit être vérifiée : aucune correction de SCR n’est déduite du seul nom du fichier. Les surfaces présentées sont des résultats planaires provisoires dans ce SCR.

## Calibration et nomenclature

Un facteur GDAL égal à 1 n’établit pas que le producteur a livré une réflectance. EVI, SAVI et les autres formules comportant des constantes ne doivent pas être appliqués au composite sans confirmation des unités. Même une différence normalisée demande de connaître les décalages et les conditions de validité. Le cours réel ne publie donc pas de carte NDVI prétendument calibrée.

Les cours d’indices utilisent une réflectance synthétique connue. Les références de classification, le MNT, le réseau et les deux dates de changement sont également simulés. Les résultats ne constituent ni des observations forestières ni une validation de terrain.

Le composite de Mvouti et le raster d’Okapi portent sur deux territoires différents. Ils ne sont pas fusionnés dans une mosaïque et ne forment pas une paire temporelle.

## Diffusion

Les fichiers du ZIP sont importés localement, sans être ajoutés au dépôt public. Cela conserve les conditions de leurs producteurs et évite une redistribution générale sous la licence du code.

- Protected Planet limite la redistribution des données brutes. Pour obtenir les données, consulter [Protected Planet](https://www.protectedplanet.net/) et ses [conditions](https://www.protectedplanet.net/en/legal). Attribution de la source fournie : UNEP-WCMC et IUCN, Protected Planet, WDPA/WDOECM, mai 2026. Le cours exploite cet extrait daté pour la reproduction de l’exercice, sans le présenter comme la version actuelle.
- Si la provenance GADM des divisions administratives est confirmée, ses [conditions](https://gadm.org/license.html) s’appliquent notamment à la redistribution et à l’usage commercial.
- La licence et la provenance du composite, du raster classé et des concessions doivent être documentées avant de diffuser leurs données sources.

Les cartes et tableaux des cas réels sont produits localement. Les géométries WDPA et administratives ne sont pas publiées comme données téléchargeables dans le parcours. La galerie publique repose sur les données synthétiques.

## Ajouter d’autres données

Remplacer les chemins et conserver les métadonnées. Pour chaque entrée, préciser : producteur, identifiant du produit, dates, SCR, résolution, unités, calibration, valeurs NoData, qualité, nomenclature, licence et URL d’origine. Les références d’apprentissage et de validation doivent être documentées séparément.
