import os
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, render_template,request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from db import db
from models import Usuario, Producto, Pedido
from datetime import timedelta, datetime, timezone
import plotly.express as px
import plotly.utils
import json
from sqlalchemy import func
from functools import wraps

load_dotenv()

# IVA estándar aplicable (editable por transacción)
IVA_DEFECTO = 21.0

# Bloqueo de rutas: solo admin puede acceder
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            flash("Acceso denegado. Solo administradores pueden acceder.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def create_app():
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, 'database', 'suministros.db')

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['REMEMBER_COOKIE_DURATION'] = 0
    app.config['SESSION_PERMANENT'] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    def limpiar_reservas_expiradas():
        # Política de negocio: liberación automática tras 48h sin recoger
        limite = datetime.now(timezone.utc) - timedelta(hours=48)
        expirados = Pedido.query.filter_by(estado='pendiente', tipo='venta').filter(Pedido.fecha < limite).all()

        for r in expirados:
            producto = Producto.query.get(r.producto_id)
            if producto:
                producto.cantidad_actual += r.cantidad
            r.estado = 'cancelado'

        if expirados:
            db.session.commit()

    @login_manager.user_loader
    def load_user(user_id):
        return Usuario.query.get(int(user_id))

    with app.app_context():
        db.create_all()

        user_env = os.getenv('ADMIN_USER')
        pass_env = os.getenv('ADMIN_PASS')

        # Prevención de duplicados al reiniciar aplicación
        if not Usuario.query.filter_by(username=user_env).first():
            admin_inicial = Usuario(
                username=user_env,
                rol='admin'
            )
            admin_inicial.set_password(pass_env)

            db.session.add(admin_inicial)
            db.session.commit()
            print(f"ÉXITO: Administrador '{user_env}' creado desde archivo .env")
        else:
            print("INFO: El administrador ya existe en la base de datos.")

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/registro', methods=['GET', 'POST'])
    def registro():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')

            user_exists = Usuario.query.filter_by(username=username).first()
            if user_exists:
                flash("Ese usuario ya existe", "warning")
                return redirect(url_for('registro'))

            nuevo_usuario = Usuario(username=username)
            nuevo_usuario.set_password(password)

            db.session.add(nuevo_usuario)
            db.session.commit()

            flash("¡Registro con éxito!", "success")
            return redirect(url_for('login'))

        return render_template('registro.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            usuario_ingresado = request.form.get('username')
            password_ingresada = request.form.get('password')

            user = Usuario.query.filter_by(username=usuario_ingresado).first()

            if user and user.check_password(password_ingresada):
                if not user.activo:
                    flash("Tu cuenta ha sido desactivada. Contacta al administrador.", "danger")
                    return redirect(url_for('login'))
                login_user(user)
                flash("Sesión iniciada correctamente", "success")
                return redirect(url_for('index'))
            else:
                flash("Usuario o contraseña incorrectos", "danger")
                return redirect(url_for('login'))

        return render_template('login.html')

    @app.route('/usuarios')
    @login_required
    @admin_required
    def ver_usuarios():
        todos_los_usuarios = Usuario.query.all()
        return render_template('usuarios.html', usuarios=todos_los_usuarios)

    @app.route('/proveedores')
    @login_required
    @admin_required
    def ver_proveedores():
        from models import Proveedor
        todos_los_proveedores = Proveedor.query.all()
        return render_template('proveedores.html', proveedores=todos_los_proveedores)

    @app.route('/proveedor/nuevo', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def nuevo_proveedor():
        from models import Proveedor
        if request.method == 'POST':
            try:
                nombre = request.form.get('nombre_empresa')
                cif = request.form.get('cif')
                telefono = request.form.get('telefono')
                direccion = request.form.get('direccion')
                descuento = float(request.form.get('descuento', 0))

                # Validación: porcentajes solo entre 0-100
                if descuento < 0 or descuento > 100:
                    flash("El descuento debe estar entre 0 y 100%", "danger")
                    return redirect(url_for('nuevo_proveedor'))

                # Verificar si el CIF ya existe
                if cif and Proveedor.query.filter_by(cif=cif).first():
                    flash("Ya existe un proveedor con ese CIF", "warning")
                    return redirect(url_for('nuevo_proveedor'))

                nuevo = Proveedor(
                    nombre_empresa=nombre,
                    cif=cif,
                    telefono=telefono,
                    direccion=direccion,
                    descuento=descuento
                )
                db.session.add(nuevo)
                db.session.commit()
                flash(f'Proveedor {nombre} registrado con éxito', 'success')
                return redirect(url_for('ver_proveedores'))

            except (ValueError, TypeError):
                flash("Error en los datos ingresados", "danger")
                return redirect(url_for('nuevo_proveedor'))

        return render_template('nuevo_proveedor.html')

    @app.route('/proveedor/editar/<int:id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def editar_proveedor(id):
        from models import Proveedor
        proveedor = Proveedor.query.get_or_404(id)

        if request.method == 'POST':
            try:
                nuevo_descuento = float(request.form.get('descuento', 0))

                if nuevo_descuento < 0 or nuevo_descuento > 100:
                    flash("El descuento debe estar entre 0 y 100%", "danger")
                    return redirect(url_for('editar_proveedor', id=id))

                proveedor.nombre_empresa = request.form.get('nombre_empresa')
                proveedor.cif = request.form.get('cif')
                proveedor.telefono = request.form.get('telefono')
                proveedor.direccion = request.form.get('direccion')
                proveedor.descuento = nuevo_descuento

                db.session.commit()
                flash(f'Proveedor {proveedor.nombre_empresa} actualizado', 'success')
                return redirect(url_for('ver_proveedores'))

            except (ValueError, TypeError):
                flash("Error en los datos ingresados", "danger")
                return redirect(url_for('editar_proveedor', id=id))

        return render_template('editar_proveedor.html', proveedor=proveedor)

    @app.route('/proveedor/eliminar/<int:id>')
    @login_required
    @admin_required
    def eliminar_proveedor(id):
        from models import Proveedor
        proveedor = Proveedor.query.get_or_404(id)

        # Integridad referencial: no eliminar si tiene productos asociados
        if proveedor.productos:
            flash(f"No se puede eliminar: {proveedor.nombre_empresa} tiene {len(proveedor.productos)} productos asociados", "danger")
            return redirect(url_for('ver_proveedores'))

        db.session.delete(proveedor)
        db.session.commit()
        flash(f'Proveedor {proveedor.nombre_empresa} eliminado', 'success')
        return redirect(url_for('ver_proveedores'))

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        print("LOG: Sesión cerrada")
        return redirect(url_for('index'))

    @app.route('/usuarios/estado/<int:id>')
    @login_required
    @admin_required
    def cambiar_estado(id):
        user = Usuario.query.get_or_404(id)

        # Protección: evita bloqueo total del sistema sin admin activo
        if user.id == current_user.id:
            flash("No puedes desactivar tu propia cuenta", "warning")
            return redirect(url_for('ver_usuarios'))

        user.activo = not user.activo
        db.session.commit()

        estado_texto = "activado" if user.activo else "desactivado"
        flash(f"El usuario {user.username} ha sido {estado_texto}.", "success")

        return redirect(url_for('ver_usuarios'))

    @app.route('/eliminar_usuario/<int:id>')
    @login_required
    @admin_required
    def eliminar_usuario(id):
        user_a_eliminar = Usuario.query.get_or_404(id)

        # Evitar que el admin se elimine a sí mismo
        if user_a_eliminar.id == current_user.id:
            flash("No puedes darte de baja a ti mismo", "warning")
            return redirect(url_for('inventario'))

        db.session.delete(user_a_eliminar)
        db.session.commit()

        flash(f"Usuario {user_a_eliminar.username} eliminado correctamente", "success")
        return redirect(url_for('ver_usuarios'))

    @app.route('/usuario/resetear_password/<int:id>', methods=['POST'])
    @login_required
    @admin_required
    def resetear_password_usuario(id):
        usuario = Usuario.query.get_or_404(id)

        # Seguridad: admin no puede cambiar su propia contraseña
        if usuario.id == current_user.id:
            flash("No puedes cambiar tu propia contraseña desde aquí. Usa tu perfil.", "warning")
            return redirect(url_for('ver_usuarios'))

        nueva_password = request.form.get('nueva_password', '').strip()

        if not nueva_password:
            flash("Debes ingresar una contraseña", "danger")
            return redirect(url_for('ver_usuarios'))

        if len(nueva_password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres", "danger")
            return redirect(url_for('ver_usuarios'))

        usuario.set_password(nueva_password)
        db.session.commit()

        flash(f"✅ Contraseña de '{usuario.username}' cambiada exitosamente. Nueva contraseña: {nueva_password}", "success")
        return redirect(url_for('ver_usuarios'))

    @app.route('/producto/nuevo', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def nuevo_producto():
        from models import Proveedor

        if request.method == 'POST':
            nombre = request.form.get('nombre')
            descripcion = request.form.get('descripcion')
            ubicacion = request.form.get('ubicacion')
            proveedor_id = request.form.get('proveedor_id')

            try:
                p_coste_sin_iva = float(request.form.get('precio_coste'))
                p_venta_sin_iva = float(request.form.get('precio_venta'))

                iva_porcentaje = float(request.form.get('iva', IVA_DEFECTO))
                if iva_porcentaje < 0 or iva_porcentaje > 100:
                    flash("El IVA debe estar entre 0 y 100%", "danger")
                    return redirect(url_for('nuevo_producto'))

                # Aplicamos IVA manualmente para evitar inconsistencias en cálculos
                p_coste = round(p_coste_sin_iva * (1 + iva_porcentaje / 100), 2)
                p_venta = round(p_venta_sin_iva * (1 + iva_porcentaje / 100), 2)

                stock_inicial = int(request.form.get('cantidad_actual'))
                maximo = int(request.form.get('stock_maximo'))

                if p_coste_sin_iva < 0 or p_venta_sin_iva < 0:
                    flash("Los precios no pueden ser negativos", "danger")
                    return redirect(url_for('nuevo_producto'))

                if p_venta_sin_iva < p_coste_sin_iva:
                    flash("Advertencia: El precio de venta es menor que el de coste. Tendrás pérdidas.", "warning")

                if stock_inicial < 0 or maximo < 0:
                    flash("Las cantidades no pueden ser negativas", "danger")
                    return redirect(url_for('nuevo_producto'))

                if stock_inicial > maximo:
                    flash(f"El stock inicial ({stock_inicial}) no puede superar el máximo ({maximo})", "danger")
                    return redirect(url_for('nuevo_producto'))

            except (ValueError, TypeError):
                flash("Error: Los campos numéricos contienen valores inválidos", "danger")
                return redirect(url_for('nuevo_producto'))

            nuevo = Producto(
                nombre=nombre,
                descripcion=descripcion,
                ubicacion=ubicacion,
                precio_coste=p_coste,
                precio_venta=p_venta,
                cantidad_actual=stock_inicial,
                stock_maximo=maximo,
                proveedor_id=int(proveedor_id) if proveedor_id else None
            )

            db.session.add(nuevo)
            db.session.flush()

            # Registramos inversión inicial como compra para gráfico de costos
            if stock_inicial > 0:
                registro_costo_inicial = Pedido(
                    cantidad=stock_inicial,
                    precio_unidad_coste=p_coste,
                    precio_unidad_venta=p_venta,
                    total_venta=0,
                    tipo='compra',
                    usuario_id=current_user.id,
                    producto_id=nuevo.id
                )
                db.session.add(registro_costo_inicial)

            db.session.commit()
            flash('Producto y stock inicial registrados con éxito')
            return redirect(url_for('inventario'))

        proveedores = Proveedor.query.all()
        return render_template('nuevo_producto.html', proveedores=proveedores)

    @app.route('/inventario')
    @login_required
    @admin_required
    def inventario():
        todos_los_productos = Producto.query.all()

        # Sistema de alertas: rojo ≤10%, amarillo ≤25%, azul ≥90%
        productos_con_alertas = []
        for p in todos_los_productos:
            porcentaje_ocupacion = (p.cantidad_actual / p.stock_maximo * 100) if p.stock_maximo > 0 else 0
            alerta = None

            if porcentaje_ocupacion <= 10:
                alerta = 'danger'
            elif porcentaje_ocupacion <= 25:
                alerta = 'warning'
            elif porcentaje_ocupacion >= 90:
                alerta = 'info'

            productos_con_alertas.append({
                'producto': p,
                'porcentaje': round(porcentaje_ocupacion, 1),
                'alerta': alerta
            })

        clientes = Usuario.query.filter_by(rol='cliente', activo=True).all()

        return render_template('inventario.html', productos=productos_con_alertas, clientes=clientes)

    @app.route('/producto/eliminar/<int:id>')
    @login_required
    @admin_required
    def eliminar_producto(id):
        producto = Producto.query.get_or_404(id)
        db.session.delete(producto)
        db.session.commit()

        flash(f'Producto {producto.nombre} eliminado con éxito')
        return redirect(url_for('inventario'))

    @app.route('/producto/editar/<int:id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def editar_producto(id):
        from models import Proveedor
        producto = Producto.query.get_or_404(id)

        if request.method == 'POST':
            try:
                nuevo_precio_coste = float(request.form.get('precio_coste'))
                nuevo_precio_venta = float(request.form.get('precio_venta'))
                nueva_cantidad = int(request.form.get('cantidad_actual'))
                nuevo_maximo = int(request.form.get('stock_maximo'))
                proveedor_id = request.form.get('proveedor_id')

                if nuevo_precio_coste < 0 or nuevo_precio_venta < 0:
                    flash("Los precios no pueden ser negativos", "danger")
                    return redirect(url_for('editar_producto', id=id))

                if nueva_cantidad < 0 or nuevo_maximo < 0:
                    flash("Las cantidades no pueden ser negativas", "danger")
                    return redirect(url_for('editar_producto', id=id))

                if nueva_cantidad > nuevo_maximo:
                    flash(f"El stock actual ({nueva_cantidad}) no puede superar el máximo ({nuevo_maximo})", "danger")
                    return redirect(url_for('editar_producto', id=id))

                producto.nombre = request.form.get('nombre')
                producto.descripcion = request.form.get('descripcion')
                producto.ubicacion = request.form.get('ubicacion')
                producto.precio_coste = nuevo_precio_coste
                producto.precio_venta = nuevo_precio_venta
                producto.cantidad_actual = nueva_cantidad
                producto.stock_maximo = nuevo_maximo
                producto.proveedor_id = int(proveedor_id) if proveedor_id else None

            except (ValueError, TypeError):
                flash("Error: Los campos numéricos contienen valores inválidos", "danger")
                return redirect(url_for('editar_producto', id=id))

            db.session.commit()

            flash(f'Producto "{producto.nombre}" actualizado con éxito')
            return redirect(url_for('inventario'))

        proveedores = Proveedor.query.all()
        return render_template('editar_producto.html', producto=producto, proveedores=proveedores)

    @app.route('/venta/nueva/<int:producto_id>', methods=['POST'])
    @login_required
    def realizar_venta(producto_id):
        producto = Producto.query.get_or_404(producto_id)
        cantidad_a_vender = int(request.form.get('cantidad', 1))

        if producto.cantidad_actual < cantidad_a_vender:
            flash(f"Error: Stock insuficiente de {producto.nombre}", "danger")
            return redirect(url_for('inventario'))

        descuento_cliente = float(request.form.get('descuento', 0))
        if descuento_cliente < 0 or descuento_cliente > 100:
            descuento_cliente = 0

        iva_venta = float(request.form.get('iva', IVA_DEFECTO))
        if iva_venta < 0 or iva_venta > 100:
            iva_venta = IVA_DEFECTO

        # Quitamos IVA almacenado y aplicamos el nuevo con redondeo
        precio_base = producto.precio_venta / (1 + IVA_DEFECTO / 100)
        precio_con_nuevo_iva = round(precio_base * (1 + iva_venta / 100), 2)
        precio_con_descuento = round(precio_con_nuevo_iva * (1 - descuento_cliente / 100), 2)
        total = round(precio_con_descuento * cantidad_a_vender, 2)

        # Si es admin puede especificar cliente, sino es el usuario actual
        if current_user.rol == 'admin':
            cliente_id = request.form.get('cliente_id')
            if cliente_id:
                cliente = Usuario.query.filter_by(id=int(cliente_id), rol='cliente', activo=True).first()
                if not cliente:
                    flash("Cliente no válido", "danger")
                    return redirect(url_for('inventario'))
                usuario_destino = int(cliente_id)
            else:
                usuario_destino = current_user.id
        else:
            usuario_destino = current_user.id

        nuevo_pedido = Pedido(
            tipo='venta',
            cantidad=cantidad_a_vender,
            precio_unidad_coste=producto.precio_coste,
            precio_unidad_venta=precio_con_nuevo_iva,
            total_venta=total,
            descuento_aplicado=descuento_cliente,
            iva_aplicado=iva_venta,
            usuario_id=usuario_destino,
            producto_id=producto.id,
            estado='pendiente'
        )

        producto.cantidad_actual -= cantidad_a_vender

        db.session.add(nuevo_pedido)
        db.session.commit()

        if current_user.rol == 'admin':
            if cliente_id:
                cliente = Usuario.query.get(usuario_destino)
                flash(f"Reserva #{nuevo_pedido.id} creada para el cliente: {cliente.username}", "success")
            else:
                flash(f"Reserva #{nuevo_pedido.id} creada (sin cliente asignado)", "info")
            return redirect(url_for('inventario'))
        else:
            flash(f"¡Reserva confirmada! Recuerda recoger tu {producto.nombre} en las próximas 48 horas.", "success")
            return redirect(url_for('ver_catalogo'))

    @app.route('/carrito/añadir/<int:producto_id>', methods=['POST'])
    @login_required
    def anadir_al_carrito(producto_id):
        # 1. Obtener el producto y la cantidad solicitada
        producto = Producto.query.get_or_404(producto_id)

        cantidad_solicitada = int(request.form.get('cantidad', 1))

        # 2. Inicializar el carrito en la sesión si no existe
        if 'carrito' not in session:
            session['carrito'] = {}

        carrito = session['carrito']
        id_str = str(producto_id)

        # 3. Calcular cuánto habría en total en el carrito si aceptamos esto
        cantidad_actual_en_carrito = carrito.get(id_str, 0)
        nueva_cantidad_total = cantidad_actual_en_carrito + cantidad_solicitada

        # Calcular stock real descontando reservas pendientes de otros usuarios
        stock_reservado = db.session.query(func.sum(Pedido.cantidad))\
            .filter(Pedido.producto_id == producto_id,
                    Pedido.estado == 'pendiente',
                    Pedido.tipo == 'venta')\
            .scalar() or 0

        stock_disponible = producto.cantidad_actual - stock_reservado

        # Validar contra el stock disponible real
        if nueva_cantidad_total > stock_disponible:
            flash(
                f"No puedes añadir {cantidad_solicitada} unidades. Solo hay {stock_disponible} disponibles (considerando reservas pendientes). Ya tienes {cantidad_actual_en_carrito} en tu carrito.",
                "warning")
            return redirect(url_for('ver_catalogo'))

        # 6. Si todo está bien, actualizamos el carrito
        carrito[id_str] = nueva_cantidad_total

        # 7. Guardar y marcar la sesión como modificada
        session['carrito'] = carrito
        session.modified = True

        flash(f"Añadido: {producto.nombre} (Cantidad: {cantidad_solicitada})", "success")
        return redirect(url_for('ver_catalogo'))

    @app.route('/carrito/eliminar/<int:producto_id>')
    @login_required
    def eliminar_del_carrito(producto_id):
        if 'carrito' in session:
            carrito = session['carrito']
            id_str = str(producto_id)
            if id_str in carrito:
                carrito.pop(id_str)
                session['carrito'] = carrito
                session.modified = True
                flash("Producto eliminado del carrito", "info")
        return redirect(url_for('ver_carrito'))

    @app.route('/carrito/vaciar')
    @login_required
    def vaciar_carrito():
        session.pop('carrito', None)
        flash("Carrito vaciado correctamente", "info")
        return redirect(url_for('ver_catalogo'))

    @app.route('/carrito')
    @login_required
    def ver_carrito():
        items_carrito = []
        total_compra = 0

        if 'carrito' in session and session['carrito']:
            # Optimización: consulta única en lugar de N consultas
            ids = [int(p_id) for p_id in session['carrito'].keys()]
            productos = Producto.query.filter(Producto.id.in_(ids)).all()
            productos_dict = {p.id: p for p in productos}

            for p_id, cantidad in session['carrito'].items():
                producto = productos_dict.get(int(p_id))
                if producto:
                    subtotal = round(producto.precio_venta * cantidad, 2)
                    total_compra += subtotal
                    items_carrito.append({
                        'id': producto.id, 'nombre': producto.nombre,
                        'precio': round(producto.precio_venta, 2), 'cantidad': cantidad,
                        'subtotal': subtotal
                    })

        return render_template('carrito.html', items=items_carrito, total=total_compra)

    @app.route('/carrito/confirmar', methods=['POST'])
    @login_required
    def confirmar_carrito():
        if 'carrito' not in session or not session['carrito']:
            flash("El carrito está vacío", "warning")
            return redirect(url_for('ver_catalogo'))

        for p_id, cantidad in session['carrito'].items():
            producto = Producto.query.get(int(p_id))
            if producto.cantidad_actual < cantidad:
                flash(f"Stock insuficiente de {producto.nombre}", "danger")
                return redirect(url_for('ver_carrito'))

            nuevo_pedido = Pedido(
                tipo='venta', cantidad=cantidad,
                precio_unidad_coste=round(producto.precio_coste, 2),
                precio_unidad_venta=round(producto.precio_venta, 2),
                total_venta=round(producto.precio_venta * cantidad, 2),
                usuario_id=current_user.id, producto_id=producto.id,
                estado='pendiente'
            )
            producto.cantidad_actual -= cantidad
            db.session.add(nuevo_pedido)

        session.pop('carrito', None)
        db.session.commit()

        if current_user.rol == 'admin':
            flash("Venta/Reserva registrada en inventario.", "info")
            return redirect(url_for('inventario'))
        else:
            flash("¡Reserva realizada! Tienes 48h para recoger tus artículos.", "success")
            return redirect(url_for('pedidos_clientes'))

    @app.route('/pedidos-clientes')
    @login_required
    def pedidos_clientes():
        # Obtener parámetro de filtro
        filtro_producto = request.args.get('producto', '')

        # Consulta base: Solo pedidos del usuario actual de tipo 'venta'
        query = Pedido.query.filter_by(usuario_id=current_user.id, tipo='venta')

        # Aplicar filtro de producto si existe
        if filtro_producto:
            query = query.filter(Pedido.producto_id == int(filtro_producto))

        # Ordenar por fecha descendente
        reservas = query.order_by(Pedido.fecha.desc()).all()

        # Gráfico TOP productos más comprados por el cliente
        graph_reserva_json = None
        if reservas:
            # Agregamos por producto sumando cantidades y dinero gastado
            top_productos = db.session.query(
                Producto.nombre,
                func.sum(Pedido.cantidad).label('total_cantidad'),
                func.sum(Pedido.total_venta).label('total_gastado')
            ).join(Pedido).filter(
                Pedido.usuario_id == current_user.id,
                Pedido.tipo == 'venta'
            ).group_by(Producto.id, Producto.nombre)\
             .order_by(func.sum(Pedido.cantidad).desc())\
             .limit(10).all()  # Máximo 10, pero si tiene menos muestra los que tenga

            if top_productos:
                # Crear DataFrame con los datos
                datos_top = [{
                    'Producto': nombre,
                    'Cantidad': int(cantidad),
                    'Total Gastado (€)': float(gastado)
                } for nombre, cantidad, gastado in top_productos]

                df = pd.DataFrame(datos_top)

                # Crear gráfico de barras mostrando DINERO GASTADO
                fig = px.bar(
                    df,
                    x='Producto',
                    y='Total Gastado (€)',
                    title=f'Tus {len(top_productos)} Productos: Total Gastado',
                    template='plotly_white',
                    color='Total Gastado (€)',
                    color_continuous_scale=['#4FC3F7', '#039BE5', '#0277BD'],  # Azul degradado
                    hover_data=['Cantidad']
                )

                # Personalizar diseño
                fig.update_layout(
                    xaxis_title='Producto',
                    yaxis_title='Dinero Gastado (€)',
                    showlegend=False,
                    xaxis_tickangle=-45,
                    coloraxis_showscale=False  # Ocultar la barra de color lateral
                )

                # Personalizar hover
                fig.update_traces(
                    hovertemplate='<b>%{x}</b><br>Gastado: %{y:.2f}€<br>Unidades: %{customdata[0]}<extra></extra>'
                )

                graph_reserva_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

        # Obtener lista de productos únicos del cliente para el filtro
        productos_cliente = db.session.query(Producto)\
            .join(Pedido)\
            .filter(Pedido.usuario_id == current_user.id, Pedido.tipo == 'venta')\
            .distinct().all()

        return render_template('pedidos_clientes.html',
                               pedidos=reservas,
                               graph_user=graph_reserva_json,
                               productos=productos_cliente,
                               filtro_producto=filtro_producto)

    @app.route('/admin/reservas')
    @login_required
    @admin_required
    def panel_admin_reservas():
        limpiar_reservas_expiradas()  # Limpiamos antes de mostrar

        # Obtener parámetros de filtro
        filtro_cliente = request.args.get('cliente', '')
        filtro_producto = request.args.get('producto', '')
        filtro_estado = request.args.get('estado', '')

        # Consulta base: TODAS las reservas de tipo 'venta'
        query = Pedido.query.filter_by(tipo='venta')

        # Aplicar filtros si existen
        if filtro_cliente:
            query = query.filter(Pedido.usuario_id == int(filtro_cliente))

        if filtro_producto:
            query = query.filter(Pedido.producto_id == int(filtro_producto))

        if filtro_estado:
            query = query.filter(Pedido.estado == filtro_estado)

        # Ordenar por fecha descendente
        reservas = query.order_by(Pedido.fecha.desc()).all()

        # Obtener listas para los selectores de filtro
        clientes = Usuario.query.filter_by(rol='cliente').all()
        productos = Producto.query.all()

        return render_template('admin_reservas.html',
                               reservas=reservas,
                               clientes=clientes,
                               productos=productos,
                               filtro_cliente=filtro_cliente,
                               filtro_producto=filtro_producto,
                               filtro_estado=filtro_estado)

    @app.route('/pedido/confirmar_entrega/<int:id>')
    @login_required
    @admin_required
    def confirmar_entrega(id):

        pedido = Pedido.query.get_or_404(id)
        pedido.estado = 'completado'  # La reserva se convierte en venta real
        db.session.commit()
        flash(f"Pedido #{id} marcado como entregado y cobrado.", "success")
        return redirect(url_for('panel_admin_reservas'))

    @app.route('/pedido/cancelar/<int:pedido_id>')
    @login_required
    def cancelar_reserva(pedido_id):
        # Solo admin o el dueño del pedido pueden cancelar
        reserva = Pedido.query.get_or_404(pedido_id)

        if current_user.rol != 'admin' and reserva.usuario_id != current_user.id:
            flash("No tienes permiso.", "danger")
            return redirect(url_for('index'))

        if reserva.estado == 'pendiente':
            producto = Producto.query.get(reserva.producto_id)
            if producto:
                # Liberamos el stock bloqueado de la reserva cancelada
                producto.cantidad_actual += reserva.cantidad
            reserva.estado = 'cancelado'
            db.session.commit()
            flash("Reserva cancelada y stock devuelto.", "warning")

        if current_user.rol == 'admin':
            return redirect(url_for('panel_admin_reservas'))
        return redirect(url_for('pedidos_clientes'))

    @app.route('/dashboard')
    @login_required
    @admin_required
    def dashboard():

        limpiar_reservas_expiradas()

        # Solo ventas completadas cuentan como ingreso real
        ventas_reales = Pedido.query.filter_by(tipo='venta', estado='completado').all()
        compras_proveedor = Pedido.query.filter_by(tipo='compra').all()

        total_ingresos = sum(v.total_venta for v in ventas_reales)
        total_costos = sum(c.precio_unidad_coste * c.cantidad for c in compras_proveedor)

        # Conversión explícita a float para compatibilidad con Plotly
        categorias = ["Ingresos Totales", "Costos Totales"]
        valores = [float(total_ingresos), float(total_costos)]

        fig_bar = px.bar(
            x=categorias,
            y=valores,
            title="Comparacion Costos contra Ingresos (€)",
            color=categorias,
            color_discrete_map={
                "Ingresos Totales": "#198754",
                "Costos Totales": "#dc3545"
            }
        )

        # 1. Quitamos la leyenda (la explicación de colores de la derecha)
        fig_bar.update_layout(showlegend=False, xaxis_title=None, yaxis_title=None, hovermode="x unified")

        # 2. Personalizamos la información al pasar el ratón (hover)
        # %{y} muestra el valor y .2f le da dos decimales.
        fig_bar.update_traces(hovertemplate="Valor: %{y:.2f}€<extra></extra>")

        # Convertir a JSON de forma explícita
        graph_bar_json = json.dumps(fig_bar, cls=plotly.utils.PlotlyJSONEncoder)

        # --- TABLA TOP 3 (Lógica de Negocio) ---
        top_ventas_raw = db.session.query(
            Producto,
            func.sum(Pedido.cantidad).label('total_qty'),
            func.sum(Pedido.total_venta).label('total_ingreso')
        ).join(Pedido).filter(Pedido.tipo == 'venta') \
            .group_by(Producto.id) \
            .order_by(func.sum(Pedido.cantidad).desc()) \
            .limit(3).all()

        top_3_tabla = []
        for p, qty, ingreso in top_ventas_raw:
            # Cálculo de ganancia neta: ingresos menos costos totales vendidos
            costo_total_vendido = p.precio_coste * qty
            ganancia = ingreso - costo_total_vendido

            top_3_tabla.append({
                'nombre': p.nombre,
                'cantidad': qty,
                'costo_total': costo_total_vendido,  # <--- Añadido
                'venta_total': ingreso,
                'ganancia': ganancia
            })

        return render_template('dashboard.html',
                               graph_bar=graph_bar_json,
                               top_3=top_3_tabla)

    @app.route('/catalogo')
    @login_required
    def ver_catalogo():
        productos_en_stock = Producto.query.filter(Producto.cantidad_actual > 0).all()
        return render_template('catalogo.html', productos=productos_en_stock)

    @app.route('/producto/reabastecer/<int:producto_id>', methods=['POST'])
    @login_required
    @admin_required
    def reabastecer_producto(producto_id):
        producto = Producto.query.get_or_404(producto_id)

        try:
            cantidad_compra = int(request.form.get('cantidad', 0))

            if cantidad_compra <= 0:
                flash("La cantidad debe ser mayor a 0.", "warning")
                return redirect(url_for('inventario'))

            # Validación límite: no exceder stock máximo configurado
            if producto.cantidad_actual + cantidad_compra > producto.stock_maximo:
                flash(f"No puedes añadir {cantidad_compra} unidades. Excederías el stock máximo de {producto.stock_maximo}. Actualmente tienes {producto.cantidad_actual}.", "danger")
                return redirect(url_for('inventario'))

        except (ValueError, TypeError):
            flash("Cantidad inválida", "danger")
            return redirect(url_for('inventario'))

        if cantidad_compra > 0:
            producto.cantidad_actual += cantidad_compra

            # Registro como compra para auditoría de costos
            nueva_compra = Pedido(
                cantidad=cantidad_compra,
                precio_unidad_coste=producto.precio_coste,
                precio_unidad_venta=producto.precio_venta,
                total_venta=0,
                tipo='compra',
                usuario_id=current_user.id,
                producto_id=producto.id
            )

            db.session.add(nueva_compra)
            db.session.commit()
            flash(f"Se han añadido {cantidad_compra} unidades a {producto.nombre}.", "success")

        return redirect(url_for('inventario'))

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)