from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import re

app = Flask(__name__)
# Configuration de la base de données SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///access_control.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# MODÈLES DE BASE DE DONNÉES
# ==========================================

class Card(db.Model):
    __tablename__ = 'cards'
    id = db.Column(db.String(50), primary_key=True)
    level = db.Column(db.Integer, nullable=False)
    owner = db.Column(db.String(100), nullable=False)

    def to_dict(self):
        return {"id": self.id, "level": self.level, "owner": self.owner}

class CardReader(db.Model):
    __tablename__ = 'cardReaders'
    id = db.Column(db.String(50), primary_key=True)
    level = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {"id": self.id, "level": self.level}

class Log(db.Model):
    __tablename__ = 'logs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cardId = db.Column(db.String(50), nullable=False)
    cardreaderId = db.Column(db.String(50), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    levelInScan = db.Column(db.Integer, nullable=False)
    access_granted = db.Column(db.Boolean, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "cardId": self.cardId,
            "cardreaderId": self.cardreaderId,
            "date": self.date.isoformat(),
            "levelInScan": self.levelInScan,
            "access_granted": self.access_granted
        }

# Création automatique des tables si elles n'existent pas
with app.app_context():
    db.create_all()

# ==========================================
# ROUTES ADMIN : Utilisateurs (Cards)
# ==========================================

@app.route('/admin/cards', methods=['POST'])
def add_card():
    data = request.json
    if Card.query.get(data['id']):
        return jsonify({"error": "Card already exists"}), 400
    new_card = Card(id=data['id'], level=data['level'], owner=data['owner'])
    db.session.add(new_card)
    db.session.commit()
    return jsonify(new_card.to_dict()), 201

@app.route('/admin/cards/<card_id>', methods=['GET', 'PUT', 'DELETE'])
def manage_card(card_id):
    card = Card.query.get(card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404

    if request.method == 'GET':
        return jsonify(card.to_dict())
    
    elif request.method == 'PUT':
        data = request.json
        card.level = data.get('level', card.level)
        card.owner = data.get('owner', card.owner)
        db.session.commit()
        return jsonify(card.to_dict())
    
    elif request.method == 'DELETE':
        db.session.delete(card)
        db.session.commit()
        return jsonify({"message": "Card deleted"})

@app.route('/admin/cards/search', methods=['GET'])
def search_cards():
    pattern = request.args.get('regex', '.*')
    cards = Card.query.all()
    # Filtrage Regex en Python
    regex = re.compile(pattern, re.IGNORECASE)
    result = [c.to_dict() for c in cards if regex.search(c.id) or regex.search(c.owner)]
    return jsonify(result)

# ==========================================
# ROUTES ADMIN : Lecteurs de cartes (CardReaders)
# ==========================================

@app.route('/admin/readers', methods=['POST'])
def add_reader():
    data = request.json
    if CardReader.query.get(data['id']):
        return jsonify({"error": "Reader already exists"}), 400
    new_reader = CardReader(id=data['id'], level=data['level'])
    db.session.add(new_reader)
    db.session.commit()
    return jsonify(new_reader.to_dict()), 201

@app.route('/admin/readers/<reader_id>', methods=['GET', 'PUT', 'DELETE'])
def manage_reader(reader_id):
    reader = CardReader.query.get(reader_id)
    if not reader:
        return jsonify({"error": "Reader not found"}), 404

    if request.method == 'GET':
        return jsonify(reader.to_dict())
    
    elif request.method == 'PUT':
        data = request.json
        reader.level = data.get('level', reader.level)
        db.session.commit()
        return jsonify(reader.to_dict())
    
    elif request.method == 'DELETE':
        db.session.delete(reader)
        db.session.commit()
        return jsonify({"message": "Reader deleted"})

@app.route('/admin/readers/search', methods=['GET'])
def search_readers():
    pattern = request.args.get('regex', '.*')
    readers = CardReader.query.all()
    regex = re.compile(pattern, re.IGNORECASE)
    result = [r.to_dict() for r in readers if regex.search(r.id)]
    return jsonify(result)

# ==========================================
# ROUTES ADMIN : Logs
# ==========================================

@app.route('/admin/logs/search', methods=['GET'])
def search_logs():
    pattern = request.args.get('regex', '.*')
    limit = int(request.args.get('limit', 100))
    
    logs = Log.query.order_by(Log.date.desc()).all()
    regex = re.compile(pattern, re.IGNORECASE)
    
    result = []
    for log in logs:
        # On peut chercher la regex dans cardId ou cardreaderId
        if regex.search(log.cardId) or regex.search(log.cardreaderId):
            result.append(log.to_dict())
            if len(result) >= limit:
                break
                
    return jsonify(result)

# ==========================================
# ROUTE PUBLIQUE : SCAN CHECK
# ==========================================

@app.route('/scan', methods=['POST'])
def check_scan():
    """Vérifie si une carte a accès à un lecteur spécifique."""
    data = request.json
    card_id = data.get('cardId')
    reader_id = data.get('readerId')

    if not card_id or not reader_id:
        return jsonify({"valid": False}), 400

    card = Card.query.get(card_id)
    reader = CardReader.query.get(reader_id)

    # Déterminer si l'accès est valide
    is_valid = False
    level_in_scan = 0
    
    if card and reader:
        level_in_scan = reader.level
        if card.level >= reader.level:
            is_valid = True

    # Logger l'action
    new_log = Log(
        cardId=card_id, 
        cardreaderId=reader_id, 
        levelInScan=level_in_scan, 
        access_granted=is_valid
    )
    db.session.add(new_log)
    db.session.commit()

    # Afficher dans la console (print)
    print(f"[{datetime.now()}] SCAN - Card: {card_id} | Reader: {reader_id} | Granted: {is_valid}")

    # Réponse minimaliste sans détails comme demandé
    return jsonify({"valid": is_valid})

if __name__ == '__main__':
    # host='0.0.0.0' permet d'accepter les connexions venant d'autres appareils
    app.run(host='0.0.0.0', port=5000, debug=True)