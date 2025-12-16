from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, date
import uuid

from src import db
from src.models import SolicitudVacaciones, SolicitudBaja, TipoAusencia, Usuario, SaldoVacaciones
from src.utils import calcular_dias_habiles, verificar_solapamiento, simular_modificacion_vacaciones
from . import ausencias_bp

# -------------------------------------------------------------------------
# GESTIÓN DE VACACIONES
# -------------------------------------------------------------------------

@ausencias_bp.route('/vacaciones')
@login_required
def listar_vacaciones():
    """Lista el historial de solicitudes de vacaciones del usuario actual."""
    # 1. Obtener todas las versiones 'actuales'
    raw_solicitudes = SolicitudVacaciones.query.filter_by(usuario_id=current_user.id, es_actual=True)\
        .order_by(SolicitudVacaciones.fecha_solicitud.desc()).all()
    
    # 2. Separar padres de hijos y FILTRAR CANCELADAS
    solicitudes_principales = []
    cambios_pendientes = {} 

    for sol in raw_solicitudes:
        # A. Si es una petición de cambio PENDIENTE, la guardamos para vincularla después
        if sol.estado == 'pendiente' and sol.tipo_accion in ['cancelacion', 'modificacion']:
            cambios_pendientes[sol.grupo_id] = sol
            continue # Pasamos al siguiente ciclo
        
        # Ocultar si está rechazada (esto incluye las canceladas manualmente por el usuario cuando eran pendientes)
        if sol.estado == 'rechazada':
            continue
            
        # Ocultar si es una "Solicitud de Cancelación" que ya fue Aprobada
        # (Esto significa que el proceso de cancelación finalizó con éxito, por lo que la vacación ya no existe)
        if sol.tipo_accion == 'cancelacion' and sol.estado == 'aprobada':
            continue
        # -----------------------------------------------------

        # Si pasa los filtros, es una solicitud válida para mostrar (Pendiente, Aprobada, etc.)
        solicitudes_principales.append(sol)

    # 3. Vincular el cambio pendiente a su principal
    for sol in solicitudes_principales:
        sol.cambio_pendiente = cambios_pendientes.get(sol.grupo_id)

    return render_template('vacaciones.html', solicitudes=solicitudes_principales, today=date.today())


