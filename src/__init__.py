from flask import Flask, redirect, url_for, flash, render_template
from flask_login import LoginManager, current_user
from werkzeug.security import generate_password_hash
from functools import wraps
import os

# Protección contra ataques de fuerza bruta
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Importamos las extensiones y modelos
from .models import db, Usuario, Festivo, TipoAusencia
from .email_service import init_mail
from flask_dance.contrib.google import make_google_blueprint, google

# Carga de fichero env
from dotenv import load_dotenv
load_dotenv()

# Importamos utilidades
from src.utils import decimal_to_human

# Permitir transporte inseguro para OAuth en desarrollo (HTTP)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# CREACIÓN Y CONFIGURACIÓN DE LA APP
app = Flask(__name__, template_folder='../templates')

# ASIGNACIÓN DE VARIABLES DE ENTORNO
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-fallback')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///fichaje.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS', 'False').lower() == 'true'
app.config['GOOGLE_CALENDAR_ID'] = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')

# Configuración de Flask-Dance (Google)
app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

google_bp = make_google_blueprint(
    scope=["profile", "email"],
    redirect_to="auth.google_logged_in"
)
app.register_blueprint(google_bp, url_prefix="/login")

# Límite global de 200/día y 50/hora por IP. Almacenamiento en memoria.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Manejador personalizado para el error 429 (Too Many Requests)
@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template('429.html', error=e.description), 429

# INICIALIZACIÓN DE EXTENSIONES
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

# INICIALIZAR SERVICIO DE EMAIL
init_mail(app)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# DEFINICIÓN DE DECORADORES
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            flash('Acceso denegado. Se requiere rol de administrador.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

def aprobador_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol not in ['admin', 'aprobador']:
            flash('Acceso denegado. Se requiere rol de aprobador o administrador.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

# FILTRO DE HORAS
@app.template_filter('formato_hora')
def formato_hora_filter(value):
    return decimal_to_human(value)

# REGISTRO DE BLUEPRINTS
from src.routes import auth_bp, main_bp, fichajes_bp, ausencias_bp, admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(fichajes_bp)
app.register_blueprint(ausencias_bp)
app.register_blueprint(admin_bp)

# INICIALIZACIÓN DE BBDD
@app.before_request
def init_db():
    if not hasattr(app, 'db_initialized'):
        db.create_all()
        
        # 1. Crear usuario admin si no existe
        if not Usuario.query.filter_by(email='admin@example.com').first():
            admin = Usuario(
                nombre='Administrador',
                email='admin@example.com',
                password=generate_password_hash('admin123'),
                rol='admin',
                dias_vacaciones=25
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Usuario Administrador creado.")
        
        # 2. Crear Tipo de Ausencia por defecto "Otros" si no existe
        if not TipoAusencia.query.filter_by(nombre='Otros').first():
            otros = TipoAusencia(
                nombre='Otros',
                descripcion='Otras causas justificadas',
                max_dias=365,
                tipo_dias='naturales',
                requiere_justificante=True,
                descuenta_vacaciones=False
            )
            db.session.add(otros)
            db.session.commit()
            print("✅ Tipo de ausencia 'Otros' creado automáticamente.")

        # 3. Migración de Saldos de Vacaciones (Tarea 3)
        from datetime import datetime
        from .models import SaldoVacaciones, SolicitudVacaciones
        
        current_year = datetime.now().year
        usuarios = Usuario.query.all()
        
        for usuario in usuarios:
            # Verificar si ya tiene saldo para este año
            saldo = SaldoVacaciones.query.filter_by(usuario_id=usuario.id, anio=current_year).first()
            
            if not saldo:
                # Calcular días disfrutados este año
                # Solicitudes aprobadas y actuales que caigan en este año
                # Nota: Una solicitud podría cruzar años, pero simplificamos asumiendo fechas dentro del año
                # o que el usuario gestiona cortes. La instrucción dice "que caigan en el año actual".
                # Para mayor precisión usamos intersection, pero seguiremos lógica simple de "solicitudes del año".
                
                dias_disfrutados = 0
                solicitudes = SolicitudVacaciones.query.filter_by(usuario_id=usuario.id, estado='aprobada', es_actual=True).all()
                
                for sol in solicitudes:
                    # Simple check: si la solicitud empieza o termina en este año
                    if sol.fecha_inicio.year == current_year:
                        dias_disfrutados += sol.dias_solicitados
                
                # Crear Saldo
                nuevo_saldo = SaldoVacaciones(
                    usuario_id=usuario.id,
                    anio=current_year,
                    dias_totales=usuario.dias_vacaciones, # Usamos el valor antiguo
                    dias_disfrutados=dias_disfrutados
                )
                db.session.add(nuevo_saldo)
                print(f"✅ SaldoVacaciones migrado para {usuario.email} ({current_year}): {dias_disfrutados}/{usuario.dias_vacaciones}")
        
        db.session.commit()
        
        
        app.db_initialized = True

from src.cli import cerrar_anio_command, import_users_command
app.cli.add_command(cerrar_anio_command)
app.cli.add_command(import_users_command)
