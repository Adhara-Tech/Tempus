from flask import current_app, render_template, request, redirect, url_for, flash
from flask_login import current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func, or_, case, cast, Float, extract
from datetime import datetime, date, timedelta
from calendar import monthrange

from src import db, admin_required
from src.models import Usuario, Aprobador, Fichaje, SolicitudVacaciones, Festivo, TipoAusencia, SolicitudBaja
from src.utils import invalidar_cache_festivos
from . import admin_bp

@admin_bp.route('/admin/usuarios')
@admin_required
def admin_usuarios():
    # MODIFICADO: No cargamos todos los usuarios de golpe para la vista inicial
    # Se obtendrán por AJAX o paginación si fuera necesario
    page = request.args.get('page', 1, type=int)
    usuarios = Usuario.query.paginate(page=page, per_page=20)
    return render_template('admin/usuarios.html', usuarios=usuarios)

@admin_bp.route('/admin/api/usuarios/buscar')
@admin_required
def admin_buscar_usuarios():
    """
    Endpoint AJAX para buscar usuarios por nombre/email.
    Retorna JSON para autocompletado typeahead.
    """
    query = request.args.get('q', '')
    if not query or len(query) < 2:
        return {'results': []}
    
    # Búsqueda insensible a mayúsculas
    usuarios = Usuario.query.filter(
        or_(
            Usuario.nombre.ilike(f'%{query}%'),
            Usuario.email.ilike(f'%{query}%')
        )
    ).limit(20).all()
    
    results = [
        {
            'id': u.id,
            'text': f"{u.nombre} ({u.email})"
        } for u in usuarios
    ]
    
    return {'results': results}

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
        
        # Crear usuario
        usuario = Usuario(
            nombre=nombre,
            email=email,
            password=generate_password_hash(password),
            rol=rol,
            dias_vacaciones=dias_vacaciones
        )
        db.session.add(usuario)
        db.session.flush()  # ✅ Genera el usuario.id sin hacer commit
        
        # ✅ NUEVO: Crear saldo automáticamente para el año actual
        from datetime import datetime
        from src.models import SaldoVacaciones
        
        anio_actual = datetime.now().year
        saldo = SaldoVacaciones(
            usuario_id=usuario.id,
            anio=anio_actual,
            dias_totales=dias_vacaciones,
            dias_disfrutados=0,
            dias_carryover=0
        )
        db.session.add(saldo)
        
        db.session.commit()

        # Log de auditoría
        current_app.logger.info(
            f"Usuario creado: {email}",
            extra={
                "event.action": "user-creation",
                "event.category": ["iam", "configuration"],
                "user.target.email": email,
                "user.target.role": rol,
                "actor.email": current_user.email, # Quién hizo la acción
                "actor.id": current_user.id
            }
        )
        
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

        password = request.form.get('password')
        password_changed = False
        
        if password:
            usuario.password = generate_password_hash(password)
            password_changed = True

        
        db.session.commit()

        # --- LOGGING INICIO ---
        current_app.logger.info(
            f"Usuario editado: {usuario.email}",
            extra={
                "event.action": "user-update",
                "event.category": ["iam", "configuration"],
                "event.module": "admin",
                "user.target.id": usuario.id,
                "user.target.email": usuario.email,
                "user.target.role": usuario.rol,
                "user.changes.password": password_changed, # Info útil de seguridad
                "actor.email": current_user.email,
                "actor.id": current_user.id,
                "source.ip": request.remote_addr
            }
        )
        # --- LOGGING FIN ---
        
        flash('Usuario actualizado correctamente', 'success')
        return redirect(url_for('admin.admin_usuarios'))
    
    return render_template('admin/editar_usuario.html', usuario=usuario)

