from flask import render_template, request, redirect, url_for, flash
from flask_login import current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from datetime import datetime, date
from calendar import monthrange

from src import db, admin_required
from src.models import Usuario, Aprobador, Fichaje, SolicitudVacaciones, Festivo, TipoAusencia
from . import admin_bp

@admin_bp.route('/admin/usuarios')
@admin_required
def admin_usuarios():
    usuarios = Usuario.query.all()
    return render_template('admin/usuarios.html', usuarios=usuarios)

@admin_bp.route('/admin/usuarios/crear', methods=['GET', 'POST'])
@admin_required
def admin_crear_usuario():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        rol = request.form.get('rol')
        dias_vacaciones = int(request.form.get('dias_vacaciones', 25))
        
        if Usuario.query.filter_by(email=email).first():
            flash('El email ya está registrado', 'danger')
            return redirect(url_for('admin.admin_crear_usuario'))
        
        usuario = Usuario(
            nombre=nombre,
            email=email,
            password=generate_password_hash(password),
            rol=rol,
            dias_vacaciones=dias_vacaciones
        )
        
        db.session.add(usuario)
        db.session.commit()
        flash('Usuario creado correctamente', 'success')
        return redirect(url_for('admin.admin_usuarios'))
    
    return render_template('admin/crear_usuario.html')

@admin_bp.route('/admin/usuarios/editar/<int:id>', methods=['GET', 'POST'])
@admin_required
def admin_editar_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    
    if request.method == 'POST':
        usuario.nombre = request.form.get('nombre')
        usuario.email = request.form.get('email')
        usuario.rol = request.form.get('rol')
        usuario.dias_vacaciones = int(request.form.get('dias_vacaciones', 25))
        
        password = request.form.get('password')
        if password:
            usuario.password = generate_password_hash(password)
        
        db.session.commit()
        flash('Usuario actualizado correctamente', 'success')
        return redirect(url_for('admin.admin_usuarios'))
    
    return render_template('admin/editar_usuario.html', usuario=usuario)

