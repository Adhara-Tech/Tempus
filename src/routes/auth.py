from flask import render_template, request, redirect, url_for, flash, session, current_app
from datetime import datetime, timedelta
import random
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from flask_dance.contrib.google import google
from flask_dance.consumer import oauth_authorized
from src import google_bp
from src.models import db, Usuario, UserKnownIP
from src.email_service import enviar_email_otp
from . import auth_bp

from src import limiter

def verify_ip_and_login(user):
    """
    Verifica si la IP es conocida.
    Si es conocida -> login directo.
    Si es nueva -> envía OTP y redirige a verificación.
    """
    ip = request.remote_addr
    
    # Buscar si existe IP conocida
    known_ip = UserKnownIP.query.filter_by(
        usuario_id=user.id,
        ip_address=ip
    ).first()
    
    if known_ip or not current_app.config.get('MFA_ENABLED', True):
        # IP conocida o MFA desactivado: actualizar last_seen si aplica y loguear
        if known_ip:
            known_ip.last_seen = datetime.utcnow()
            db.session.commit()
        
        login_user(user)
        flash("Inicio de sesión exitoso", "success")
        return redirect(url_for("main.index"))
    
    # IP nueva: iniciar proceso MFA
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    
    # Guardar en sesión (expira en 10 min)
    session['mfa_user_id'] = user.id
    session['mfa_otp'] = otp
    session['mfa_expiry'] = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
    
    # Enviar email
    enviar_email_otp(user, otp)
    
    flash("Se ha detectado un nuevo dispositivo. Revisa tu email para el código de verificación.", "info")
    return redirect(url_for("auth.mfa_verify"))


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
        return verify_ip_and_login(user)
    else:
        flash("No existe un usuario con este email.", "danger")
        return redirect(url_for("auth.login"))

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  #Límite de 5 intentos por minuto
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        # 1. Sanitización: quitar espacios en blanco al inicio/final
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
        # 2. Validación básica de campos vacíos
        if not email or not password:
            flash('Por favor, introduce email y contraseña.', 'warning')
            return render_template('login.html')

        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and check_password_hash(usuario.password, password):
            return verify_ip_and_login(usuario)
        else:
            flash('Email o contraseña incorrectos', 'danger')
    
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/mfa-verify', methods=['GET', 'POST'])
def mfa_verify():
    if 'mfa_user_id' not in session:
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        stored_otp = session.get('mfa_otp')
        expiry = session.get('mfa_expiry')
        
        if not stored_otp or not expiry:
             flash("Sesión expirada. Intenta loguearte de nuevo.", "danger")
             return redirect(url_for('auth.login'))
             
        if datetime.utcnow().timestamp() > expiry:
             flash("El código ha expirado.", "warning")
             return redirect(url_for('auth.login'))
             
        if code == stored_otp:
            # Éxito
            user_id = session['mfa_user_id']
            user = Usuario.query.get(user_id)
            
            if user:
                # Guardar IP
                new_ip = UserKnownIP(
                    usuario_id=user.id,
                    ip_address=request.remote_addr
                )
                db.session.add(new_ip)
                db.session.commit()
                
                # Limpiar sesión MFA
                session.pop('mfa_user_id', None)
                session.pop('mfa_otp', None)
                session.pop('mfa_expiry', None)
                
                login_user(user)
                flash("Dispositivo verificado y guardado. Bienvenido.", "success")
                return redirect(url_for('main.index'))
        
        flash("Código incorrecto.", "danger")
    
    return render_template('auth/mfa.html')