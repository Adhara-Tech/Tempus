from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
import uuid

from src import db
from src.utils import calcular_dias_laborables
from src.models import SolicitudVacaciones, SolicitudBaja, Aprobador, TipoAusencia
from src.email_service import enviar_email_solicitud, enviar_email_respuesta
from src.google_calendar import sincronizar_vacaciones_a_google, sincronizar_baja_a_google
from src import aprobador_required
from . import ausencias_bp

# =======================
# VACACIONES
# =======================
@ausencias_bp.route('/vacaciones')
@login_required
def listar_vacaciones():
    # Solo mostrar actuales y que no estén "eliminadas" si decidimos usar ese estado
    solicitudes = SolicitudVacaciones.query.filter_by(usuario_id=current_user.id, es_actual=True).order_by(
        SolicitudVacaciones.fecha_solicitud.desc()
    ).all()
    return render_template('vacaciones.html', solicitudes=solicitudes)

@ausencias_bp.route('/vacaciones/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_vacaciones():
    if request.method == 'POST':
        fecha_inicio = datetime.strptime(request.form.get('fecha_inicio'), '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(request.form.get('fecha_fin'), '%Y-%m-%d').date()
        motivo = request.form.get('motivo', '')
        
        dias_solicitados = calcular_dias_laborables(fecha_inicio, fecha_fin)
        
        solicitud = SolicitudVacaciones(
            usuario_id=current_user.id,
            grupo_id=str(uuid.uuid4()), # Nuevo UUID
            version=1,
            es_actual=True,
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
        return redirect(url_for('ausencias.listar_vacaciones'))
    
    return render_template('solicitar_vacaciones.html')

@ausencias_bp.route('/vacaciones/cancelar/<int:id>', methods=['POST'])
@login_required
def cancelar_vacaciones(id):
    """Permite al usuario cancelar su propia solicitud (crea versión cancelada)"""
    solicitud = SolicitudVacaciones.query.get_or_404(id)
    
    if solicitud.usuario_id != current_user.id:
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('ausencias.listar_vacaciones'))

    if not solicitud.es_actual:
        flash('Solo se puede cancelar la versión actual.', 'danger')
        return redirect(url_for('ausencias.listar_vacaciones'))
    
    # Inmutabilidad: Marcamos anterior como no actual
    solicitud.es_actual = False
    
    # Nueva versión con estado 'cancelada'
    cancelada = SolicitudVacaciones(
        usuario_id=solicitud.usuario_id,
        grupo_id=solicitud.grupo_id,
        version=solicitud.version + 1,
        es_actual=True,
        fecha_inicio=solicitud.fecha_inicio,
        fecha_fin=solicitud.fecha_fin,
        dias_solicitados=solicitud.dias_solicitados,
        motivo=solicitud.motivo,
        estado='rechazada', # O 'cancelada' si añades ese estado al enum/modelo
        motivo_rectificacion="Cancelada por el usuario",
        fecha_solicitud=datetime.utcnow() # Fecha de cancelación
    )
    
    db.session.add(cancelada)
    db.session.commit()
    flash('Solicitud cancelada correctamente.', 'success')
    return redirect(url_for('ausencias.listar_vacaciones'))


# =======================
# BAJAS (Con TipoAusencia)
# =======================
@ausencias_bp.route('/bajas')
@login_required
def listar_bajas():
    solicitudes = SolicitudBaja.query.filter_by(usuario_id=current_user.id, es_actual=True).order_by(
        SolicitudBaja.fecha_solicitud.desc()
    ).all()
    return render_template('bajas.html', solicitudes=solicitudes)

@ausencias_bp.route('/bajas/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_baja():
    tipos_ausencia = TipoAusencia.query.all()
    
    if request.method == 'POST':
        fecha_inicio = datetime.strptime(request.form.get('fecha_inicio'), '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(request.form.get('fecha_fin'), '%Y-%m-%d').date()
        motivo = request.form.get('motivo', '')
        tipo_id = request.form.get('tipo_ausencia_id') # ID del TipoAusencia
        
        # Validación básica de motivo
        if not motivo:
            flash('Debes especificar detalles del motivo.', 'danger')
            return redirect(url_for('ausencias.solicitar_baja'))
            
        dias_solicitados = calcular_dias_laborables(fecha_inicio, fecha_fin)
        
        solicitud = SolicitudBaja(
            usuario_id=current_user.id,
            grupo_id=str(uuid.uuid4()),
            version=1,
            es_actual=True,
            tipo_ausencia_id=tipo_id, # Asignamos el tipo
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
        return redirect(url_for('ausencias.listar_bajas'))
    
    return render_template('solicitar_baja.html', tipos_ausencia=tipos_ausencia)

@ausencias_bp.route('/bajas/cancelar/<int:id>', methods=['POST'])
@login_required
def cancelar_baja(id):
    solicitud = SolicitudBaja.query.get_or_404(id)
    
    if solicitud.usuario_id != current_user.id:
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('ausencias.listar_bajas'))
        
    if not solicitud.es_actual:
        flash('Versión obsoleta.', 'danger')
        return redirect(url_for('ausencias.listar_bajas'))

    solicitud.es_actual = False
    
    cancelada = SolicitudBaja(
        usuario_id=solicitud.usuario_id,
        grupo_id=solicitud.grupo_id,
        version=solicitud.version + 1,
        es_actual=True,
        tipo_ausencia_id=solicitud.tipo_ausencia_id,
        fecha_inicio=solicitud.fecha_inicio,
        fecha_fin=solicitud.fecha_fin,
        dias_solicitados=solicitud.dias_solicitados,
        motivo=solicitud.motivo,
        estado='rechazada',
        motivo_rectificacion="Cancelada por el usuario",
        fecha_solicitud=datetime.utcnow()
    )
    db.session.add(cancelada)
    db.session.commit()
    flash('Baja cancelada.', 'success')
    return redirect(url_for('ausencias.listar_bajas'))


# =======================
# APROBACIÓN
# =======================
@ausencias_bp.route('/aprobar-solicitudes')
@aprobador_required
def aprobar_solicitudes():
    usuarios_ids = [r.usuario_id for r in Aprobador.query.filter_by(aprobador_id=current_user.id).all()]
    
    # Filtrar pendientes Y es_actual=True
    solicitudes_vac = SolicitudVacaciones.query.filter(
        SolicitudVacaciones.usuario_id.in_(usuarios_ids),
        SolicitudVacaciones.estado == 'pendiente',
        SolicitudVacaciones.es_actual == True
    ).order_by(SolicitudVacaciones.fecha_solicitud.desc()).all()
    
    solicitudes_bajas = SolicitudBaja.query.filter(
        SolicitudBaja.usuario_id.in_(usuarios_ids),
        SolicitudBaja.estado == 'pendiente',
        SolicitudBaja.es_actual == True
    ).order_by(SolicitudBaja.fecha_solicitud.desc()).all()
    
    return render_template('aprobar_solicitudes.html', 
                           solicitudes_vac=solicitudes_vac, 
                           solicitudes_bajas=solicitudes_bajas)

@ausencias_bp.route('/vacaciones/responder/<int:id>/<accion>', methods=['POST'])
@aprobador_required
def responder_solicitud(id, accion):
    # NOTA: En este caso, al aprobar/rechazar, NO creamos nueva versión, 
    # sino que actualizamos el estado de la versión ACTUAL pendiente.
    # El flujo de "versiones" es principalmente para cambios en los DATOS de la solicitud (fechas, etc).
    solicitud = SolicitudVacaciones.query.get_or_404(id)
    
    if solicitud.estado != 'pendiente' or not solicitud.es_actual:
        flash('Esta solicitud ya ha sido procesada o modificada.', 'warning')
        return redirect(url_for('ausencias.aprobar_solicitudes'))
    
    mensaje = ''
    if accion == 'aprobar':
        solicitud.estado = 'aprobada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        
        event_id = sincronizar_vacaciones_a_google(solicitud)
        if event_id:
            solicitud.google_event_id = event_id
            mensaje = 'Solicitud aprobada y sincronizada.'
        else:
            mensaje = 'Solicitud aprobada (⚠ Sincronización fallida).'
        
    elif accion == 'rechazar':
        solicitud.estado = 'rechazada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        solicitud.comentarios = request.form.get('comentarios', '')
        mensaje = 'Solicitud rechazada.'
    
    try:
        db.session.commit()
        enviar_email_respuesta(solicitud.usuario, solicitud)
        flash(mensaje, 'success' if '⚠' not in mensaje else 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('ausencias.aprobar_solicitudes'))

@ausencias_bp.route('/bajas/responder/<int:id>/<accion>', methods=['POST'])
@aprobador_required
def responder_baja(id, accion):
    solicitud = SolicitudBaja.query.get_or_404(id)
    
    if solicitud.estado != 'pendiente' or not solicitud.es_actual:
        flash('Esta solicitud ya ha sido procesada o modificada.', 'warning')
        return redirect(url_for('ausencias.aprobar_solicitudes'))
    
    mensaje = ''
    if accion == 'aprobar':
        solicitud.estado = 'aprobada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        
        event_id = sincronizar_baja_a_google(solicitud)
        if event_id:
            solicitud.google_event_id = event_id
            mensaje = 'Baja aprobada y sincronizada.'
        else:
            mensaje = 'Baja aprobada (⚠ Sincronización fallida).'
            
    elif accion == 'rechazar':
        solicitud.estado = 'rechazada'
        solicitud.aprobador_id = current_user.id
        solicitud.fecha_respuesta = datetime.now()
        solicitud.comentarios = request.form.get('comentarios', '')
        mensaje = 'Baja rechazada.'
    
    try:
        db.session.commit()
        enviar_email_respuesta(solicitud.usuario, solicitud)
        flash(mensaje, 'success' if '⚠' not in mensaje else 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('ausencias.aprobar_solicitudes'))