from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, date
import uuid

from src import db
from src.models import SolicitudVacaciones, SolicitudBaja, TipoAusencia, Usuario
from src.utils import calcular_dias_habiles, verificar_solapamiento
from . import ausencias_bp

# -------------------------------------------------------------------------
# GESTIÓN DE VACACIONES
# -------------------------------------------------------------------------

@ausencias_bp.route('/vacaciones')
@login_required
def listar_vacaciones():
    """Lista el historial de solicitudes de vacaciones del usuario actual."""
    solicitudes = SolicitudVacaciones.query.filter_by(usuario_id=current_user.id, es_actual=True)\
        .order_by(SolicitudVacaciones.fecha_solicitud.desc()).all()
    return render_template('vacaciones.html', solicitudes=solicitudes)


@ausencias_bp.route('/vacaciones/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_vacaciones():
    """Formulario y proceso de creación de nueva solicitud de vacaciones."""
    if request.method == 'POST':
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        motivo = request.form.get('motivo')

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
        # Comprueba si ya existe otra solicitud (pendiente/aprobada) en ese rango
        hay_solapamiento, mensaje_error = verificar_solapamiento(
            current_user.id, fecha_inicio, fecha_fin, tipo='vacaciones'
        )
        if hay_solapamiento:
            flash(f'Error: {mensaje_error}', 'danger')
            return redirect(url_for('ausencias.solicitar_vacaciones'))

        # 3. Cálculo de Días (Solo días Hábiles para vacaciones)
        dias_calculados = calcular_dias_habiles(fecha_inicio, fecha_fin)
        
        if dias_calculados <= 0:
            flash('El rango seleccionado no contiene días laborables (fines de semana o festivos).', 'warning')
            return redirect(url_for('ausencias.solicitar_vacaciones'))

        # 4. Validación de Saldo Disponible
        saldo_actual = current_user.dias_vacaciones_disponibles()
        if dias_calculados > saldo_actual:
            flash(f'Saldo insuficiente. Solicitas {dias_calculados} días pero solo te quedan {saldo_actual}.', 'danger')
            return redirect(url_for('ausencias.solicitar_vacaciones'))
        
        # 5. Creación de la Solicitud
        solicitud = SolicitudVacaciones(
            usuario_id=current_user.id,
            grupo_id=str(uuid.uuid4()),
            version=1,
            es_actual=True,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            dias_solicitados=dias_calculados,
            motivo=motivo,
            estado='pendiente',
            fecha_solicitud=datetime.utcnow()
        )
        
        db.session.add(solicitud)
        db.session.commit()
        
        flash('Solicitud de vacaciones enviada correctamente.', 'success')
        return redirect(url_for('ausencias.listar_vacaciones'))
        
    return render_template('solicitar_vacaciones.html')


@ausencias_bp.route('/vacaciones/cancelar/<int:id>', methods=['POST'])
@login_required
def cancelar_vacaciones(id):
    """Permite al usuario cancelar su propia solicitud si aún está pendiente."""
    solicitud = SolicitudVacaciones.query.get_or_404(id)
    
    # Seguridad: Verificar propiedad
    if solicitud.usuario_id != current_user.id:
        flash('No tienes permiso para modificar esta solicitud.', 'danger')
        return redirect(url_for('ausencias.listar_vacaciones'))
        
    # Lógica de Negocio: Solo pendientes
    if solicitud.estado != 'pendiente':
        flash('Solo se pueden cancelar solicitudes pendientes. Contacta con RRHH.', 'warning')
        return redirect(url_for('ausencias.listar_vacaciones'))
    
    # Acción: Marcar como rechazada/cancelada
    solicitud.estado = 'rechazada'
    solicitud.comentarios = 'Cancelada por el usuario'
    solicitud.fecha_respuesta = datetime.utcnow()
    
    db.session.commit()
    flash('Solicitud cancelada correctamente.', 'info')
    return redirect(url_for('ausencias.listar_vacaciones'))


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
    tipos = TipoAusencia.query.all()
    
    if request.method == 'POST':
        tipo_id = request.form.get('tipo_ausencia')
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        motivo = request.form.get('motivo')
        
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
            current_user.id, fecha_inicio, fecha_fin, tipo='baja'
        )
        if hay_solapamiento:
            flash(f'Error: {mensaje_error}', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))
            
        # 2. Cálculo de Días (Depende del Tipo de Ausencia)
        tipo_obj = TipoAusencia.query.get(tipo_id)
        if not tipo_obj:
            flash('Tipo de ausencia no válido.', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))

        if tipo_obj.tipo_dias == 'naturales':
            # Cuenta todos los días del calendario
            dias = (fecha_fin - fecha_inicio).days + 1
        else:
            # Cuenta solo días hábiles (laborables)
            dias = calcular_dias_habiles(fecha_inicio, fecha_fin)

        # 3. Creación de la Solicitud
        solicitud = SolicitudBaja(
            usuario_id=current_user.id,
            grupo_id=str(uuid.uuid4()),
            version=1,
            es_actual=True,
            tipo_ausencia_id=tipo_id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            dias_solicitados=dias,
            motivo=motivo,
            estado='pendiente',
            fecha_solicitud=datetime.utcnow()
        )
        
        db.session.add(solicitud)
        db.session.commit()
        
        flash('Baja/Permiso registrado correctamente.', 'success')
        return redirect(url_for('ausencias.listar_bajas'))
        
    return render_template('solicitar_baja.html', tipos=tipos)


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
        solicitud.estado = 'aprobada'
        flash(f'Solicitud de vacaciones de {solicitud.usuario.nombre} aprobada.', 'success')
        # TODO: Aquí se podría integrar el envío de email de confirmación
        
    elif accion == 'rechazar':
        solicitud.estado = 'rechazada'
        flash(f'Solicitud de vacaciones de {solicitud.usuario.nombre} rechazada.', 'info')
    
    else:
        flash('Acción no reconocida.', 'warning')
        return redirect(url_for('ausencias.aprobar_solicitudes'))
    
    # Registrar auditoría de la respuesta
    solicitud.aprobador_id = current_user.id
    solicitud.fecha_respuesta = datetime.utcnow()
    
    db.session.commit()
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