@ausencias_bp.route('/vacaciones/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_vacaciones():
    """Formulario y proceso de creación de nueva solicitud de vacaciones."""
    
    # Si es admin, cargar usuarios para el selector
    usuarios = []
    if current_user.rol == 'admin':
        usuarios = Usuario.query.order_by(Usuario.nombre).all()

    if request.method == 'POST':
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        motivo = request.form.get('motivo')
        usuario_id_seleccionado = request.form.get('usuario_id')

        # DETERMINAR EL USUARIO OBJETIVO (Impersonation)
        target_user = current_user
        if current_user.rol == 'admin' and usuario_id_seleccionado:
            target_user = Usuario.query.get(int(usuario_id_seleccionado))
            if not target_user:
                flash('Usuario seleccionado no válido.', 'danger')
                return redirect(url_for('ausencias.solicitar_vacaciones'))

        # Conversión de fechas
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Formato de fechas inválido.', 'danger')
            return redirect(url_for('ausencias.solicitar_vacaciones'))
        
        # 1. Validación Básica de Fechas
        if fecha_fin < fecha_inicio:
            flash('La fecha de fin no puede ser anterior a la de inicio.', 'danger')
            return redirect(url_for('ausencias.solicitar_vacaciones'))
        
        # 2. Validación de Solapamiento (Overlap)
        # Comprueba si TARGET_USER ya tiene otra solicitud
        hay_solapamiento, mensaje_error = verificar_solapamiento(
            target_user.id, fecha_inicio, fecha_fin, tipo='vacaciones'
        )
        if hay_solapamiento:
            flash(f'Error ({target_user.nombre}): {mensaje_error}', 'danger')
            return redirect(url_for('ausencias.solicitar_vacaciones'))

        # 3. Cálculo de Días (Solo días Hábiles para vacaciones)
        dias_calculados = calcular_dias_habiles(fecha_inicio, fecha_fin)
        
        if dias_calculados <= 0:
            flash('El rango seleccionado no contiene días laborables (fines de semana o festivos).', 'warning')
            return redirect(url_for('ausencias.solicitar_vacaciones'))

        # 4. LÓGICA DE SALDO Y ADELANTO
        saldo_actual = target_user.dias_vacaciones_disponibles()
        
        # Definimos el límite de endeudamiento (ej. puede adelantar hasta el 100% de sus vacaciones anuales)
        max_deuda_permitida = target_user.dias_vacaciones 
        saldo_proyectado = saldo_actual - dias_calculados

        # Si el saldo proyectado es menor que el límite negativo permitido, bloqueamos
        if saldo_proyectado < -max_deuda_permitida:
            flash(f'Límite de adelanto excedido. No puedes tener una deuda mayor a {max_deuda_permitida} días.', 'danger')
            return redirect(url_for('ausencias.solicitar_vacaciones'))
        
        # 5. Configurar Estado
        es_admin_gestion = (current_user.rol == 'admin' and target_user.id != current_user.id)
        estado_inicial = 'aprobada' if es_admin_gestion else 'pendiente'
        aprobador_inicial = current_user.id if es_admin_gestion else None
        fecha_respuesta = datetime.utcnow() if es_admin_gestion else None

        # 6. Creación de la Solicitud (Igual que antes)
        solicitud = SolicitudVacaciones(
            usuario_id=target_user.id,
            # ... resto de campos ...
            #
            grupo_id=str(uuid.uuid4()),
            version=1,
            es_actual=True,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            dias_solicitados=dias_calculados,
            motivo=motivo,
            estado=estado_inicial,
            aprobador_id=aprobador_inicial,
            fecha_respuesta=fecha_respuesta,
            fecha_solicitud=datetime.utcnow()
        )
        
        db.session.add(solicitud)
        db.session.commit()
        
        # Mensajes Feedback
        if saldo_proyectado < 0:
            msg_exito = f'Solicitud enviada con ADELANTO de vacaciones. Tu saldo quedará en {saldo_proyectado} días.'
            flash(msg_exito, 'warning') # Warning para llamar la atención
        else:
            msg_exito = 'Solicitud de vacaciones enviada correctamente.'
            flash(msg_exito, 'success')
        
        return redirect(url_for('ausencias.listar_vacaciones'))
        
    return render_template('solicitar_vacaciones.html', usuarios=usuarios)


@ausencias_bp.route('/vacaciones/cancelar/<int:id>', methods=['POST'])
@login_required
def cancelar_vacaciones(id):
    """Permite al usuario cancelar su propia solicitud si aún está pendiente."""
    solicitud = SolicitudVacaciones.query.get_or_404(id)
    
    # Seguridad: Verificar propiedad O Admin
    es_admin = current_user.rol == 'admin'
    if solicitud.usuario_id != current_user.id and not es_admin:
        flash('No tienes permiso para modificar esta solicitud.', 'danger')
        return redirect(url_for('ausencias.listar_vacaciones'))

    # Validación: No tocar el pasado
    if solicitud.fecha_fin < date.today():
        flash('No se pueden cancelar vacaciones que ya han sido disfrutadas.', 'danger')
        return redirect(url_for('ausencias.listar_vacaciones'))
        
    # Lógica de Negocio: 
    # 1. Si está APROBADA: SIEMPRE generar solicitud de cancelación (para gestionar devolución de saldo).
    if solicitud.estado == 'aprobada':
        # Crear solicitud de cancelación (versión nueva)
        nueva_solicitud = SolicitudVacaciones(
            usuario_id=current_user.id,
            grupo_id=solicitud.grupo_id,
            version=solicitud.version + 1,
            es_actual=True, # La petición de cancelación pasa a ser la actual visible
            tipo_accion='cancelacion',
            fecha_inicio=solicitud.fecha_inicio,
            fecha_fin=solicitud.fecha_fin,
            dias_solicitados=solicitud.dias_solicitados,
            motivo=f"Solicitud de cancelación: {solicitud.motivo}",
            estado='pendiente',
            fecha_solicitud=datetime.utcnow()
        )
        db.session.add(nueva_solicitud)
        db.session.commit()
        
        # Enviar Email al Aprobador
        aprobador = None
        if current_user.aprobadores:
            aprobador = current_user.aprobadores[0].aprobador
        else:
            aprobador = Usuario.query.filter_by(rol='admin').first()
            
        if aprobador:
            from src.email_service import enviar_email_solicitud
            enviar_email_solicitud(aprobador, current_user, nueva_solicitud)

        flash('Solicitud de cancelación enviada para aprobación.', 'info')
        return redirect(url_for('ausencias.listar_vacaciones'))

    # 2. Si NO está pendiente (ej. rechazada o ya cancelada), error.
    if solicitud.estado != 'pendiente':
         flash('No puedes cancelar esta solicitud en su estado actual.', 'warning')
         return redirect(url_for('ausencias.listar_vacaciones'))
    
    # 3. Si está PENDIENTE: Cancelación Directa (Retirada)
    solicitud.estado = 'rechazada'
    solicitud.comentarios = f'Cancelada/Retirada por {current_user.nombre}'
    solicitud.fecha_respuesta = datetime.utcnow()
    # Si es pendiente, NO ha consumido saldo, así que no hay reembolso que procesar.
    
    db.session.commit()
    flash('Solicitud cancelada correctamente.', 'info')
    return redirect(url_for('ausencias.listar_vacaciones'))


@ausencias_bp.route('/vacaciones/modificar/<int:id>', methods=['GET', 'POST'])
@login_required
def modificar_vacaciones(id):
    """Solicita una modificación de fechas para una solicitud existente (crea v2)."""
    original = SolicitudVacaciones.query.get_or_404(id)
    
    if original.usuario_id != current_user.id:
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('ausencias.listar_vacaciones'))

    # Validación: No tocar el pasado
    if original.fecha_fin < date.today():
        flash('No se pueden modificar vacaciones pasadas.', 'danger')
        return redirect(url_for('ausencias.listar_vacaciones'))
        
    if request.method == 'POST':
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        motivo = request.form.get('motivo')
        
        try:
            nueva_fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            nueva_fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Fechas inválidas.', 'danger')
            return redirect(url_for('ausencias.modificar_vacaciones', id=id))
            
        # Validar fechas básicas
        if nueva_fecha_fin < nueva_fecha_inicio:
            flash('La fecha fin no puede ser anterior a la de inicio.', 'danger')
            return redirect(url_for('ausencias.modificar_vacaciones', id=id))

        # SIMULACIÓN (Tarea 4)
        resultado = simular_modificacion_vacaciones(
            current_user.id, 
            original.id, 
            nueva_fecha_inicio, 
            nueva_fecha_fin
        )
        
        if not resultado['valido']:
            flash(f"Error al modificar: {resultado['motivo']}", 'danger')
            return redirect(url_for('ausencias.modificar_vacaciones', id=id))
            
        if resultado.get('es_adelanto'):
            flash(f"Atención: Estás solicitando vacaciones por adelantado ({resultado['saldo_proyectado']} días).", 'warning')

        # CREAR NUEVA VERSIÓN (Tarea 5)
        nueva_version = SolicitudVacaciones(
            usuario_id=current_user.id,
            grupo_id=original.grupo_id,
            version=original.version + 1,
            es_actual=True,
            tipo_accion='modificacion',
            fecha_inicio=nueva_fecha_inicio,
            fecha_fin=nueva_fecha_fin,
            dias_solicitados=resultado['dias_diff'] + original.dias_solicitados, 
            motivo=motivo,
            estado='pendiente',
            editor_id=current_user.id,
            fecha_solicitud=datetime.utcnow()
        )
        
        # Recalculamos dias_solicitados del total nuevo de forma segura
        nueva_version.dias_solicitados = resultado['dias_diff'] + original.dias_solicitados
        # Si la simulación devuelve dias_diff, entonces Total Nuevo = Original + Diff

        db.session.add(nueva_version)
        db.session.commit()
        
        # Enviar Email al Aprobador (si tiene)
        # Buscamos aprobador asignado. Si no hay, a los admins.
        # (Lógica simplificada: Si no hay aprobador directo, usar admin genérico o primer admin)
        aprobador = None
        if current_user.aprobadores:
            aprobador = current_user.aprobadores[0].aprobador
        else:
            aprobador = Usuario.query.filter_by(rol='admin').first()
            
        if aprobador:
            from src.email_service import enviar_email_solicitud
            enviar_email_solicitud(aprobador, current_user, nueva_version)
        
        flash('Solicitud de modificación enviada correctamente. Tu responsable ha sido notificado.', 'success')
        return redirect(url_for('ausencias.listar_vacaciones'))

    return render_template('modificar_vacaciones.html', solicitud=original)


