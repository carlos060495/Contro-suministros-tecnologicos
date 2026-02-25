from db import db
from flask_login import UserMixin
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

# UserMixin provee is_authenticated, is_active, get_id
class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(20), default='cliente')
    activo = db.Column(db.Boolean, default=True)

    def set_password(self, password_plana):
        self.password = generate_password_hash(password_plana)

    def check_password(self, password_plana):
        return check_password_hash(self.password, password_plana)

class Proveedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_empresa = db.Column(db.String(100), nullable=False)
    cif = db.Column(db.String(20), unique=True)
    telefono = db.Column(db.String(20))
    direccion = db.Column(db.String(200))
    descuento = db.Column(db.Float, default=0.0)
    productos = db.relationship('Producto', backref='proveedor', lazy=True)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    precio_coste = db.Column(db.Float, nullable=False)
    precio_venta = db.Column(db.Float, nullable=False)
    cantidad_actual = db.Column(db.Integer, default=0)
    stock_maximo = db.Column(db.Integer, default=100)
    referencia = db.Column(db.String(50))
    ubicacion = db.Column(db.String(100))
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedor.id'))

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # UTC evita inconsistencias con zonas horarias
    fecha = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unidad_coste = db.Column(db.Float, nullable=False)
    precio_unidad_venta = db.Column(db.Float, nullable=False)
    total_venta = db.Column(db.Float, nullable=False)
    descuento_aplicado = db.Column(db.Float, default=0.0)
    iva_aplicado = db.Column(db.Float, default=21.0)
    # Tipo: 'venta' (cliente) vs 'compra' (proveedor)
    tipo = db.Column(db.String(10), nullable=False, default='venta')
    # Estado: pendiente → completado/cancelado
    estado = db.Column(db.String(20), default='pendiente')

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)

    usuario = db.relationship('Usuario', backref=db.backref('pedidos', lazy=True))
    producto = db.relationship('Producto', backref=db.backref('pedidos', lazy=True))