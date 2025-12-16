from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from calendar import monthrange
from sqlalchemy import func, desc
from src.utils import es_festivo, verificar_solapamiento, verificar_solapamiento_fichaje
import uuid

from src import db
from src.models import Fichaje
from src.utils import es_festivo, verificar_solapamiento
from . import fichajes_bp

@fichajes_bp.route('/fichajes')
@login_required
def listar():
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

    # Solo mostramos fichajes actuales y que NO sean de tipo 'eliminacion'
    fichajes = Fichaje.query.filter_by(usuario_id=current_user.id, es_actual=True)\
        .filter(Fichaje.tipo_accion != 'eliminacion')\
        .filter(Fichaje.fecha >= fecha_inicio)\
        .filter(Fichaje.fecha <= fecha_fin)\
        .order_by(Fichaje.fecha.desc()).all()
        
    return render_template('fichajes.html', fichajes=fichajes, mes_actual=mes, anio_actual=anio)

@fichajes_bp.route('/fichajes/crear', methods=['GET', 'POST'])
@login_required
def crear():
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