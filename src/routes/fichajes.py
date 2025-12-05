from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from calendar import monthrange
import uuid

from src import db
from src.models import Fichaje
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
        
        # CAPTURAR PAUSA
        try:
            pausa = int(request.form.get('pausa') or 0)
        except ValueError:
            pausa = 0
        
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
    
    return render_template('crear_fichaje.html', now=datetime.now)

@fichajes_bp.route('/fichajes/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    fichaje_actual = Fichaje.query.get_or_404(id)
    
    if fichaje_actual.usuario_id != current_user.id and current_user.rol != 'admin':
        flash('No tienes permisos para editar este fichaje', 'danger')
        return redirect(url_for('fichajes.listar'))
    
    if not fichaje_actual.es_actual:
        flash('Solo se puede editar la versión vigente de un fichaje.', 'warning')
        return redirect(url_for('fichajes.listar'))
    
    if request.method == 'POST':
        motivo = request.form.get('motivo')
        if not motivo:
            flash('El motivo es obligatorio para rectificar un fichaje.', 'danger')
            return redirect(url_for('fichajes.editar', id=id))

        # CAPTURAR PAUSA
        try:
            pausa = int(request.form.get('pausa') or 0)
        except ValueError:
            pausa = 0

        # VERSIONADO
        fichaje_actual.es_actual = False
        
        nuevo_fichaje = Fichaje(
            usuario_id=fichaje_actual.usuario_id,
            editor_id=current_user.id, # Quién modifica
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
        flash('Fichaje rectificado correctamente.', 'success')
        return redirect(url_for('fichajes.listar'))
    
    return render_template('editar_fichaje.html', fichaje=fichaje_actual, now=datetime.now)

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
    
    fichaje_actual.es_actual = False
    
    fichaje_borrado = Fichaje(
        usuario_id=fichaje_actual.usuario_id,
        editor_id=current_user.id, # Quién elimina
        grupo_id=fichaje_actual.grupo_id,
        version=fichaje_actual.version + 1,
        es_actual=True,
        tipo_accion='eliminacion',
        motivo_rectificacion="Eliminado por el usuario",
        fecha=fichaje_actual.fecha,
        hora_entrada=fichaje_actual.hora_entrada,
        hora_salida=fichaje_actual.hora_salida,
        pausa=fichaje_actual.pausa
    )
    
    db.session.add(fichaje_borrado)
    db.session.commit()
    flash('Fichaje eliminado correctamente.', 'success')
    return redirect(url_for('fichajes.listar'))