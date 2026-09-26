# Validation du parcours

Le parcours utilise Cartomize 1.0, révision du paquet 1.0.1.

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
