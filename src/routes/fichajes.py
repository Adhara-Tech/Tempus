from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from calendar import monthrange
from sqlalchemy import func, desc, cast, Float
from sqlalchemy.sql import extract
from src.utils import es_festivo, verificar_solapamiento, verificar_solapamiento_fichaje, decimal_to_human
import uuid

from src import db
from src.models import Fichaje
from src.utils import es_festivo, verificar_solapamiento
from . import fichajes_bp

# --- HELPER DE ZONA HORARIA (Sencillo y nativo) ---
def get_user_now():
    """
    Devuelve la fecha y hora actual ajustada a la zona horaria del negocio.
    Por defecto intenta simular Europe/Madrid si el servidor está en UTC.
    """
    now = datetime.utcnow()
    # Ajuste manual simple para Madrid (UTC+1 en invierno, UTC+2 en verano)
    # Una solución más robusta requeriría instalar 'pytz' y configurar la zona en el Usuario.
    # Aquí aplicamos UTC+1 por defecto como base segura para España Peninsular invierno.
    # TODO: En el futuro, instalar 'pytz' y usar: datetime.now(pytz.timezone('Europe/Madrid'))
    
    # Verificamos si estamos en horario de verano (aprox: último domingo marzo a último octubre)
    # Esta es una aproximación básica. Lo ideal es añadir 'pytz' al requirements.txt.
    is_dst = False # Simplificación
    offset = 2 if is_dst else 1 
    
    # Si el servidor ya está en hora local (no UTC), no ajustar.
    # Para Docker/Nube suele ser UTC.
    return now + timedelta(hours=offset)

# --- RUTAS DE FICHAJES ---

@fichajes_bp.route('/fichajes')
@login_required
def listar():
    """
    Lista fichajes del usuario con paginación y filtros por mes/año.
    """
    # ========================================
    # 1. OBTENER PARÁMETROS DE FILTRO Y PAGINACIÓN
    # ========================================
    hoy = datetime.now()
    mes = request.args.get('mes', type=int, default=hoy.month)
    anio = request.args.get('anio', type=int, default=hoy.year)
    page = request.args.get('page', type=int, default=1)
    per_page = 50  # Mostrar 50 fichajes por página

    # ========================================
    # 2. VALIDAR Y CALCULAR RANGO DE FECHAS
    # ========================================
    try:
        _, ultimo_dia = monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)
    except ValueError:
        # Si mes/año inválidos, usar mes actual
        mes = hoy.month
        anio = hoy.year
        _, ultimo_dia = monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

    # ========================================
    # 3. QUERY BASE CON FILTROS
    # ========================================
    query = Fichaje.query.filter(
        Fichaje.usuario_id == current_user.id,
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion',
        Fichaje.fecha >= fecha_inicio,
        Fichaje.fecha <= fecha_fin
    ).order_by(Fichaje.fecha.desc(), Fichaje.hora_entrada.desc())

    # ========================================
    # 4. APLICAR PAGINACIÓN
    # ========================================
    pagination = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False  # No lanzar error si page > max_pages
    )
    
    # ========================================
    # 5. CALCULAR ESTADÍSTICAS DEL MES
    # ========================================
    # Query separada para totales (sin paginación)
    total_horas_mes = db.session.query(
        func.sum(
            (
                (extract('hour', Fichaje.hora_salida) * 3600 + 
                 extract('minute', Fichaje.hora_salida) * 60) -
                (extract('hour', Fichaje.hora_entrada) * 3600 + 
                 extract('minute', Fichaje.hora_entrada) * 60)
            ) / 3600.0 - (cast(Fichaje.pausa, Float) / 60.0)
        )
    ).filter(
        Fichaje.usuario_id == current_user.id,
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion',
        Fichaje.fecha >= fecha_inicio,
        Fichaje.fecha <= fecha_fin,
        Fichaje.hora_salida.isnot(None)
    ).scalar() or 0
    
    total_fichajes_mes = query.count()
    
    # ========================================
    # 6. RENDERIZAR TEMPLATE
    # ========================================
    return render_template('fichajes.html', 
                         fichajes=pagination.items,
                         pagination=pagination,
                         mes_actual=mes, 
                         anio_actual=anio,
                         total_horas_mes=total_horas_mes,
                         total_fichajes_mes=total_fichajes_mes)

