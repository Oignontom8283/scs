
### 1. Gestion des Utilisateurs / Cartes (Cards)

#### Ajouter une carte
* **Méthode :** `POST`
* **Route :** `/admin/cards`
* **Corps (JSON) :**
  ```json
  {
    "id": "card_12345",
    "level": 2,
    "owner": "Jean Dupont"
  }
  ```

#### Obtenir, Modifier ou Supprimer une carte
* **Route :** `/admin/cards/<card_id>` (ex: `/admin/cards/card_12345`)
* **Méthodes :**
  * `GET` : Récupère les infos de la carte.
  * `DELETE` : Supprime la carte.
  * `PUT` : Modifie la carte. **Corps (JSON) :**
    ```json
    {
      "level": 3,
      "owner": "Jean D."
    }
    ```

#### Rechercher des cartes (via regex)
* **Méthode :** `GET`
* **Route :** `/admin/cards/search?regex=VOTRE_REGEX`
* **Exemple d'URL :** `/admin/cards/search?regex=^Jean` (Trouve tous les propriétaires dont le nom commence par "Jean").

---

### 2. Gestion des Lecteurs (CardReaders)

#### Ajouter un lecteur
* **Méthode :** `POST`
* **Route :** `/admin/readers`
* **Corps (JSON) :**
  ```json
  {
    "id": "reader_porte_A",
    "level": 2
  }
  ```

#### Obtenir, Modifier ou Supprimer un lecteur
* **Route :** `/admin/readers/<reader_id>` (ex: `/admin/readers/reader_porte_A`)
* **Méthodes :**
  * `GET` : Récupère les infos du lecteur.
  * `DELETE` : Supprime le lecteur.
  * `PUT` : Modifie le lecteur. **Corps (JSON) :**
    ```json
    {
      "level": 1
    }
    ```

#### Rechercher des lecteurs (via regex)
* **Méthode :** `GET`
* **Route :** `/admin/readers/search?regex=VOTRE_REGEX`
* **Exemple d'URL :** `/admin/readers/search?regex=porte` (Trouve tous les lecteurs contenant "porte" dans leur ID).

---

### 3. Consultation des Logs

#### Rechercher dans l'historique (via regex)
* **Méthode :** `GET`
* **Route :** `/admin/logs/search?regex=VOTRE_REGEX&limit=NOMBRE`
* **Paramètres d'URL :**
  * `regex` : L'expression régulière appliquée sur l'ID de la carte ou l'ID du lecteur (par défaut tout récupérer `.*`).
  * `limit` : Le nombre maximal de résultats voulus (par défaut `100`).
* **Exemple d'URL :** `/admin/logs/search?regex=card_12345&limit=10`

---

### 4. Action : Scanner une carte

#### Vérifier un accès
* **Méthode :** `POST`
* **Route :** `/scan`
* **Corps (JSON) :**
  ```json
  {
    "cardId": "card_12345",
    "readerId": "reader_porte_A"
  }
  ```
* **Réponse attendue :**
  ```json
  {
    "valid": true  // ou false si refusé/inexistant
  }
  ```
  *(Cette action enregistre automatiquement l'événement dans les Logs de l'API)*.

---

**Rappel :** N'oubliez pas d'ajouter le header HTTP `Content-Type: application/json` lorsque vous envoyez du JSON dans le corps de vos requêtes (pour les requêtes `POST` ou `PUT`).