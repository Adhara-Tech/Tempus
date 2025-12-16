from flask import render_template, request, redirect, url_for, flash
from flask_login import current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func, or_  # <--- AÑADIDO or_
from datetime import datetime, date, timedelta
from calendar import monthrange

from src import db, admin_required
from src.models import Usuario, Aprobador, Fichaje, SolicitudVacaciones, Festivo, TipoAusencia, SolicitudBaja
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

# --- TIPOS DE AUSENCIA ---
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
        
    tipos = TipoAusencia.query.order_by(TipoAusencia.activo.desc(), TipoAusencia.nombre).all()
    return render_template('admin/tipos_ausencia.html', tipos=tipos)

@admin_bp.route('/admin/tipos-ausencia/toggle/<int:id>', methods=['POST'])
@admin_required
def admin_toggle_tipo_ausencia(id):
    tipo = TipoAusencia.query.get_or_404(id)
    tipo.activo = not tipo.activo
    db.session.commit()
    estado = "activado" if tipo.activo else "desactivado"
    tipo_msg = 'success' if tipo.activo else 'warning'
    flash(f'Tipo de ausencia "{tipo.nombre}" {estado}.', tipo_msg)
    return redirect(url_for('admin.admin_tipos_ausencia'))

# --- RESUMEN ---
@admin_bp.route('/admin/resumen')
@admin_required
def admin_resumen():
    # 1. Obtener filtros
    usuario_id = request.args.get('usuario_id', type=int)
    # Por defecto usamos el año actual si no se especifica
    anio = request.args.get('anio', type=int, default=datetime.now().year)
    
    # 2. Definir rango de fechas del año seleccionado (para vacaciones y estadísticas anuales)
    fecha_inicio_anio = date(anio, 1, 1)
    fecha_fin_anio = date(anio, 12, 31)

    # 3. Obtener usuarios (para el selector y para el bucle)
    all_usuarios = Usuario.query.order_by(Usuario.nombre).all()
    
    # Filtramos la lista principal si se seleccionó un usuario
    query_users = Usuario.query.filter(Usuario.rol != 'admin')
    if usuario_id:
        query_users = query_users.filter(Usuario.id == usuario_id)
    usuarios_a_mostrar = query_users.all()
    
    resumen_usuarios = []
    
    for usuario in usuarios_a_mostrar:
        # A. Fichajes del AÑO completo (Conteo y Horas)
        fichajes_anio = Fichaje.query.filter(
            Fichaje.usuario_id == usuario.id,
            Fichaje.es_actual == True,
            Fichaje.tipo_accion != 'eliminacion',
            Fichaje.fecha >= fecha_inicio_anio,
            Fichaje.fecha <= fecha_fin_anio
        ).all()
        
        # B. Vacaciones disfrutadas EN ESE AÑO
        # (Importante: filtramos por fecha para que el saldo sea correcto por año)
        dias_aprobados = db.session.query(func.sum(SolicitudVacaciones.dias_solicitados)).filter(
            SolicitudVacaciones.usuario_id == usuario.id,
            SolicitudVacaciones.estado == 'aprobada',
            SolicitudVacaciones.es_actual == True,
            SolicitudVacaciones.fecha_inicio >= fecha_inicio_anio,
            SolicitudVacaciones.fecha_inicio <= fecha_fin_anio
        ).scalar() or 0
        
        # Calculamos horas totales del año (puede ser costoso si hay muchos, pero útil)
        total_horas_anio = sum(f.horas_trabajadas() for f in fichajes_anio)

        resumen_usuarios.append({
            'usuario': usuario,
            'fichajes_count': len(fichajes_anio),
            'horas_totales': total_horas_anio,
            'dias_vacaciones_totales': usuario.dias_vacaciones,
            'dias_disfrutados': dias_aprobados,
            'dias_restantes': usuario.dias_vacaciones - dias_aprobados
        })
    
    # Totales globales para el pie de página
    total_dias_disfrutados = sum(r['dias_disfrutados'] for r in resumen_usuarios)
    total_dias_restantes = sum(r['dias_restantes'] for r in resumen_usuarios)
    
    return render_template('admin/resumen.html', 
                           resumen_usuarios=resumen_usuarios, 
                           usuarios=all_usuarios, # Para el selector
                           usuario_seleccionado=usuario_id,
                           anio_actual=anio,
                           total_dias_disfrutados=total_dias_disfrutados,
                           total_dias_restantes=total_dias_restantes)

