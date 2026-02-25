from flask_sqlalchemy import SQLAlchemy

# Instancia sin app: evita importación circular con models
db = SQLAlchemy()