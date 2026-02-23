from flask_sqlalchemy import SQLAlchemy

# Creamos la instancia de SQLAlchemy sin pasarle la aplicación aún.
# Esto nos permite importar 'db' en otros archivos (como models.py)
# sin causar errores de importación circular.
db = SQLAlchemy()