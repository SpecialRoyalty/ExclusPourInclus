Remplace ces fichiers dans ton projet Railway :

- main.py
- utils.py
- models.py
- database.py

Cette version ajoute :
- statistiques admin
- broadcast acceptés / créateurs / acheteurs / VIP / abandonnés / bloqués
- une seule demande pending par utilisateur
- verrouillage de décision admin : si un admin a déjà validé/refusé, un autre admin reçoit “Décision déjà prise”
- migrations automatiques pour block_reason