@fichajes_bp.route('/fichajes/crear', methods=['GET', 'POST'])
@login_required
def crear():
    # CAMBIO: Redirección estricta para TODOS (incluido admin) si el manual está off.
    # El admin debe usar el reloj si quiere fichar (o reactivar el modo manual por config).
    if not current_app.config.get('ENABLE_MANUAL_ENTRY'):
        return redirect(url_for('fichajes.reloj'))
    
    if request.method == 'POST':
        fecha = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date()
        hora_entrada = datetime.strptime(request.form.get('hora_entrada'), '%H:%M').time()
        hora_salida = datetime.strptime(request.form.get('hora_salida'), '%H:%M').time()
        
        try:
            pausa = int(request.form.get('pausa') or 0)
        except ValueError:
            pausa = 0

        # --- VALIDACIONES DE BLOQUEO ---
        
        # 0. Validación básica de horas
        if hora_salida <= hora_entrada:
             flash('La hora de salida debe ser posterior a la entrada.', 'danger')
             return redirect(url_for('fichajes.crear'))

        # 1. CHECK DE SOLAPAMIENTO DE FICHAJES
        hay_solape, msg_error = verificar_solapamiento_fichaje(current_user.id, fecha, hora_entrada, hora_salida)
        
        if hay_solape:
            # Aquí usamos 'danger' para indicar error y NO guardamos
            flash(f'Error: No se puede crear el fichaje. {msg_error}', 'danger')
            #return redirect(url_for('fichajes.listar')) 
            return redirect(url_for('fichajes.crear'))
            
        # --- LÓGICA DE ADVERTENCIAS ---
        
        # 1. Advertencia de Fin de Semana o Festivo
        if es_festivo(fecha):
            dia_semana = fecha.strftime('%A') # Opcional: traducir días si quieres
            flash(f'Atención: Has registrado un fichaje fuera de horario laboral.', 'warning')
        # 2. Advertencia de Vacaciones/Bajas (Solapamiento)
        # Usamos verificar_solapamiento con la misma fecha de inicio y fin
        en_ausencia, motivo_ausencia = verificar_solapamiento(current_user.id, fecha, fecha)
        if en_ausencia:
            # El mensaje de motivo_ausencia suele ser "Ya tienes vacaciones..."
            flash(f'Atención: Tienes una ausencia aprobada o solicitada para este día: {motivo_ausencia}', 'warning')

        # ------------------------------------
        
        fichaje = Fichaje(
            usuario_id=current_user.id,
            editor_id=current_user.id, 
            grupo_id=str(uuid.uuid4()),
            version=1,
            es_actual=True,
            tipo_accion='creacion',
            fecha=fecha,
            hora_entrada=hora_entrada,
            hora_salida=hora_salida,
            pausa=pausa
        )
        
        db.session.add(fichaje)
        db.session.commit()
        flash('Fichaje registrado correctamente', 'success')
        return redirect(url_for('fichajes.listar'))
    
    # --- LÓGICA DE SUGERENCIAS (TOP 3 FRECUENTES) ---
    sugerencias = db.session.query(
        Fichaje.hora_entrada,
        Fichaje.hora_salida,
        Fichaje.pausa,
        func.count(Fichaje.id).label('total')
    ).filter(
        Fichaje.usuario_id == current_user.id,
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion'
    ).group_by(
        Fichaje.hora_entrada,
        Fichaje.hora_salida,
        Fichaje.pausa
    ).order_by(
        desc('total')
    ).limit(3).all()
    
    return render_template('crear_fichaje.html', now=datetime.now, sugerencias=sugerencias)