# --- AUDITORÍA UNIFICADA (Fichajes + Ausencias + Impersonation) ---
@admin_bp.route('/admin/auditoria')
@admin_required
def admin_auditoria():
    usuario_nombre = request.args.get('usuario')
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    
    logs_unificados = []

    # 1. AUDITORÍA DE FICHAJES
    # Buscamos: Modificaciones (v>1), Eliminaciones, o Creaciones por admin (editor!=usuario)
    query_fichajes = Fichaje.query.join(Usuario, Fichaje.usuario_id == Usuario.id).filter(
        or_(
            Fichaje.version > 1,
            Fichaje.tipo_accion == 'eliminacion',
            Fichaje.editor_id != Fichaje.usuario_id  # <--- DETECTA CREACIÓN POR ADMIN
        )
    )
    
    if usuario_nombre:
        query_fichajes = query_fichajes.filter(Usuario.nombre.ilike(f'%{usuario_nombre}%'))
    if fecha_inicio:
        query_fichajes = query_fichajes.filter(Fichaje.fecha_creacion >= datetime.strptime(fecha_inicio, '%Y-%m-%d'))
    if fecha_fin:
        fin = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
        query_fichajes = query_fichajes.filter(Fichaje.fecha_creacion < fin)
        
    for f in query_fichajes.all():
        tipo = 'MODIFICACIÓN'
        if f.tipo_accion == 'eliminacion': tipo = 'ELIMINACIÓN'
        elif f.version == 1: tipo = 'CREACIÓN (ADMIN)'
        
        logs_unificados.append({
            'fecha_accion': f.fecha_creacion,
            'tipo_etiqueta': tipo,
            'empleado': f.usuario.nombre,
            'editor': f.editor.nombre if f.editor else 'Sistema',
            'objeto': 'Fichaje',
            'detalle': f"{f.fecha.strftime('%d/%m/%Y')} ({f.hora_entrada.strftime('%H:%M')} - {f.hora_salida.strftime('%H:%M')})",
            'motivo': f.motivo_rectificacion or '-'
        })

    # 2. AUDITORÍA DE VACACIONES
    # Buscamos solicitudes donde haya intervenido un aprobador (o admin creador)
    query_vac = SolicitudVacaciones.query.join(Usuario, SolicitudVacaciones.usuario_id == Usuario.id).filter(
        SolicitudVacaciones.aprobador_id.isnot(None)
    )
    
    if usuario_nombre:
        query_vac = query_vac.filter(Usuario.nombre.ilike(f'%{usuario_nombre}%'))
    # Filtros de fecha (simplificado para usar fecha_respuesta si existe)
    
    for v in query_vac.all():
        # Si la respuesta es casi inmediata a la solicitud, fue creada por el admin directamente
        delta = (v.fecha_respuesta or v.fecha_solicitud) - v.fecha_solicitud
        es_creacion_directa = delta.total_seconds() < 60
        
        tipo = 'CREACIÓN (ADMIN)' if es_creacion_directa else 'APROBACIÓN/RECHAZO'
        
        logs_unificados.append({
            'fecha_accion': v.fecha_respuesta or v.fecha_solicitud,
            'tipo_etiqueta': tipo,
            'empleado': v.usuario.nombre,
            'editor': v.aprobador.nombre if v.aprobador else 'Admin',
            'objeto': 'Vacaciones',
            'detalle': f"{v.fecha_inicio.strftime('%d/%m')} - {v.fecha_fin.strftime('%d/%m')} ({v.dias_solicitados}d) [{v.estado.upper()}]",
            'motivo': v.motivo or '-'
        })

    # 3. AUDITORÍA DE BAJAS
    query_bajas = SolicitudBaja.query.join(Usuario, SolicitudBaja.usuario_id == Usuario.id).filter(
        SolicitudBaja.aprobador_id.isnot(None)
    )
    
    if usuario_nombre:
        query_bajas = query_bajas.filter(Usuario.nombre.ilike(f'%{usuario_nombre}%'))

    for b in query_bajas.all():
        delta = (b.fecha_respuesta or b.fecha_solicitud) - b.fecha_solicitud
        es_creacion_directa = delta.total_seconds() < 60
        
        tipo = 'CREACIÓN (ADMIN)' if es_creacion_directa else 'APROBACIÓN/RECHAZO'
        
        logs_unificados.append({
            'fecha_accion': b.fecha_respuesta or b.fecha_solicitud,
            'tipo_etiqueta': tipo,
            'empleado': b.usuario.nombre,
            'editor': b.aprobador.nombre if b.aprobador else 'Admin',
            'objeto': 'Baja/Ausencia',
            'detalle': f"{b.fecha_inicio.strftime('%d/%m')} - {b.fecha_fin.strftime('%d/%m')} ({b.tipo_ausencia.nombre}) [{b.estado.upper()}]",
            'motivo': b.motivo or '-'
        })

    # Ordenar cronológicamente (más reciente arriba)
    logs_unificados.sort(key=lambda x: x['fecha_accion'], reverse=True)
    
    # Renderizamos la plantilla nueva que sabe mostrar esta lista unificada
    return render_template('admin/auditoria.html', logs=logs_unificados)

