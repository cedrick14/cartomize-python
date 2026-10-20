# Cartomize 1.1.0

## Interface

La fenêtre regroupe l’explorateur de projet, les vingt pages de traitement, les résultats cartographiques et la console Python. Les menus, les raccourcis et la barre d’outils utilisent les mêmes traitements que l’API existante.

Les thèmes Clair, Sombre et Système sont mémorisés. La taille du texte, la position des panneaux et le répertoire de travail sont enregistrés dans les préférences locales.

## Données et projets

Les fichiers importés sont disponibles pour la visualisation et le transfert aux traitements compatibles. Les projets JSON et CMZ s’ouvrent depuis l’explorateur. La disposition des anciennes sessions est convertie sans changement des paramètres scientifiques.

Les vues de comparaison conservent une surface cartographique minimale et ne peuvent plus être réduites à une largeur nulle. Leur emprise reste synchronisée lors du zoom.

## Console

Le noyau Python conserve ses variables, affiche les sorties et les erreurs et peut être interrompu sans fermer Cartomize. Il est arrêté lors de la fermeture de la fenêtre. Les scripts ne sont exécutés que sur demande explicite.

## Distribution et validation

Le numéro 1.1.0 distingue cette interface des paquets 1.0.1 déjà distribués. La préparation d’une archive ne publie pas automatiquement sur PyPI.

La validation exécute les tests unitaires et d’intégration sous Windows et Linux, produit les captures de la fenêtre réelle, construit les archives et réinstalle le wheel dans un environnement virtuel isolé. Ce dernier contrôle vérifie l’importation, les traitements NDVI et tampon, les exports PDF/PNG/SVG et le noyau de console depuis le paquet installé.

Les contrôles spécialisés CUDA et QGIS natif restent conditionnés à la présence de ces environnements. Le fonctionnement standard de Cartomize est indépendant de ces options.