@fichajes_bp.route('/fichajes/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    fichaje_actual = Fichaje.query.get_or_404(id)
    
    # Seguridad: Solo dueño o admin
    if fichaje_actual.usuario_id != current_user.id and current_user.rol != 'admin':
        flash('No tienes permisos para editar este fichaje', 'danger')
        return redirect(url_for('fichajes.listar'))
    
    if not fichaje_actual.es_actual:
        flash('Solo se puede editar la versión vigente de un fichaje.', 'warning')
        return redirect(url_for('fichajes.listar'))
    
    # CAPTURAR REDIRECT (Para volver al Admin Panel si venimos de allí)
    next_page = request.args.get('next') or request.form.get('next')

    if request.method == 'POST':
        motivo = request.form.get('motivo')
        if not motivo:
            flash('El motivo es obligatorio para rectificar un fichaje.', 'danger')
            # Mantenemos el next en caso de error
            return redirect(url_for('fichajes.editar', id=id, next=next_page))

        try:
            pausa = int(request.form.get('pausa') or 0)
        except ValueError:
            pausa = 0

        # 1. INMUTABILIDAD: Marcar actual como obsoleto
        fichaje_actual.es_actual = False
        
        # 2. CREAR NUEVA VERSIÓN
        nuevo_fichaje = Fichaje(
            usuario_id=fichaje_actual.usuario_id,
            editor_id=current_user.id, # Quién hace la corrección
            grupo_id=fichaje_actual.grupo_id,
            version=fichaje_actual.version + 1,
            es_actual=True,
            tipo_accion='modificacion',
            motivo_rectificacion=motivo,
            fecha=datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date(),
            hora_entrada=datetime.strptime(request.form.get('hora_entrada'), '%H:%M').time(),
            hora_salida=datetime.strptime(request.form.get('hora_salida'), '%H:%M').time(),
            pausa=pausa
        )
        
        db.session.add(nuevo_fichaje)
        db.session.commit()
        flash('Fichaje rectificado correctamente (histórico guardado).', 'success')
        
        # REDIRECCIÓN INTELIGENTE
        if next_page:
            return redirect(next_page)
        return redirect(url_for('fichajes.listar'))
    
    return render_template('editar_fichaje.html', fichaje=fichaje_actual, now=datetime.now, next_url=next_page)

@fichajes_bp.route('/fichajes/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar(id):
    fichaje_actual = Fichaje.query.get_or_404(id)
    
    if fichaje_actual.usuario_id != current_user.id and current_user.rol != 'admin':
        flash('No tienes permisos para eliminar este fichaje', 'danger')
        return redirect(url_for('fichajes.listar'))
    
    if not fichaje_actual.es_actual:
        flash('No se puede eliminar una versión histórica.', 'danger')
        return redirect(url_for('fichajes.listar'))
    
    # CAPTURAR REDIRECT
    next_page = request.args.get('next')
    
    # 1. SOFT DELETE: Marcar actual como obsoleto
    fichaje_actual.es_actual = False
    
    # 2. CREAR REGISTRO DE ELIMINACIÓN (Tombstone)
    fichaje_borrado = Fichaje(
        usuario_id=fichaje_actual.usuario_id,
        editor_id=current_user.id, # Quién elimina
        grupo_id=fichaje_actual.grupo_id,
        version=fichaje_actual.version + 1,
        es_actual=True,
        tipo_accion='eliminacion',
        motivo_rectificacion="Eliminado por el usuario/admin",
        fecha=fichaje_actual.fecha,
        # Mantenemos datos originales para saber qué se borró
        hora_entrada=fichaje_actual.hora_entrada,
        hora_salida=fichaje_actual.hora_salida,
        pausa=fichaje_actual.pausa
    )
    
    db.session.add(fichaje_borrado)
    db.session.commit()
    flash('Fichaje eliminado correctamente.', 'success')
    
    # REDIRECCIÓN INTELIGENTE
    if next_page:
        return redirect(next_page)
    return redirect(url_for('fichajes.listar'))

@fichajes_bp.route('/fichajes/verificar-fecha', methods=['POST'])
@login_required
def verificar_fecha_ajax():
    data = request.get_json()
    fecha_str = data.get('fecha')
    
    if not fecha_str:
        return jsonify({'status': 'ok'})
        
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Fecha inválida'})

    warnings = []

    # 1. Verificar Fin de Semana (Sábado=5, Domingo=6)
    if fecha.weekday() >= 5:
        dia = "Sábado" if fecha.weekday() == 5 else "Domingo"
        warnings.append(f"Aviso: El {fecha.strftime('%d/%m/%Y')} es {dia} (Fin de semana).")

    # 2. Verificar Festivo (Si no es finde, miramos si es festivo en BBDD)
    # Nota: es_festivo() ya comprueba finde, pero aquí separamos para dar mensajes distintos
    elif es_festivo(fecha): 
        # Si entra aquí es que es festivo entre semana (lunes-viernes)
        # Podríamos buscar la descripción del festivo si quisiéramos ser más precisos
        warnings.append(f"Aviso: El {fecha.strftime('%d/%m/%Y')} es un día Festivo.")

    # 3. y 4. Verificar Vacaciones y Bajas Activas
    # verificar_solapamiento comprueba ambas tablas (SolicitudVacaciones y SolicitudBaja)
    en_ausencia, motivo = verificar_solapamiento(current_user.id, fecha, fecha)
    
    if en_ausencia:
        # 'motivo' contendrá "Ya tienes vacaciones..." o "Ya tienes una baja..."
        warnings.append(f"Bloqueo: {motivo}")

    # Respuesta
    if warnings:
        return jsonify({'status': 'warning', 'messages': warnings})
        
    return jsonify({'status': 'ok'})

# --- NUEVAS RUTAS PARA START/STOP ---

@fichajes_bp.route('/fichajes/estado', methods=['GET'])
@login_required
def estado_fichaje():
    """
    Devuelve el estado actual del fichaje para el usuario.
    Se usa para pintar el botón (Verde/Rojo) al cargar la página.
    """
    # Buscamos si hay algún fichaje "abierto" (sin hora de salida)
    # Nota: No filtramos por fecha. Si se dejó abierto ayer, hay que cerrarlo hoy.
    fichaje_activo = Fichaje.query.filter(
        Fichaje.usuario_id == current_user.id,
        Fichaje.es_actual == True,
        Fichaje.hora_salida.is_(None), # Fichaje abierto
        Fichaje.tipo_accion != 'eliminacion'
    ).first()

    if fichaje_activo:
        # Calcular duración en tiempo real
        ahora = get_user_now()
        inicio = datetime.combine(fichaje_activo.fecha, fichaje_activo.hora_entrada)
        
        # Ajuste por si el fichaje es de ayer (evitar duraciones negativas raras)
        duracion_segundos = (ahora - inicio).total_seconds()
        
        return jsonify({
            'activo': True,
            'inicio': inicio.isoformat(),
            'duracion_segundos': int(duracion_segundos),
            'fecha': fichaje_activo.fecha.isoformat()
        })
    
    return jsonify({
        'activo': False,
        'inicio': None,
        'duracion_segundos': 0
    })

@fichajes_bp.route('/fichajes/toggle', methods=['POST'])
@login_required
def toggle_fichaje():
    """
    Acción del botón: Inicia o Detiene el fichaje.
    """
    ahora_local = get_user_now()
    fecha_actual = ahora_local.date()
    hora_actual = ahora_local.time()

    # 1. Buscar si ya hay uno abierto
    fichaje_activo = Fichaje.query.filter(
        Fichaje.usuario_id == current_user.id,
        Fichaje.es_actual == True,
        Fichaje.hora_salida.is_(None),
        Fichaje.tipo_accion != 'eliminacion'
    ).first()

    if fichaje_activo:
        # --- CASO: DETENER (STOP) ---
        # Cerramos el fichaje existente
        fichaje_activo.hora_salida = hora_actual
        
        # Opcional: Calcular pausa automática si quisiéramos, pero
        # en este modelo Start/Stop la pausa es simplemente el tiempo entre fichajes.
        fichaje_activo.pausa = 0 
        
        db.session.commit()
        
        return jsonify({
            'status': 'stopped',
            'mensaje': f'Jornada pausada/finalizada a las {hora_actual.strftime("%H:%M")}',
            'total_horas': decimal_to_human(fichaje_activo.horas_trabajadas())
        })

    else:
        # --- CASO: INICIAR (START) ---
        
        # Validar si ya existe un fichaje cerrado HOY que solape (improbable con Start/Stop, pero posible por seguridad)
        # En modo Start/Stop puro, permitimos múltiples fragmentos.
        
        nuevo_fichaje = Fichaje(
            usuario_id=current_user.id,
            editor_id=current_user.id,
            grupo_id=str(uuid.uuid4()),
            version=1,
            es_actual=True,
            tipo_accion='creacion',
            fecha=fecha_actual,
            hora_entrada=hora_actual,
            hora_salida=None, # IMPORTANTE: Se queda abierto
            pausa=0
        )
        
        db.session.add(nuevo_fichaje)
        db.session.commit()
        
        return jsonify({
            'status': 'started',
            'mensaje': f'Fichaje iniciado a las {hora_actual.strftime("%H:%M")}',
            'inicio': ahora_local.isoformat()
        })
    
@fichajes_bp.route('/fichajes/reloj')
@login_required
def reloj():
    """Nueva pantalla de fichaje Start/Stop"""
    return render_template('reloj.html')

@fichajes_bp.route('/fichajes/api/timeline', methods=['GET'])
@login_required
def api_timeline():
    """
    Devuelve los tramos horarios de un día específico para el timeline visual.
    """
    fecha_str = request.args.get('fecha')
    if not fecha_str:
        fecha = date.today()
    else:
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify([]) # Fecha inválida, devolvemos lista vacía

    # 1. Obtener fichajes del día (excluyendo eliminados)
    fichajes = Fichaje.query.filter(
        Fichaje.usuario_id == current_user.id,
        Fichaje.es_actual == True,
        Fichaje.tipo_accion != 'eliminacion',
        Fichaje.fecha == fecha
    ).order_by(Fichaje.hora_entrada).all()

    bloques = []
    
    # 2. Convertir a formato porcentual para la barra (0-100%)
    # Un día tiene 1440 minutos (24 * 60)
    TOTAL_MINUTOS = 1440 

    ahora = get_user_now() # Usamos tu helper de zona horaria
    hora_actual_minutos = ahora.hour * 60 + ahora.minute

    for f in fichajes:
        entrada_min = f.hora_entrada.hour * 60 + f.hora_entrada.minute
        
        if f.hora_salida:
            salida_min = f.hora_salida.hour * 60 + f.hora_salida.minute
            tipo = 'cerrado'
        else:
            # Si es hoy, llega hasta ahora. Si es pasado, hasta 23:59
            if f.fecha == ahora.date():
                salida_min = hora_actual_minutos
            else:
                salida_min = 1439 # Final del día
            tipo = 'activo'

        # Corregir si cruza medianoche (simple visualización corta en 23:59)
        if salida_min < entrada_min: 
            salida_min = 1439 

        duracion = salida_min - entrada_min
        
        # Calcular porcentajes para CSS
        left_pct = (entrada_min / TOTAL_MINUTOS) * 100
        width_pct = (duracion / TOTAL_MINUTOS) * 100

        bloques.append({
            'left': f"{left_pct:.2f}%",
            'width': f"{width_pct:.2f}%",
            'tipo': tipo,
            'hora_entrada': f.hora_entrada.strftime('%H:%M'),
            'hora_salida': f.hora_salida.strftime('%H:%M') if f.hora_salida else "..."
        })

    return jsonify({
        'bloques': bloques,
        'hora_actual_pct': (hora_actual_minutos / TOTAL_MINUTOS) * 100 if fecha == ahora.date() else None
    })