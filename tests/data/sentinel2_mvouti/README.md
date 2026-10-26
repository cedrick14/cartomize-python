# Référence Sentinel-2 réelle — Mayombe

**Contains modified Copernicus Sentinel data 2026.** Données publiques ESA / Copernicus, distribuées par Element 84 Earth Search. La [notice Sentinel](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) autorise la reproduction, la distribution et l’adaptation avec attribution. Les termes du code Cartomize ne remplacent pas cette notice pour ces données.

Les trois GeoTIFF sont des extraits sans rééchantillonnage : rouge et proche infrarouge de 128 × 128 pixels à 10 m, SCL de 64 × 64 pixels à 20 m. Les entiers des pixels sont inchangés. Seuls l’emprise, le conteneur et les métadonnées de sous-ensemble ont été adaptés. Le centre est 12,6° E / 4,2° S, dans le Mayombe. Ces observations ne sont ni des pixels synthétiques ni un jeu de validation d’occupation du sol.

Source : [S2C_33MTR_20260721_0_L2A](https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/S2C_33MTR_20260721_0_L2A), acquisition du 21 juillet 2026. Le fichier `provenance.json` conserve les URL des COG, fenêtres natives, empreintes, paramètres, nombres de pixels et référence de comparaison.

## Contrôle radiométrique indépendant

Le COG historique annonce `earthsearch:boa_offset_applied=true` tout en conservant un offset STAC de −0,1. Le [fournisseur a documenté cette incohérence](https://github.com/Element84/earth-search/issues/9#issuecomment-1663252010). Cartomize conserve cette déclaration dans le manifeste et applique un offset effectif nul uniquement au profil COG historique concerné. Cette règle ne concerne pas les JP2 bruts, la collection C1 ou les autres produits Sentinel.

Le même extrait a été lu séparément dans la [collection C1](https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/S2C_T33MTR_20260721T093314_L2A). Ses deux fichiers réellement téléchargés sont conservés sous `reference/`, avec leurs empreintes dans la provenance. Le produit ESA est identique : `S2C_MSIL2A_20260721T092031_N0512_R093_T33MTR_20260721T143510.SAFE`. Chaque pixel C1 des deux bandes est exactement supérieur de 1 000 DN au COG historique. Les transformations `C1 × 0,0001 − 0,1` et `historique × 0,0001` donnent donc les mêmes réflectances. La comparaison porte sur 32 768 valeurs, avec la même grille. Le test relit les deux sources distinctes et ne reconstruit pas la référence à partir de l’entrée.

Résultats de référence : 16 384 pixels utiles, moyenne rouge 0,07378505859375 et moyenne proche infrarouge 0,2001044860839844. Les classes SCL présentes sont 2, 4, 5 et 7. Le contrôle porte sur le fonctionnement du masque configuré ; ces classes ne constituent pas une garantie indépendante d’absence de nuages.

## Reproduction

Les fenêtres sont `[3294, 6404, 128, 128]` pour le rouge/NIR et `[1647, 3202, 64, 64]` pour SCL, exprimées en colonne, ligne, largeur, hauteur. Une lecture `rasterio.open('/vsicurl/' + href).read(1, window=Window(*window))` retrouve les pixels natifs. Conserver la transformation de fenêtre, le SCR et NoData. Les extractions réalisées le 26 octobre 2026 ont utilisé des requêtes HTTP Range : 3 063 808 octets pour le jeu principal et 3 031 040 octets pour la comparaison C1. Les tests ordinaires utilisent les extraits présents dans le dépôt et n’accèdent pas au réseau.
