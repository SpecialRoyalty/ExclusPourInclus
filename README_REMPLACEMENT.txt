Remplacement safe depuis ta version qui fonctionnait.

Fichiers modifiés uniquement :
- main.py
- utils.py
- models.py
- database.py

Fonctions ajoutées :
- statistiques admin 📊
- broadcast vers formulaires abandonnés
- broadcast vers utilisateurs bloqués
- blocage des doublons : une seule demande pending par utilisateur
- verrouillage admin : si une décision est déjà prise, un autre admin reçoit “Décision déjà prise”
- migration automatique block_reason pour les stats de blocage