@admin_bp.route('/admin/usuarios/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    db.session.delete(usuario)
    db.session.commit()

    # --- LOGGING INICIO ---
    current_app.logger.info(
        f"Usuario eliminado: {target_email}",
        extra={
            "event.action": "user-deletion",
            "event.category": ["iam", "configuration"],
            "event.outcome": "success",
            "user.target.id": target_id,
            "user.target.email": target_email,
            "user.target.role": target_role,
            "actor.email": current_user.email,
            "actor.id": current_user.id,
            "source.ip": request.remote_addr
        }
    )
    # --- LOGGING FIN ---
    
    flash('Usuario eliminado correctamente', 'success')
    return redirect(url_for('admin.admin_usuarios'))

# --- APROBADORES ---
@admin_bp.route('/admin/aprobadores')
@admin_required
def admin_aprobadores():
    # Optimización N+1
    aprobadores = Aprobador.query.options(
        db.joinedload(Aprobador.usuario),
        db.joinedload(Aprobador.aprobador)
    ).all()
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
    # Obtener filtro de la URL (default: solo activos)
    mostrar = request.args.get('mostrar', 'activos')
    
    if mostrar == 'todos':
        festivos = Festivo.query.order_by(Festivo.fecha.desc()).all()
    elif mostrar == 'archivados':
        festivos = Festivo.query.filter_by(activo=False).order_by(Festivo.fecha.desc()).all()
    else:  # 'activos' (default)
        festivos = Festivo.query.filter_by(activo=True).order_by(Festivo.fecha.desc()).all()
    
    return render_template('admin/festivos.html', festivos=festivos, mostrar=mostrar)

@admin_bp.route('/admin/festivos/crear', methods=['POST'])
@admin_required
def admin_crear_festivo():
    from src.utils import invalidar_cache_festivos
    
    fecha = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date()
    descripcion = request.form.get('descripcion')
    
    if Festivo.query.filter_by(fecha=fecha).first():
        flash('Este festivo ya existe', 'warning')
        return redirect(url_for('admin.admin_festivos'))
    
    festivo = Festivo(
        fecha=fecha, 
        descripcion=descripcion,
        activo=True  # ✅ Explícitamente activo
    )
    db.session.add(festivo)
    db.session.commit()
    
    invalidar_cache_festivos()
    
    flash('Festivo añadido correctamente', 'success')
    return redirect(url_for('admin.admin_festivos'))

# Endpoint para archivar/desarchivar
@admin_bp.route('/admin/festivos/toggle/<int:id>', methods=['POST'])
@admin_required
def admin_toggle_festivo(id):
    from src.utils import invalidar_cache_festivos
    
    festivo = Festivo.query.get_or_404(id)
    festivo.activo = not festivo.activo
    db.session.commit()
    
    invalidar_cache_festivos()
    
    estado = "activado" if festivo.activo else "archivado"
    flash(f'Festivo {estado} correctamente', 'success')
    return redirect(url_for('admin.admin_festivos'))

@admin_bp.route('/admin/festivos/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_festivo(id):
    festivo = Festivo.query.get_or_404(id)
    db.session.delete(festivo)
    db.session.commit()
    
    invalidar_cache_festivos()  # ✅ AÑADIR ESTA LÍNEA
    
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
    """
    Panel de resumen global anual con estadísticas agregadas y paginación real.
    """
    # 1. FILTROS Y PARÁMETROS
    usuario_id = request.args.get('usuario_id', type=int)
    anio = request.args.get('anio', type=int, default=datetime.now().year)
    page = request.args.get('page', 1, type=int)
    per_page = 10 
    
    # Generar lista de años dinámicamente (año actual + 4 anteriores)
    anio_actual_servidor = datetime.now().year
    anios_disponibles = list(range(anio_actual_servidor - 4, anio_actual_servidor + 1))
    anios_disponibles.reverse()  # Mostrar del más reciente al más antiguo
    
    fecha_inicio_anio = date(anio, 1, 1)
    fecha_fin_anio = date(anio, 12, 31)

    # 2. QUERY BASE DE USUARIOS
    query_base_usuarios = Usuario.query
    
    if usuario_id:
        query_base_usuarios = query_base_usuarios.filter(Usuario.id == usuario_id)

    # 3. CÁLCULO DE TOTALES GLOBALES (REALES, TODO EL AÑO)
    # Suma total de días asignados
    total_asignados_query = db.session.query(func.sum(Usuario.dias_vacaciones))
    
    if usuario_id:
        total_asignados_query = total_asignados_query.filter(Usuario.id == usuario_id)
    
    total_asignados_val = total_asignados_query.scalar() or 0

    # Suma total de días disfrutados
    total_disfrutados_query = db.session.query(
        func.sum(SolicitudVacaciones.dias_solicitados)
    ).filter(
        SolicitudVacaciones.estado == 'aprobada',
        SolicitudVacaciones.es_actual == True,
        SolicitudVacaciones.tipo_accion != 'cancelacion',
        SolicitudVacaciones.fecha_inicio >= fecha_inicio_anio,
        SolicitudVacaciones.fecha_inicio <= fecha_fin_anio
    )
    
    if usuario_id:
        total_disfrutados_query = total_disfrutados_query.filter(Usuario.id == usuario_id)
        
    total_dias_disfrutados = int(total_disfrutados_query.scalar() or 0)
    total_dias_restantes = int(total_asignados_val) - total_dias_disfrutados

    # 4. PAGINACIÓN DE USUARIOS
    pagination = query_base_usuarios.paginate(page=page, per_page=per_page, error_out=False)
    usuarios_a_mostrar = pagination.items

    if not usuarios_a_mostrar:
        return render_template('admin/resumen.html', 
                             resumen_usuarios=[],
                             pagination=pagination,
                             usuario_seleccionado=None,
                             anio_actual=anio,
                             anios_disponibles=anios_disponibles,
                             total_dias_disfrutados=0,
                             total_dias_restantes=0)

    # 5. DETALLE PARA LA PÁGINA ACTUAL (OPTIMIZADO)
    ids_pagina = [u.id for u in usuarios_a_mostrar]

    # Query fichajes (solo para usuarios visibles)
    horas_trabajadas_expr = (
        ((extract('hour', Fichaje.hora_salida) * 3600 + 
          extract('minute', Fichaje.hora_salida) * 60) -
         (extract('hour', Fichaje.hora_entrada) * 3600 + 
          extract('minute', Fichaje.hora_entrada) * 60)
        ) / 3600.0
    ) - (cast(Fichaje.pausa, Float) / 60.0)

    fichajes_stats = db.session.query(
        Fichaje.usuario_id,
        func.count(Fichaje.id).label('total_fichajes'),
        func.sum(horas_trabajadas_expr).label('total_horas')
    ).filter(
        Fichaje.usuario_id.in_(ids_pagina),
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion',
        Fichaje.fecha >= fecha_inicio_anio,
        Fichaje.fecha <= fecha_fin_anio,
        Fichaje.hora_salida.isnot(None)
    ).group_by(Fichaje.usuario_id).all()

    fichajes_dict = {s.usuario_id: {'total_fichajes': s.total_fichajes, 'total_horas': float(s.total_horas or 0)} for s in fichajes_stats}

    # Query vacaciones (solo para usuarios visibles)
    vacaciones_stats = db.session.query(
        SolicitudVacaciones.usuario_id,
        func.sum(SolicitudVacaciones.dias_solicitados).label('dias_disfrutados')
    ).filter(
        SolicitudVacaciones.usuario_id.in_(ids_pagina),
        SolicitudVacaciones.estado == 'aprobada',
        SolicitudVacaciones.es_actual == True,
        SolicitudVacaciones.tipo_accion != 'cancelacion',
        SolicitudVacaciones.fecha_inicio >= fecha_inicio_anio,
        SolicitudVacaciones.fecha_inicio <= fecha_fin_anio
    ).group_by(SolicitudVacaciones.usuario_id).all()

    vacaciones_dict = {s.usuario_id: int(s.dias_disfrutados or 0) for s in vacaciones_stats}

    # Construir lista final
    resumen_usuarios = []
    for usuario in usuarios_a_mostrar:
        f_stats = fichajes_dict.get(usuario.id, {'total_fichajes': 0, 'total_horas': 0.0})
        d_disfrutados = vacaciones_dict.get(usuario.id, 0)
        resumen_usuarios.append({
            'usuario': usuario,
            'fichajes_count': f_stats['total_fichajes'],
            'horas_totales': f_stats['total_horas'],
            'dias_vacaciones_totales': usuario.dias_vacaciones,
            'dias_disfrutados': d_disfrutados,
            'dias_restantes': usuario.dias_vacaciones - d_disfrutados
        })

    usuario_obj = Usuario.query.get(usuario_id) if usuario_id else None

    return render_template('admin/resumen.html', 
                         resumen_usuarios=resumen_usuarios, 
                         pagination=pagination,
                         usuario_seleccionado=usuario_obj,
                         anio_actual=anio,
                         anios_disponibles=anios_disponibles,
                         total_dias_asignados=int(total_asignados_val),
                         total_dias_disfrutados=total_dias_disfrutados,
                         total_dias_restantes=total_dias_restantes)

# --- CSV EXPORT ENDPOINTS ---
@admin_bp.route('/admin/resumen/export')
@admin_required
def admin_resumen_export():
    """Export all users vacation summary to CSV."""
    import io
    import csv
    from flask import Response
    
    anio = request.args.get('anio', type=int, default=datetime.now().year)
    usuario_id = request.args.get('usuario_id', type=int)
    
    fecha_inicio_anio = date(anio, 1, 1)
    fecha_fin_anio = date(anio, 12, 31)
    
    # Query all users (or filtered)
    query = Usuario.query
    if usuario_id:
        query = query.filter(Usuario.id == usuario_id)
    usuarios = query.all()
    
    # Get vacation stats
    vacaciones_stats = db.session.query(
        SolicitudVacaciones.usuario_id,
        func.sum(SolicitudVacaciones.dias_solicitados).label('dias_disfrutados')
    ).filter(
        SolicitudVacaciones.estado == 'aprobada',
        SolicitudVacaciones.es_actual == True,
        SolicitudVacaciones.tipo_accion != 'cancelacion',
        SolicitudVacaciones.fecha_inicio >= fecha_inicio_anio,
        SolicitudVacaciones.fecha_inicio <= fecha_fin_anio
    ).group_by(SolicitudVacaciones.usuario_id).all()
    
    vacaciones_dict = {s.usuario_id: int(s.dias_disfrutados or 0) for s in vacaciones_stats}
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Usuario', 'Email', 'Rol', 'Días Totales', 'Disfrutados', 'Restantes'])
    
    for u in usuarios:
        disfrutados = vacaciones_dict.get(u.id, 0)
        writer.writerow([u.nombre, u.email, u.rol, u.dias_vacaciones, disfrutados, u.dias_vacaciones - disfrutados])
    
    # Return with BOM for Excel UTF-8 compatibility
    csv_content = '\ufeff' + output.getvalue()
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=resumen_vacaciones_{anio}.csv'}
    )

@admin_bp.route('/admin/fichajes/export')
@admin_required
def admin_fichajes_export():
    """Export fichajes to CSV with current filters."""
    import io
    import csv
    from flask import Response
    from calendar import monthrange
    
    usuario_id = request.args.get('usuario_id', type=int)
    hoy = date.today()
    mes = request.args.get('mes', hoy.month, type=int)
    anio = request.args.get('anio', hoy.year, type=int)
    
    _, ultimo_dia = monthrange(anio, mes)
    fecha_inicio = date(anio, mes, 1)
    fecha_fin = date(anio, mes, ultimo_dia)
    
    query = Fichaje.query.filter(
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion',
        Fichaje.fecha >= fecha_inicio,
        Fichaje.fecha <= fecha_fin
    )
    
    if usuario_id:
        query = query.filter(Fichaje.usuario_id == usuario_id)
    
    fichajes = query.order_by(Fichaje.fecha.desc(), Fichaje.hora_entrada.asc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Fecha', 'Usuario', 'Email', 'Entrada', 'Salida', 'Pausa (min)', 'Horas'])
    
    for f in fichajes:
        horas = ((f.hora_salida.hour * 60 + f.hora_salida.minute) - 
                 (f.hora_entrada.hour * 60 + f.hora_entrada.minute)) / 60 - (f.pausa / 60)
        writer.writerow([
            f.fecha.strftime('%d/%m/%Y'),
            f.usuario.nombre,
            f.usuario.email,
            f.hora_entrada.strftime('%H:%M'),
            f.hora_salida.strftime('%H:%M'),
            f.pausa,
            f'{horas:.2f}'
        ])
    
    csv_content = '\ufeff' + output.getvalue()
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=fichajes_{mes:02d}_{anio}.csv'}
    )

@admin_bp.route('/admin/ausencias/export')
@admin_required
def admin_ausencias_export():
    """Export ausencias to CSV with current filters."""
    import io
    import csv
    from flask import Response
    
    usuario_id = request.args.get('usuario_id', type=int)
    tipo_filtro = request.args.get('tipo', 'todos')
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    
    query_vac = SolicitudVacaciones.query.filter_by(es_actual=True)
    query_bajas = SolicitudBaja.query.filter_by(es_actual=True)
    
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
    
    resultados = []
    
    if tipo_filtro in ['todos', 'vacaciones']:
        for v in query_vac.all():
            resultados.append({
                'empleado': v.usuario.nombre,
                'email': v.usuario.email,
                'tipo': 'Vacaciones',
                'fecha_inicio': v.fecha_inicio.strftime('%d/%m/%Y'),
                'fecha_fin': v.fecha_fin.strftime('%d/%m/%Y'),
                'dias': v.dias_solicitados,
                'estado': v.estado
            })
    
    if tipo_filtro in ['todos', 'bajas']:
        for b in query_bajas.all():
            resultados.append({
                'empleado': b.usuario.nombre,
                'email': b.usuario.email,
                'tipo': b.tipo_ausencia.nombre if b.tipo_ausencia else 'Baja',
                'fecha_inicio': b.fecha_inicio.strftime('%d/%m/%Y'),
                'fecha_fin': b.fecha_fin.strftime('%d/%m/%Y'),
                'dias': b.dias_solicitados,
                'estado': b.estado
            })
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Empleado', 'Email', 'Tipo', 'Fecha Inicio', 'Fecha Fin', 'Días', 'Estado'])
    
    for r in resultados:
        writer.writerow([r['empleado'], r['email'], r['tipo'], r['fecha_inicio'], r['fecha_fin'], r['dias'], r['estado']])
    
    csv_content = '\ufeff' + output.getvalue()
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=listado_ausencias.csv'}
    )

