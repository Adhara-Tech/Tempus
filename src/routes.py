from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from datetime import datetime, timedelta, date
from calendar import monthrange

from . import app, db, admin_required, aprobador_required, google_bp
from .utils import  calcular_dias_laborables
from .models import Usuario, Fichaje, SolicitudVacaciones, SolicitudBaja, Aprobador, Festivo
from .email_service import enviar_email_solicitud, enviar_email_respuesta
from .google_calendar import sincronizar_vacaciones_a_google, sincronizar_baja_a_google, eliminar_evento_google
from flask_dance.consumer import oauth_authorized
from flask_dance.contrib.google import google

@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    if not google.authorized:
        return False
    
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Error al obtener información de Google", "danger")
        return False
    
    google_info = resp.json()
    email = google_info["email"]
    
    user = Usuario.query.filter_by(email=email).first()
    if user:
        login_user(user)
        flash("Inicio de sesión exitoso con Google", "success")
    else:
        flash("No existe un usuario con este email.", "danger")
        return redirect(url_for("login"))
        
    return redirect(url_for("index"))

# Rutas de autenticación
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and check_password_hash(usuario.password, password):
            login_user(usuario)
            flash('Inicio de sesión exitoso', 'success')
            return redirect(url_for('index'))
        else:
            flash('Email o contraseña incorrectos', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('login'))

# Ruta principal
@app.route('/')
@login_required
def index():
    solicitudes_pendientes_count = 0
    if current_user.rol in ['aprobador', 'admin']:
        usuarios_ids = [r.usuario_id for r in Aprobador.query.filter_by(aprobador_id=current_user.id).all()]
        
        count_vac = SolicitudVacaciones.query.filter(
            SolicitudVacaciones.usuario_id.in_(usuarios_ids),
            SolicitudVacaciones.estado == 'pendiente'
        ).count()
        
        count_bajas = SolicitudBaja.query.filter(
            SolicitudBaja.usuario_id.in_(usuarios_ids),
            SolicitudBaja.estado == 'pendiente'
        ).count()
        
        solicitudes_pendientes_count = count_vac + count_bajas
    
    return render_template('index.html', solicitudes_pendientes_count=solicitudes_pendientes_count)

# Rutas de fichaje
@app.route('/fichajes')
@login_required
def fichajes():
    # Obtener parámetros o defaults
    hoy = datetime.now()
    mes = request.args.get('mes', type=int, default=hoy.month)
    anio = request.args.get('anio', type=int, default=hoy.year)

    # Calcular rango de fechas
    try:
        _, ultimo_dia = monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)
    except ValueError:
        # Fallback si los parámetros son inválidos
        mes = hoy.month
        anio = hoy.year
        _, ultimo_dia = monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

    fichajes = Fichaje.query.filter_by(usuario_id=current_user.id)\
        .filter(Fichaje.fecha >= fecha_inicio)\
        .filter(Fichaje.fecha <= fecha_fin)\
        .order_by(Fichaje.fecha.desc()).all()
        
    return render_template('fichajes.html', fichajes=fichajes, mes_actual=mes, anio_actual=anio)

@app.route('/fichajes/crear', methods=['GET', 'POST'])
@login_required
def crear_fichaje():
    if request.method == 'POST':
        fecha = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date()
        hora_entrada = datetime.strptime(request.form.get('hora_entrada'), '%H:%M').time()
        hora_salida = datetime.strptime(request.form.get('hora_salida'), '%H:%M').time()
        
        fichaje = Fichaje(
            usuario_id=current_user.id,
            fecha=fecha,
            hora_entrada=hora_entrada,
            hora_salida=hora_salida
        )
        
        db.session.add(fichaje)
        db.session.commit()
        flash('Fichaje registrado correctamente', 'success')
        return redirect(url_for('fichajes'))
    
    return render_template('crear_fichaje.html', now=datetime.now)

