# Dépôt de la bibliothèque Python Cartomize

Projet : bibliothèque Python et interface graphique autonome Cartomize.
Dépôt : `cedrick14/cartomize-python`.
Paquet PyPI et module Python : `cartomize`.
Version préparée : `0.8.1a1`.

Ce projet est distinct du plugin QGIS. Il contient son propre `pyproject.toml`, ses sources sous `src/cartomize`, ses tests, sa documentation et ses workflows GitHub Actions à la racine.

Les modules scientifiques et l’interface graphique sont conservés à l’identique. La provenance des composants historiques, les licences et les crédits restent dans `NOTICE.md`, `docs/PROVENANCE.json` et `docs/BRANDING.md`. Les passerelles facultatives vers des moteurs SIG natifs sont des fonctionnalités d’interopérabilité ; elles ne constituent pas une dépendance pour le moteur autonome.

L’extraction provient de la version Python préparée au commit distant `182caf88565cf2e1f6af8c879e20dd12a240529f`. La PR d’intégration au dépôt du plugin a été fermée sans fusion et le workflow PyPI de cette branche a été retiré. Aucun fichier n’a été téléversé sur PyPI lors de cette première tentative.
