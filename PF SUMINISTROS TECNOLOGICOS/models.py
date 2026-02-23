from db import db
from flask_login import UserMixin
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

# 1. CLASE USUARIO: Para gestionar quién entra al sistema
class Usuario(db.Model, UserMixin): # <--- UserMixin es la clave
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(20), default='cliente') # Aquí definimos si es 'admin' o 'cliente'
    activo = db.Column(db.Boolean, default=True)

    def set_password(self, password_plana):
        """Toma la contraseña escrita por el usuario y la guarda encriptada."""
        self.password = generate_password_hash(password_plana)

    def check_password(self, password_plana):
        """Verifica si la contraseña escrita coincide con el hash guardado."""
        return check_password_hash(self.password, password_plana)

# 2. CLASE PROVEEDOR: Datos que solo verá el administrador
class Proveedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_empresa = db.Column(db.String(100), nullable=False)
    cif = db.Column(db.String(20), unique=True)
    telefono = db.Column(db.String(20))
    direccion = db.Column(db.String(200))  # NUEVO: Dirección del proveedor
    descuento = db.Column(db.Float, default=0.0) # Porcentaje de descuento del proveedor
    # Un proveedor puede suministrar muchos productos
    productos = db.relationship('Producto', backref='proveedor', lazy=True)

# 3. CLASE PRODUCTO: El inventario central
class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    precio_coste = db.Column(db.Float, nullable=False) # Lo que nos cuesta (solo Admin)
    precio_venta = db.Column(db.Float, nullable=False) # Lo que paga el cliente (Ambos)
    cantidad_actual = db.Column(db.Integer, default=0)
    stock_maximo = db.Column(db.Integer, default=100) # Para calcular el aviso del 90%
    referencia = db.Column(db.String(50))
    ubicacion = db.Column(db.String(100))  # NUEVO: Ubicación física en el almacén
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedor.id'))

# 4. CLASE PEDIDO: El registro detallado de transacciones y movimientos de stock
class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unidad_coste = db.Column(db.Float, nullable=False)  # Guardamos el precio del momento
    precio_unidad_venta = db.Column(db.Float, nullable=False)
    total_venta = db.Column(db.Float, nullable=False)
    descuento_aplicado = db.Column(db.Float, default=0.0)  # Descuento % aplicado al cliente
    iva_aplicado = db.Column(db.Float, default=21.0)  # NUEVO: IVA % aplicado en esta transacción
    tipo = db.Column(db.String(10), nullable=False, default='venta')
    estado = db.Column(db.String(20), default='pendiente')  # 'pendiente', 'completado', 'cancelado'

    # Relaciones
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)

    # Para acceder fácilmente a los objetos relacionados
    usuario = db.relationship('Usuario', backref=db.backref('pedidos', lazy=True))
    producto = db.relationship('Producto', backref=db.backref('pedidos', lazy=True))