@app.route('/fichajes/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_fichaje(id):
    fichaje = Fichaje.query.get_or_404(id)
    
    if fichaje.usuario_id != current_user.id and current_user.rol != 'admin':
        flash('No tienes permisos para editar este fichaje', 'danger')
        return redirect(url_for('fichajes'))
    
    if request.method == 'POST':
        fichaje.fecha = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date()
        fichaje.hora_entrada = datetime.strptime(request.form.get('hora_entrada'), '%H:%M').time()
        fichaje.hora_salida = datetime.strptime(request.form.get('hora_salida'), '%H:%M').time()
        
        db.session.commit()
        flash('Fichaje actualizado correctamente', 'success')
        return redirect(url_for('fichajes'))
    
    return render_template('editar_fichaje.html', fichaje=fichaje, now=datetime.now)

@app.route('/fichajes/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_fichaje(id):
    fichaje = Fichaje.query.get_or_404(id)
    
    if fichaje.usuario_id != current_user.id and current_user.rol != 'admin':
        flash('No tienes permisos para eliminar este fichaje', 'danger')
        return redirect(url_for('fichajes'))
    
    db.session.delete(fichaje)
    db.session.commit()
    flash('Fichaje eliminado correctamente', 'success')
    return redirect(url_for('fichajes'))

@app.route('/resumen')
@login_required
def resumen():
    hoy = date.today()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    
    fichajes_hoy = Fichaje.query.filter_by(
        usuario_id=current_user.id,
        fecha=hoy
    ).all()
    horas_hoy = sum([f.horas_trabajadas() for f in fichajes_hoy])
    
    fichajes_semana = Fichaje.query.filter(
        Fichaje.usuario_id == current_user.id,
        Fichaje.fecha >= inicio_semana,
        Fichaje.fecha <= hoy
    ).all()
    horas_semana = sum([f.horas_trabajadas() for f in fichajes_semana])
    
    return render_template('resumen.html', 
                         horas_hoy=horas_hoy, 
                         horas_semana=horas_semana,
                         fichajes_hoy=fichajes_hoy,
                         fichajes_semana=fichajes_semana,
                         now=datetime.now)

# Rutas de vacaciones
@app.route('/vacaciones')
@login_required
def vacaciones():
    solicitudes = SolicitudVacaciones.query.filter_by(usuario_id=current_user.id).order_by(
        SolicitudVacaciones.fecha_solicitud.desc()
    ).all()
    return render_template('vacaciones.html', solicitudes=solicitudes)

@app.route('/vacaciones/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_vacaciones():
    if request.method == 'POST':
        fecha_inicio = datetime.strptime(request.form.get('fecha_inicio'), '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(request.form.get('fecha_fin'), '%Y-%m-%d').date()
        motivo = request.form.get('motivo', '')
        
        dias_solicitados = calcular_dias_laborables(fecha_inicio, fecha_fin)
        
        solicitud = SolicitudVacaciones(
            usuario_id=current_user.id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            dias_solicitados=dias_solicitados,
            motivo=motivo,
            estado='pendiente'
        )
        
        db.session.add(solicitud)
        db.session.commit()
        
        aprobadores = Aprobador.query.filter_by(usuario_id=current_user.id).all()
        for rel in aprobadores:
            enviar_email_solicitud(rel.aprobador, current_user, solicitud)
        
        flash('Solicitud de vacaciones enviada correctamente', 'success')
        return redirect(url_for('vacaciones'))
    
    return render_template('solicitar_vacaciones.html')

@app.route('/vacaciones/calcular-dias', methods=['POST'])
@login_required
def calcular_dias_ajax():
    try:
        data = request.get_json()
        fecha_inicio_str = data.get('fecha_inicio')
        fecha_fin_str = data.get('fecha_fin')
        
        if not fecha_inicio_str or not fecha_fin_str:
            return jsonify({'dias': 0, 'error': 'Faltan fechas.'}), 400
            
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        
        if fecha_fin < fecha_inicio:
            return jsonify({'dias': 0, 'error': 'La fecha de fin no puede ser anterior a la de inicio.'})
        
        dias = calcular_dias_laborables(fecha_inicio, fecha_fin)
        return jsonify({'dias': dias})
        
    except Exception as e:
        return jsonify({'dias': 0, 'error': str(e)}), 400

# Rutas de Bajas
@app.route('/bajas')
@login_required
def bajas():
    solicitudes = SolicitudBaja.query.filter_by(usuario_id=current_user.id).order_by(
        SolicitudBaja.fecha_solicitud.desc()
    ).all()
    return render_template('bajas.html', solicitudes=solicitudes)

@app.route('/bajas/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_baja():
    if request.method == 'POST':
        fecha_inicio = datetime.strptime(request.form.get('fecha_inicio'), '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(request.form.get('fecha_fin'), '%Y-%m-%d').date()
        motivo = request.form.get('motivo', '')
        
        if not motivo:
            flash('El motivo es obligatorio para las bajas.', 'danger')
            return redirect(url_for('solicitar_baja'))
            
        dias_solicitados = calcular_dias_laborables(fecha_inicio, fecha_fin)
        
        solicitud = SolicitudBaja(
            usuario_id=current_user.id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            dias_solicitados=dias_solicitados,
            motivo=motivo,
            estado='pendiente'
        )
        
        db.session.add(solicitud)
        db.session.commit()
        
        aprobadores = Aprobador.query.filter_by(usuario_id=current_user.id).all()
        for rel in aprobadores:
            enviar_email_solicitud(rel.aprobador, current_user, solicitud)
        
        flash('Solicitud de baja enviada correctamente', 'success')
        return redirect(url_for('bajas'))
    
    return render_template('solicitar_baja.html')

@app.route('/bajas/responder/<int:id>/<accion>', methods=['POST'])
@aprobador_required
def responder_baja(id, accion):
    solicitud = SolicitudBaja.query.get_or_404(id)
    
    # Verificación de seguridad
    if solicitud.estado != 'pendiente':
        flash('Esta solicitud de baja ya ha sido procesada.', 'warning')
        return redirect(url_for('aprobar_solicitudes'))
    
    mensaje = ''

    if accion == 'aprobar':
        solicitud.estado = 'aprobada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        
        # 🆕 SINCRONIZAR BAJA CON GOOGLE CALENDAR
        event_id = sincronizar_baja_a_google(solicitud)
        if event_id:
            solicitud.google_event_id = event_id
            mensaje = 'Baja aprobada y sincronizada con Google Calendar correctamente.'
        else:
            mensaje = 'Baja aprobada (⚠ No se pudo sincronizar con el calendario).'
            
    elif accion == 'rechazar':
        solicitud.estado = 'rechazada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        solicitud.comentarios = request.form.get('comentarios', '')
        mensaje = 'Baja rechazada correctamente.'
    
    try:
        db.session.commit()
        # Reutilizamos la misma función de email ya que los campos son compatibles
        enviar_email_respuesta(solicitud.usuario, solicitud)
        flash(mensaje, 'success' if '⚠' not in mensaje else 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la baja: {str(e)}', 'danger')

    return redirect(url_for('aprobar_solicitudes'))

# Rutas de Aprobación
@app.route('/aprobar-solicitudes')
@aprobador_required
def aprobar_solicitudes():
    usuarios_ids = [r.usuario_id for r in Aprobador.query.filter_by(aprobador_id=current_user.id).all()]
    
    solicitudes_vac = SolicitudVacaciones.query.filter(
        SolicitudVacaciones.usuario_id.in_(usuarios_ids),
        SolicitudVacaciones.estado == 'pendiente'
    ).order_by(SolicitudVacaciones.fecha_solicitud.desc()).all()
    
    solicitudes_bajas = SolicitudBaja.query.filter(
        SolicitudBaja.usuario_id.in_(usuarios_ids),
        SolicitudBaja.estado == 'pendiente'
    ).order_by(SolicitudBaja.fecha_solicitud.desc()).all()
    
    return render_template('aprobar_solicitudes.html', 
                           solicitudes_vac=solicitudes_vac, 
                           solicitudes_bajas=solicitudes_bajas)

@app.route('/vacaciones/responder/<int:id>/<accion>', methods=['POST'])
@aprobador_required
def responder_solicitud(id, accion):
    solicitud = SolicitudVacaciones.query.get_or_404(id)
    
    # Verificación de seguridad básica (opcional: validar que estaba pendiente)
    if solicitud.estado != 'pendiente':
        flash('Esta solicitud ya ha sido procesada.', 'warning')
        return redirect(url_for('aprobar_solicitudes')) # Ajusta esta ruta a tu vista de listado
    
    mensaje = ''

    if accion == 'aprobar':
        solicitud.estado = 'aprobada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        
        # SINCRONIZAR CON GOOGLE CALENDAR
        # Intentamos crear el evento. Si falla, event_id será None pero no rompe el flujo.
        event_id = sincronizar_vacaciones_a_google(solicitud)
        if event_id:
            solicitud.google_event_id = event_id
            mensaje = 'Solicitud aprobada y sincronizada con Google Calendar correctamente.'
        else:
            mensaje = 'Solicitud aprobada (⚠ No se pudo sincronizar con el calendario).'
        
    elif accion == 'rechazar':
        solicitud.estado = 'rechazada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        solicitud.comentarios = request.form.get('comentarios', '')
        mensaje = 'Solicitud rechazada correctamente.'
    
    try:
        db.session.commit()
        # Enviar notificación por email
        enviar_email_respuesta(solicitud.usuario, solicitud)
        flash(mensaje, 'success' if '⚠' not in mensaje else 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la solicitud: {str(e)}', 'danger')

    return redirect(url_for('aprobar_solicitudes'))

# Cronograma
@app.route('/cronograma')
@login_required
def cronograma():
    solicitudes_vac = SolicitudVacaciones.query.filter_by(estado='aprobada').all()
    solicitudes_bajas = SolicitudBaja.query.filter_by(estado='aprobada').all()
    
    eventos = []
    for s in solicitudes_vac:
        eventos.append({
            'title': f"{s.usuario.nombre} - Vacaciones",
            'start': s.fecha_inicio.isoformat(),
            'end': (s.fecha_fin + timedelta(days=1)).isoformat(),
            'color': '#28a745',
            'usuario': s.usuario.nombre
        })
        
    for s in solicitudes_bajas:
        eventos.append({
            'title': f"{s.usuario.nombre} - Baja",
            'start': s.fecha_inicio.isoformat(),
            'end': (s.fecha_fin + timedelta(days=1)).isoformat(),
            'color': '#dc3545',
            'usuario': s.usuario.nombre
        })
    
    festivos = Festivo.query.all()
    for f in festivos:
        eventos.append({
            'title': f.descripcion,
            'start': f.fecha.isoformat(),
            'display': 'background',
            'color': '#ff9f89'
        })
    
    return render_template('cronograma.html', eventos=eventos)

# Rutas de administración
@app.route('/admin/usuarios')
def admin_usuarios():
    usuarios = Usuario.query.all()
    return render_template('admin/usuarios.html', usuarios=usuarios)

@app.route('/admin/usuarios/crear', methods=['GET', 'POST'])
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
            return redirect(url_for('admin_crear_usuario'))
        
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
        return redirect(url_for('admin_usuarios'))
    
    return render_template('admin/crear_usuario.html')

@app.route('/admin/usuarios/editar/<int:id>', methods=['GET', 'POST'])
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
        return redirect(url_for('admin_usuarios'))
    
    return render_template('admin/editar_usuario.html', usuario=usuario)

@app.route('/admin/usuarios/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    db.session.delete(usuario)
    db.session.commit()
    flash('Usuario eliminado correctamente', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/aprobadores')
@admin_required
def admin_aprobadores():
    aprobadores = Aprobador.query.all()
    usuarios = Usuario.query.all()
    return render_template('admin/aprobadores.html', aprobadores=aprobadores, usuarios=usuarios)

@app.route('/admin/aprobadores/asignar', methods=['POST'])
@admin_required
def admin_asignar_aprobador():
    usuario_id = int(request.form.get('usuario_id'))
    aprobador_id = int(request.form.get('aprobador_id'))
    
    if Aprobador.query.filter_by(usuario_id=usuario_id, aprobador_id=aprobador_id).first():
        flash('Esta relación ya existe', 'warning')
        return redirect(url_for('admin_aprobadores'))
    
    relacion = Aprobador(usuario_id=usuario_id, aprobador_id=aprobador_id)
    db.session.add(relacion)
    db.session.commit()
    flash('Aprobador asignado correctamente', 'success')
    return redirect(url_for('admin_aprobadores'))

@app.route('/admin/aprobadores/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_aprobador(id):
    aprobador = Aprobador.query.get_or_404(id)
    db.session.delete(aprobador)
    db.session.commit()
    flash('Relación eliminada correctamente', 'success')
    return redirect(url_for('admin_aprobadores'))

@app.route('/admin/resumen')
@admin_required
def admin_resumen():
    usuarios = Usuario.query.filter(Usuario.rol != 'admin').all()
    
    # Obtener parámetros o defaults
    hoy = datetime.now()
    mes = request.args.get('mes', type=int, default=hoy.month)
    anio = request.args.get('anio', type=int, default=hoy.year)

    # Calcular rango de fechas
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
        # Filtrar fichajes por rango de fechas
        fichajes = Fichaje.query.filter_by(usuario_id=usuario.id)\
            .filter(Fichaje.fecha >= fecha_inicio)\
            .filter(Fichaje.fecha <= fecha_fin)\
            .all()
        
        dias_aprobados = db.session.query(func.sum(SolicitudVacaciones.dias_solicitados)).filter(
            SolicitudVacaciones.usuario_id == usuario.id,
            SolicitudVacaciones.estado == 'aprobada'
        ).scalar() or 0
        
        resumen_usuarios.append({
            'usuario': usuario,
            'fichajes': fichajes,
            'dias_vacaciones_totales': usuario.dias_vacaciones,
            'dias_disfrutados': dias_aprobados,
            'dias_restantes': usuario.dias_vacaciones - dias_aprobados
        })
    
    return render_template('admin/resumen.html', resumen_usuarios=resumen_usuarios, now=datetime.now, mes_actual=mes, anio_actual=anio)

@app.route('/admin/festivos')
@admin_required
def admin_festivos():
    festivos = Festivo.query.order_by(Festivo.fecha).all()
    return render_template('admin/festivos.html', festivos=festivos)

@app.route('/admin/festivos/crear', methods=['POST'])
@admin_required
def admin_crear_festivo():
    fecha = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date()
    descripcion = request.form.get('descripcion')
    
    if Festivo.query.filter_by(fecha=fecha).first():
        flash('Este festivo ya existe', 'warning')
        return redirect(url_for('admin_festivos'))
    
    festivo = Festivo(fecha=fecha, descripcion=descripcion)
    db.session.add(festivo)
    db.session.commit()
    flash('Festivo añadido correctamente', 'success')
    return redirect(url_for('admin_festivos'))

@app.route('/admin/festivos/eliminar/<int:id>', methods=['POST'])
@admin_required
def admin_eliminar_festivo(id):
    festivo = Festivo.query.get_or_404(id)
    db.session.delete(festivo)
    db.session.commit()
    flash('Festivo eliminado correctamente', 'success')
    return redirect(url_for('admin_festivos'))

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Validate current password
        if not check_password_hash(current_user.password, current_password):
            flash('La contraseña actual es incorrecta', 'danger')
            return redirect(url_for('perfil'))
        
        # Validate new password matches confirmation
        if new_password != confirm_password:
            flash('Las contraseñas nuevas no coinciden', 'danger')
            return redirect(url_for('perfil'))
        
        # Validate password length
        if len(new_password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres', 'danger')
            return redirect(url_for('perfil'))
        
        # Update password
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Contraseña actualizada correctamente', 'success')
        return redirect(url_for('perfil'))
    
    return render_template('perfil.html')