def _generar_detalle_cambios_fichaje(fichaje_actual):
    """
    Genera un detalle de los cambios realizados en un fichaje comparando
    con la versión anterior. Retorna solo los campos que cambiaron.
    
    Args:
        fichaje_actual: El fichaje actual (versión modificada)
        
    Returns:
        str: Detalle de cambios en formato "campo: antiguo → nuevo"
    """
    # Si es versión 1 o eliminación, mostrar info básica
    if fichaje_actual.version == 1:
        return f"{fichaje_actual.fecha.strftime('%d/%m/%Y')} ({fichaje_actual.hora_entrada.strftime('%H:%M')} - {fichaje_actual.hora_salida.strftime('%H:%M')})"
    
    if fichaje_actual.tipo_accion == 'eliminacion':
        return f"{fichaje_actual.fecha.strftime('%d/%m/%Y')} ({fichaje_actual.hora_entrada.strftime('%H:%M')} - {fichaje_actual.hora_salida.strftime('%H:%M')})"
    
    # Buscar la versión anterior
    version_anterior = Fichaje.query.filter(
        Fichaje.grupo_id == fichaje_actual.grupo_id,
        Fichaje.version == fichaje_actual.version - 1
    ).first()
    
    if not version_anterior:
        # Si no hay versión anterior, mostrar info básica
        return f"{fichaje_actual.fecha.strftime('%d/%m/%Y')} ({fichaje_actual.hora_entrada.strftime('%H:%M')} - {fichaje_actual.hora_salida.strftime('%H:%M')})"
    
    # Comparar campos y generar lista de cambios
    cambios = []
    
    # Comparar fecha
    if fichaje_actual.fecha != version_anterior.fecha:
        cambios.append(f"Fecha: {version_anterior.fecha.strftime('%d/%m/%Y')} → {fichaje_actual.fecha.strftime('%d/%m/%Y')}")
    
    # Comparar hora de entrada
    if fichaje_actual.hora_entrada != version_anterior.hora_entrada:
        cambios.append(f"Entrada: {version_anterior.hora_entrada.strftime('%H:%M')} → {fichaje_actual.hora_entrada.strftime('%H:%M')}")
    
    # Comparar hora de salida
    if fichaje_actual.hora_salida != version_anterior.hora_salida:
        cambios.append(f"Salida: {version_anterior.hora_salida.strftime('%H:%M')} → {fichaje_actual.hora_salida.strftime('%H:%M')}")
    
    # Comparar pausa
    if fichaje_actual.pausa != version_anterior.pausa:
        cambios.append(f"Pausa: {version_anterior.pausa}min → {fichaje_actual.pausa}min")
    
    # Si no hay cambios detectados (raro), mostrar info básica
    if not cambios:
        return f"{fichaje_actual.fecha.strftime('%d/%m/%Y')} (sin cambios detectados)"
    
    # Unir cambios con saltos de línea
    return "\n".join(cambios)


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
            'detalle': _generar_detalle_cambios_fichaje(f),
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
    
    # Generar lista de años dinámicamente (año actual + 4 anteriores)
    anio_actual_servidor = datetime.now().year
    anios_disponibles = list(range(anio_actual_servidor - 4, anio_actual_servidor + 1))
    anios_disponibles.reverse()  # Mostrar del más reciente al más antiguo
        
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
    query = query.order_by(Fichaje.fecha.desc(), Fichaje.hora_entrada.asc())
    
    # 5. PAGINACIÓN
    page = request.args.get('page', type=int, default=1)
    per_page = 50
    
    pagination = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    # 6. Calcular totales para el resumen rápido (Query Separada)
    total_horas = db.session.query(
        func.sum(
            (
                (extract('hour', Fichaje.hora_salida) * 3600 + 
                 extract('minute', Fichaje.hora_salida) * 60) -
                (extract('hour', Fichaje.hora_entrada) * 3600 + 
                 extract('minute', Fichaje.hora_entrada) * 60)
            ) / 3600.0 - (cast(Fichaje.pausa, Float) / 60.0)
        )
    ).filter(
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion',
        Fichaje.fecha >= fecha_inicio,
        Fichaje.fecha <= fecha_fin,
        Fichaje.hora_salida.isnot(None)
    )
    
    if usuario_id:
        total_horas = total_horas.filter(Fichaje.usuario_id == usuario_id)
        
    total_horas = total_horas.scalar() or 0
    
    # usuarios = Usuario.query.order_by(Usuario.nombre).all() <-- ELIMINADO
    
    usuario_obj = None
    if usuario_id:
        usuario_obj = Usuario.query.get(usuario_id)
    
    return render_template('/admin/admin_fichajes.html',
                           fichajes=pagination.items,
                           pagination=pagination,
                           # usuarios=usuarios, <-- ELIMINADO
                           usuario_seleccionado=usuario_obj, # Pasamos objeto completo
                           mes_actual=mes,
                           anio_actual=anio,
                           anios_disponibles=anios_disponibles,
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
    # usuarios = Usuario.query.order_by(Usuario.nombre).all() <-- ELIMINADO
    
    usuario_obj = None
    if usuario_id:
        usuario_obj = Usuario.query.get(usuario_id)
    
    return render_template('admin/gestion_ausencias.html', 
                           ausencias=resultados,
                           # usuarios=usuarios, <-- ELIMINADO
                           usuario_seleccionado=usuario_obj,
                           tipo_seleccionado=tipo_filtro,
                           fecha_inicio=fecha_inicio_str,
                           fecha_fin=fecha_fin_str,
                           total_dias=total_dias)