@admin_bp.route('/admin/usuarios/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    db.session.delete(usuario)
    db.session.commit()
    flash('Usuario eliminado correctamente', 'success')
    return redirect(url_for('admin.admin_usuarios'))

# --- APROBADORES ---
@admin_bp.route('/admin/aprobadores')
@admin_required
def admin_aprobadores():
    aprobadores = Aprobador.query.all()
    usuarios = Usuario.query.all()
    return render_template('admin/aprobadores.html', aprobadores=aprobadores, usuarios=usuarios)

@admin_bp.route('/admin/aprobadores/asignar', methods=['POST'])
@admin_required
def admin_asignar_aprobador():
    usuario_id = int(request.form.get('usuario_id'))
    aprobador_id = int(request.form.get('aprobador_id'))
    
    if Aprobador.query.filter_by(usuario_id=usuario_id, aprobador_id=aprobador_id).first():
        flash('Esta relación ya existe', 'warning')
        return redirect(url_for('admin.admin_aprobadores'))
    
    relacion = Aprobador(usuario_id=usuario_id, aprobador_id=aprobador_id)
    db.session.add(relacion)
    db.session.commit()
    flash('Aprobador asignado correctamente', 'success')
    return redirect(url_for('admin.admin_aprobadores'))

@admin_bp.route('/admin/aprobadores/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_aprobador(id):
    aprobador = Aprobador.query.get_or_404(id)
    db.session.delete(aprobador)
    db.session.commit()
    flash('Relación eliminada correctamente', 'success')
    return redirect(url_for('admin.admin_aprobadores'))

# --- FESTIVOS ---
@admin_bp.route('/admin/festivos')
@admin_required
def admin_festivos():
    festivos = Festivo.query.order_by(Festivo.fecha).all()
    return render_template('admin/festivos.html', festivos=festivos)

@admin_bp.route('/admin/festivos/crear', methods=['POST'])
@admin_required
def admin_crear_festivo():
    fecha = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date()
    descripcion = request.form.get('descripcion')
    
    if Festivo.query.filter_by(fecha=fecha).first():
        flash('Este festivo ya existe', 'warning')
        return redirect(url_for('admin.admin_festivos'))
    
    festivo = Festivo(fecha=fecha, descripcion=descripcion)
    db.session.add(festivo)
    db.session.commit()
    flash('Festivo añadido correctamente', 'success')
    return redirect(url_for('admin.admin_festivos'))

@admin_bp.route('/admin/festivos/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_festivo(id):
    festivo = Festivo.query.get_or_404(id)
    db.session.delete(festivo)
    db.session.commit()
    flash('Festivo eliminado correctamente', 'success')
    return redirect(url_for('admin.admin_festivos'))

# --- TIPOS DE AUSENCIA (NUEVO) ---
@admin_bp.route('/admin/tipos-ausencia', methods=['GET', 'POST'])
@admin_required
def admin_tipos_ausencia():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        try:
            max_dias = int(request.form.get('max_dias'))
        except (ValueError, TypeError):
            max_dias = 365
            
        tipo_dias = request.form.get('tipo_dias', 'naturales')
        descripcion = request.form.get('descripcion', '')
        
        # Validación simple
        if TipoAusencia.query.filter_by(nombre=nombre).first():
            flash('Ya existe un tipo de ausencia con ese nombre', 'danger')
        else:
            nuevo = TipoAusencia(
                nombre=nombre,
                descripcion=descripcion,
                max_dias=max_dias,
                tipo_dias=tipo_dias
            )
            db.session.add(nuevo)
            db.session.commit()
            flash('Tipo de ausencia creado', 'success')
        
        return redirect(url_for('admin.admin_tipos_ausencia'))
        
    tipos = TipoAusencia.query.all()
    # Si no existe el template específico, crearemos uno o usaremos una vista genérica
    # Por ahora asumo que crearás templates/admin/tipos_ausencia.html
    return render_template('admin/tipos_ausencia.html', tipos=tipos)

# --- RESUMEN ---
@admin_bp.route('/admin/resumen')
@admin_required
def admin_resumen():
    usuarios = Usuario.query.filter(Usuario.rol != 'admin').all()
    
    hoy = datetime.now()
    mes = request.args.get('mes', type=int, default=hoy.month)
    anio = request.args.get('anio', type=int, default=hoy.year)

    try:
        _, ultimo_dia = monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)
    except ValueError:
        mes = hoy.month
        anio = hoy.year
        _, ultimo_dia = monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)
    
    resumen_usuarios = []
    for usuario in usuarios:
        # Solo fichajes ACTUALES
        fichajes = Fichaje.query.filter_by(usuario_id=usuario.id, es_actual=True)\
            .filter(Fichaje.tipo_accion != 'eliminacion')\
            .filter(Fichaje.fecha >= fecha_inicio)\
            .filter(Fichaje.fecha <= fecha_fin)\
            .all()
        
        dias_aprobados = db.session.query(func.sum(SolicitudVacaciones.dias_solicitados)).filter(
            SolicitudVacaciones.usuario_id == usuario.id,
            SolicitudVacaciones.estado == 'aprobada',
            SolicitudVacaciones.es_actual == True
        ).scalar() or 0
        
        resumen_usuarios.append({
            'usuario': usuario,
            'fichajes': fichajes,
            'dias_vacaciones_totales': usuario.dias_vacaciones,
            'dias_disfrutados': dias_aprobados,
            'dias_restantes': usuario.dias_vacaciones - dias_aprobados
        })
    
    return render_template('admin/resumen.html', resumen_usuarios=resumen_usuarios, now=datetime.now, mes_actual=mes, anio_actual=anio)

# --- AUDITORÍA (ADAPTADA) ---
@admin_bp.route('/admin/auditoria')
@admin_required
def admin_auditoria():
    usuario_nombre = request.args.get('usuario')
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    
    # Consultamos la tabla Fichaje buscando versiones históricas
    # Se considera histórico si version > 1 o si es_actual=False (versiones obsoletas)
    query = Fichaje.query.join(Usuario).filter(
        (Fichaje.version > 1) | (Fichaje.tipo_accion != 'creacion')
    )
    
    if usuario_nombre:
        query = query.filter(Usuario.nombre.ilike(f'%{usuario_nombre}%'))
        
    if fecha_inicio:
        query = query.filter(Fichaje.fecha_creacion >= datetime.strptime(fecha_inicio, '%Y-%m-%d'))
        
    if fecha_fin:
        fin = datetime.strptime(fecha_fin, '%Y-%m-%d')
        query = query.filter(Fichaje.fecha_creacion < fin)
        
    # Ordenar por fecha de creación del registro de auditoría (el momento de la edición)
    logs = query.order_by(Fichaje.fecha_creacion.desc()).all()
    
    return render_template('admin/auditoria.html', logs=logs)