# -------------------------------------------------------------------------
# GESTIÓN DE BAJAS Y OTRAS AUSENCIAS
# -------------------------------------------------------------------------

@ausencias_bp.route('/bajas')
@login_required
def listar_bajas():
    """Lista el historial de bajas médicas u otros permisos del usuario."""
    solicitudes = SolicitudBaja.query.filter_by(usuario_id=current_user.id, es_actual=True)\
        .order_by(SolicitudBaja.fecha_solicitud.desc()).all()
    return render_template('bajas.html', solicitudes=solicitudes)


@ausencias_bp.route('/bajas/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_baja():
    """Formulario y proceso de creación de nueva baja/permiso."""
    tipos = TipoAusencia.query.filter_by(activo=True).all()
    
    # Si es admin, cargar usuarios
    usuarios = []
    if current_user.rol == 'admin':
        usuarios = Usuario.query.order_by(Usuario.nombre).all()
    
    if request.method == 'POST':
        tipo_id = request.form.get('tipo_ausencia')
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        motivo = request.form.get('motivo')
        usuario_id_seleccionado = request.form.get('usuario_id')

        # DETERMINAR EL USUARIO OBJETIVO
        target_user = current_user
        if current_user.rol == 'admin' and usuario_id_seleccionado:
            target_user = Usuario.query.get(int(usuario_id_seleccionado))
            if not target_user:
                flash('Usuario no válido.', 'danger')
                return redirect(url_for('ausencias.solicitar_baja'))
        
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Formato de fechas inválido.', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))
        
        if fecha_fin < fecha_inicio:
            flash('La fecha de fin no puede ser anterior a la de inicio.', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))

        # 1. Validación de Solapamiento
        hay_solapamiento, mensaje_error = verificar_solapamiento(
            target_user.id, fecha_inicio, fecha_fin, tipo='baja'
        )
        if hay_solapamiento:
            flash(f'Error ({target_user.nombre}): {mensaje_error}', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))
            
        # 2. Cálculo de Días (Depende del Tipo de Ausencia)
        tipo_obj = TipoAusencia.query.get(tipo_id)
        if not tipo_obj:
            flash('Tipo de ausencia no válido.', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))

        if tipo_obj.tipo_dias == 'naturales':
            dias = (fecha_fin - fecha_inicio).days + 1
        else:
            dias = calcular_dias_habiles(fecha_inicio, fecha_fin)

        if dias > tipo_obj.max_dias:
            flash(f'Error: La duración ({dias} días) supera el máximo permitido para "{tipo_obj.nombre}" ({tipo_obj.max_dias} días).', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))

        # 3. Configurar Estado (Admin -> Aprobada)
        es_admin_gestion = (current_user.rol == 'admin' and target_user.id != current_user.id)
        estado_inicial = 'aprobada' if es_admin_gestion else 'pendiente'
        aprobador_inicial = current_user.id if es_admin_gestion else None
        fecha_respuesta = datetime.utcnow() if es_admin_gestion else None

        # 4. Creación de la Solicitud
        solicitud = SolicitudBaja(
            usuario_id=target_user.id,
            grupo_id=str(uuid.uuid4()),
            version=1,
            es_actual=True,
            tipo_ausencia_id=tipo_id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            dias_solicitados=dias,
            motivo=motivo,
            estado=estado_inicial,
            aprobador_id=aprobador_inicial,
            fecha_respuesta=fecha_respuesta,
            fecha_solicitud=datetime.utcnow()
        )
        
        db.session.add(solicitud)
        db.session.commit()
        
        msg_exito = f'Baja registrada y aprobada para {target_user.nombre}.' if es_admin_gestion else 'Baja/Permiso registrado correctamente.'
        flash(msg_exito, 'success')
        return redirect(url_for('ausencias.listar_bajas'))
        
    return render_template('solicitar_baja.html', tipos=tipos, usuarios=usuarios)


