from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from src import db
from src.models import Usuario, SolicitudVacaciones, SolicitudBaja, Aprobador, Festivo
from src.utils import calcular_dias_laborables
from . import main_bp

@main_bp.route('/')
@login_required
def index():
    solicitudes_pendientes_count = 0
    if current_user.rol in ['aprobador', 'admin']:
        usuarios_ids = [r.usuario_id for r in Aprobador.query.filter_by(aprobador_id=current_user.id).all()]
        
        # Filtramos solo las pendientes que sean ACTUALES (no versiones viejas)
        count_vac = SolicitudVacaciones.query.filter(
            SolicitudVacaciones.usuario_id.in_(usuarios_ids),
            SolicitudVacaciones.estado == 'pendiente',
            SolicitudVacaciones.es_actual == True
        ).count()
        
        count_bajas = SolicitudBaja.query.filter(
            SolicitudBaja.usuario_id.in_(usuarios_ids),
            SolicitudBaja.estado == 'pendiente',
            SolicitudBaja.es_actual == True
        ).count()
        
        solicitudes_pendientes_count = count_vac + count_bajas
    
    return render_template('index.html', solicitudes_pendientes_count=solicitudes_pendientes_count)

@main_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not check_password_hash(current_user.password, current_password):
            flash('La contraseña actual es incorrecta', 'danger')
            return redirect(url_for('main.perfil'))
        
        if new_password != confirm_password:
            flash('Las contraseñas nuevas no coinciden', 'danger')
            return redirect(url_for('main.perfil'))
        
        if len(new_password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres', 'danger')
            return redirect(url_for('main.perfil'))
        
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Contraseña actualizada correctamente', 'success')
        return redirect(url_for('main.perfil'))
    
    return render_template('perfil.html')

@main_bp.route('/cronograma')
@login_required
def cronograma():
    # Solo mostramos versiones actuales y aprobadas
    solicitudes_vac = SolicitudVacaciones.query.filter_by(estado='aprobada', es_actual=True).all()
    solicitudes_bajas = SolicitudBaja.query.filter_by(estado='aprobada', es_actual=True).all()
    
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
        # Mostramos el tipo de ausencia si existe, si no "Baja"
        titulo = s.tipo_ausencia.nombre if s.tipo_ausencia else "Baja"
        eventos.append({
            'title': f"{s.usuario.nombre} - {titulo}",
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

@main_bp.route('/vacaciones/calcular-dias', methods=['POST'])
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