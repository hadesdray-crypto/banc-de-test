# Banc de test

Teste des applis Android sur des téléphones et tablettes virtuels, avec un robot qui touche tous les boutons, gratte, fait défiler, tourne l'écran, coupe la connexion et joue des gestes au hasard.

- **Lancer** : onglet *Actions* → *Banc de test Android* → *Run workflow*, ou demander à Claude.
- **Résultats** : tableau de bord `docs/index.html` (vert / rouge), détails dans le rapport de l'exécution.
- **Applis testées** : `apps.json`. **Appareils** : `profiles.json`.
- Aucune donnée personnelle dans ce dépôt. Les captures d'écran ne sont publiées que si `publier_captures` vaut `true`.

## Règle de fonctionnement (décidée par le propriétaire)
Quand le banc trouve un défaut qu'il est possible de corriger, il est corrigé tout de suite, sans demander,
dans le même style de l'appli ; puis la série est relancée, et on recommence jusqu'à 0 défaut.
Seul ce qu'un robot ne peut pas faire (écouter, parler, juger le « joli », vrais Samsung) est listé
« À TESTER PAR TOI » dans le rapport. Uniquement des outils gratuits.