# En src/routes/ausencias.py

@ausencias_bp.route('/bajas/cancelar/<int:id>', methods=['POST'])
@login_required
def cancelar_baja(id):
    """Permite cancelar una solicitud de baja si está pendiente."""
    solicitud = SolicitudBaja.query.get_or_404(id)
    
    # 1. Seguridad: Verificar propiedad o Admin
    if solicitud.usuario_id != current_user.id and current_user.rol != 'admin':
        flash('No tienes permiso para cancelar esta solicitud.', 'danger')
        return redirect(url_for('ausencias.listar_bajas'))
    
    # 2. Validación: Solo pendientes
    if solicitud.estado != 'pendiente':
        flash('No se puede cancelar una baja que ya ha sido procesada.', 'warning')
        return redirect(url_for('ausencias.listar_bajas'))
        
    # 3. Acción: Cancelar (Marcar como rechazada/retirada)
    solicitud.estado = 'rechazada'
    solicitud.comentarios = f'Cancelada/Retirada por {current_user.nombre}'
    solicitud.fecha_respuesta = datetime.utcnow()
    
    db.session.commit()
    
    flash('Solicitud de baja cancelada correctamente.', 'info')
    return redirect(url_for('ausencias.listar_bajas'))

# -------------------------------------------------------------------------
# ZONA DE APROBADORES (MANAGERS/ADMINS)
# -------------------------------------------------------------------------