@admin_bp.route('/admin/admin_fichajes', methods=['GET'])
@admin_required
def admin_fichajes():
    # 1. Obtener filtros de la URL o defaults
    usuario_id = request.args.get('usuario_id', type=int)
    
    hoy = date.today()
    try:
        mes = int(request.args.get('mes', hoy.month))
        anio = int(request.args.get('anio', hoy.year))
    except ValueError:
        mes = hoy.month
        anio = hoy.year
        
    # 2. Calcular rango de fechas
    _, ultimo_dia = monthrange(anio, mes)
    fecha_inicio = date(anio, mes, 1)
    fecha_fin = date(anio, mes, ultimo_dia)
    
    # 3. Query base
    query = Fichaje.query.filter(
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion',
        Fichaje.fecha >= fecha_inicio,
        Fichaje.fecha <= fecha_fin
    )
    
    # 4. Aplicar filtro de usuario si está seleccionado
    if usuario_id:
        query = query.filter(Fichaje.usuario_id == usuario_id)
    
    # Ordenar
    fichajes = query.order_by(Fichaje.fecha.desc(), Fichaje.hora_entrada.asc()).all()
    
    # 5. Cargar lista de usuarios para el selector
    usuarios = Usuario.query.order_by(Usuario.nombre).all()
    
    # 6. Calcular totales para el resumen rápido
    total_horas = sum(f.horas_trabajadas() for f in fichajes)
    
    return render_template('/admin/admin_fichajes.html',
                           fichajes=fichajes,
                           usuarios=usuarios,
                           usuario_seleccionado=usuario_id,
                           mes_actual=mes,
                           anio_actual=anio,
                           total_horas=total_horas)

@admin_bp.route('/admin/gestion-ausencias')
@admin_required
def admin_gestion_ausencias():
    # 1. Obtener filtros
    usuario_id = request.args.get('usuario_id', type=int)
    tipo_filtro = request.args.get('tipo', 'todos')
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    
    # 2. Consultas Base (Solo versiones actuales)
    query_vac = SolicitudVacaciones.query.filter_by(es_actual=True)
    query_bajas = SolicitudBaja.query.filter_by(es_actual=True)
    
    # 3. Filtros
    if usuario_id:
        query_vac = query_vac.filter_by(usuario_id=usuario_id)
        query_bajas = query_bajas.filter_by(usuario_id=usuario_id)
        
    if fecha_inicio_str:
        f_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        query_vac = query_vac.filter(SolicitudVacaciones.fecha_fin >= f_inicio)
        query_bajas = query_bajas.filter(SolicitudBaja.fecha_fin >= f_inicio)
        
    if fecha_fin_str:
        f_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        query_vac = query_vac.filter(SolicitudVacaciones.fecha_inicio <= f_fin)
        query_bajas = query_bajas.filter(SolicitudBaja.fecha_inicio <= f_fin)

    # 4. Unificar resultados
    resultados = []
    
    if tipo_filtro in ['todos', 'vacaciones']:
        for v in query_vac.all():
            v.tipo_etiqueta = 'Vacaciones'
            v.clase_css = 'success'
            resultados.append(v)
            
    if tipo_filtro in ['todos', 'bajas']:
        for b in query_bajas.all():
            nombre = b.tipo_ausencia.nombre if b.tipo_ausencia else 'Baja/Ausencia'
            b.tipo_etiqueta = nombre
            b.clase_css = 'danger' # Rojo para bajas
            resultados.append(b)
            
    # Ordenar por fecha más reciente
    resultados.sort(key=lambda x: x.fecha_inicio, reverse=True)
    
    # 5. Calcular totales para la barra azul (Estilo Admin Fichajes)
    total_dias = sum(r.dias_solicitados for r in resultados)
    
    # 6. Datos para selectores
    usuarios = Usuario.query.order_by(Usuario.nombre).all()
    
    return render_template('admin/gestion_ausencias.html', 
                           ausencias=resultados,
                           usuarios=usuarios,
                           usuario_seleccionado=usuario_id,
                           tipo_seleccionado=tipo_filtro,
                           fecha_inicio=fecha_inicio_str,
                           fecha_fin=fecha_fin_str,
                           total_dias=total_dias)