@ausencias_bp.route('/aprobaciones')
@login_required
def aprobar_solicitudes():
    """Panel para ver solicitudes pendientes de los empleados a cargo."""
    if current_user.rol not in ['aprobador', 'admin']:
        flash('Acceso denegado. No tienes rol de aprobador.', 'danger')
        return redirect(url_for('main.index'))
    
    # Obtener lista de IDs de usuarios asignados a este aprobador
    ids_a_cargo = [r.usuario_id for r in current_user.usuarios_a_cargo]
    
    # 1. Buscar solicitudes de vacaciones pendientes
    vacaciones = SolicitudVacaciones.query.filter(
        SolicitudVacaciones.usuario_id.in_(ids_a_cargo),
        SolicitudVacaciones.estado == 'pendiente',
        SolicitudVacaciones.es_actual == True
    ).all()
    
    # 2. Buscar bajas pendientes
    bajas = SolicitudBaja.query.filter(
        SolicitudBaja.usuario_id.in_(ids_a_cargo),
        SolicitudBaja.estado == 'pendiente',
        SolicitudBaja.es_actual == True
    ).all()
    
    return render_template('aprobar_solicitudes.html', 
                         solicitudes_vac=vacaciones, 
                         solicitudes_bajas=bajas)


@ausencias_bp.route('/aprobaciones/vacaciones/<int:id>/<accion>', methods=['POST'])
@login_required
def responder_solicitud(id, accion):
    """Acción de aprobar o rechazar vacaciones."""
    if current_user.rol not in ['aprobador', 'admin']:
        flash('No tienes permisos.', 'danger')
        return redirect(url_for('main.index'))
        
    solicitud = SolicitudVacaciones.query.get_or_404(id)
    
    # Seguridad: Validar que el empleado realmente está a su cargo (o soy admin)
    es_mi_empleado = any(r.usuario_id == solicitud.usuario_id for r in current_user.usuarios_a_cargo)
    if not es_mi_empleado and current_user.rol != 'admin':
         flash('No tienes permiso para gestionar solicitudes de este usuario.', 'danger')
         return redirect(url_for('ausencias.aprobar_solicitudes'))

    # Procesar Acción
    if accion == 'aprobar':
        # --- CASO A: CREACIÓN (Primera vez) ---
        if solicitud.tipo_accion == 'creacion':
            # 1. Actualizar Saldo
            anio = solicitud.fecha_inicio.year
            saldo = SaldoVacaciones.query.filter_by(usuario_id=solicitud.usuario_id, anio=anio).first()
            if saldo:
                saldo.dias_disfrutados += solicitud.dias_solicitados
                # Seguridad básica: permitir negativo con warning en log, o bloquear. 
                # El usuario ya fue avisado al pedir. Aquí ejecutamos.
            
            solicitud.estado = 'aprobada'
            flash(f'Solicitud de vacaciones aprobada. Días descontados.', 'success')

        # --- CASO B: MODIFICACIÓN O CANCELACIÓN (Versionado) ---
        elif solicitud.tipo_accion in ['modificacion', 'cancelacion']:
            # 1. Buscar V1 (La versión actual anterior)
            v1 = SolicitudVacaciones.query.filter(
                SolicitudVacaciones.grupo_id == solicitud.grupo_id,
                SolicitudVacaciones.es_actual == True,
                SolicitudVacaciones.id != solicitud.id
            ).first()

            # 2. Consolidar V1 (Obsoleta)
            dias_reintegro = 0
            if v1:
                v1.es_actual = False
                dias_reintegro = v1.dias_solicitados
            
            # 3. Activar V2 (Esta solicitud)
            solicitud.estado = 'aprobada'
            solicitud.es_actual = True
            
            # 4. Ajuste de Saldo
            coste_nuevo = 0
            if solicitud.tipo_accion == 'modificacion':
                coste_nuevo = solicitud.dias_solicitados
            elif solicitud.tipo_accion == 'cancelacion':
                coste_nuevo = 0 # Cancelar implica que no se consumen días
            
            anio = solicitud.fecha_inicio.year
            saldo = SaldoVacaciones.query.filter_by(usuario_id=solicitud.usuario_id, anio=anio).first()
            
            if saldo:
                saldo.dias_disfrutados = saldo.dias_disfrutados - dias_reintegro + coste_nuevo
                
            flash(f"Solicitud aprobada. Saldo ajustado (Devueltos: {dias_reintegro}, Nuevos: {coste_nuevo}).", 'success')

    elif accion == 'rechazar':
        solicitud.estado = 'rechazada'
        flash(f'Solicitud de vacaciones de {solicitud.usuario.nombre} rechazada.', 'info')
        
        # Tarea 8: Si rechazamos una MODIFICACIÓN/CANCELACIÓN (v2), esa versión muere.
        # La versión original (v1) sigue siendo la válida y 'actual'.
        # Por tanto, marcamos la rechazada como es_actual=False para que no salga en listados como "actual" aprobada.
        if solicitud.tipo_accion in ['modificacion', 'cancelacion']:
            solicitud.es_actual = False
            # Nota: No tocamos v1. v1 ya era es_actual=True y sigue siendolo.
            # No tocamos Saldo.
        
        # Si rechazamos una CREACIÓN (v1), sigue siendo es_actual=True (pero rechazada), 
        # para que el usuario vea que fue rechazada en su historial.
    
    else:
        flash('Acción no reconocida.', 'warning')
        return redirect(url_for('ausencias.aprobar_solicitudes'))
    
    # Registrar auditoría de la respuesta
    solicitud.aprobador_id = current_user.id
    solicitud.fecha_respuesta = datetime.utcnow()
    
    db.session.commit()
    
    # Enviar email al usuario con el resultado
    try:
        from src.email_service import enviar_email_respuesta
        enviar_email_respuesta(solicitud.usuario, solicitud)
    except Exception as e:
        print(f"Error enviando email notificación: {e}")

    return redirect(url_for('ausencias.aprobar_solicitudes'))


@ausencias_bp.route('/aprobaciones/bajas/<int:id>/<accion>', methods=['POST'])
@login_required
def responder_baja(id, accion):
    """Acción de aprobar o rechazar bajas/permisos."""
    if current_user.rol not in ['aprobador', 'admin']:
        flash('No tienes permisos.', 'danger')
        return redirect(url_for('main.index'))
        
    solicitud = SolicitudBaja.query.get_or_404(id)
    
    # Seguridad: Validar que el empleado está a su cargo
    es_mi_empleado = any(r.usuario_id == solicitud.usuario_id for r in current_user.usuarios_a_cargo)
    if not es_mi_empleado and current_user.rol != 'admin':
         flash('No tienes permiso para gestionar solicitudes de este usuario.', 'danger')
         return redirect(url_for('ausencias.aprobar_solicitudes'))
    
    # Procesar Acción
    if accion == 'aprobar':
        solicitud.estado = 'aprobada'
        flash(f'Baja/Permiso de {solicitud.usuario.nombre} aprobada.', 'success')
        
    elif accion == 'rechazar':
        solicitud.estado = 'rechazada'
        flash(f'Baja/Permiso de {solicitud.usuario.nombre} rechazada.', 'info')
    
    else:
        flash('Acción no reconocida.', 'warning')
        return redirect(url_for('ausencias.aprobar_solicitudes'))
    
    # Registrar auditoría
    solicitud.aprobador_id = current_user.id
    solicitud.fecha_respuesta = datetime.utcnow()
    
    db.session.commit()
    return redirect(url_for('ausencias.aprobar_solicitudes'))