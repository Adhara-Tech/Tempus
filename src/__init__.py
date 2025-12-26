from flask import Flask, redirect, url_for, flash, render_template, request
from flask_login import LoginManager, current_user
from werkzeug.security import generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from functools import wraps
import os

# Imports para Logging (ECS + Rotación)
import logging
from logging.handlers import RotatingFileHandler
import ecs_logging
import sys

# Protección contra ataques de fuerza bruta
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Protección CSRF
from flask_wtf.csrf import CSRFProtect

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


# CONFIGURACIÓN DE LOGGING (ECS + Rotación)
def configure_logging(app):
    # Configurar el logger raíz de la aplicación
    logger = logging.getLogger(app.name)
    logger.setLevel(logging.INFO)

    # Configurar directorio
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 1. Handler para archivo (JSON ECS)
    # Rota cada 10MB, mantiene 5 backups. Nombre: tempus.json
    log_file_path = os.path.join(log_dir, 'tempus.json')
    file_handler = RotatingFileHandler(log_file_path, maxBytes=10*1024*1024, backupCount=5)
    file_handler.setFormatter(ecs_logging.StdlibFormatter())

    # 2. Handler para consola (útil para ver logs en tiempo real en kubectl logs)
    # Formato simple para lectura humana en consola, o podrías usar ECS también
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    # Limpiamos handlers anteriores para evitar duplicados si se recarga
    logger.handlers = []
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Enganchar el logger de la app de Flask al que acabamos de configurar
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)
    
    # Opcional: Enganchar gunicorn.error si estamos en producción
    gunicorn_logger = logging.getLogger('gunicorn.error')
    if gunicorn_logger.handlers:
        app.logger.handlers.extend(gunicorn_logger.handlers)

# CREACIÓN Y CONFIGURACIÓN DE LA APP
app = Flask(__name__, template_folder='../templates')

# ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# INICIALIZAR LOGGING
configure_logging(app)

# CONFIGURACIÓN DE OAUTHLIB
if app.config.get('FLASK_DEBUG'):
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
else:
    os.environ.pop('OAUTHLIB_INSECURE_TRANSPORT', None)

# ASIGNACIÓN DE VARIABLES DE ENTORNO
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-fallback')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///fichaje.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS', 'False').lower() == 'true'
app.config['GOOGLE_CALENDAR_ID'] = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')
app.config['MFA_ENABLED'] = os.environ.get('MFA_ENABLED', 'True').lower() == 'true'
app.config['DEFAULT_ADMIN_EMAIL'] = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
app.config['DEFAULT_ADMIN_INITIAL_PASSWORD'] = os.environ.get('DEFAULT_ADMIN_INITIAL_PASSWORD', 'admin123')

# Configuración de Flask-Dance (Google)
app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

google_bp = make_google_blueprint(
    scope=["profile", "email"],
    redirect_to="main.index"
)
app.register_blueprint(google_bp, url_prefix="/login")

# Límite global de 200/día y 50/hora por IP. Almacenamiento en memoria.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Manejador personalizado para el error 429 (Too Many Requests) con Logging
@app.errorhandler(429)
def ratelimit_handler(e):
    app.logger.warning(
        "Rate limit excedido",
        extra={
            "event.action": "rate-limit",
            "source.ip": get_remote_address(),
            "http.request.method": request.method,
            "url.path": request.path,
            "error.message": e.description
        }
    )
    return render_template('429.html', error=e.description), 429

# INICIALIZACIÓN DE EXTENSIONES
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

# INICIALIZAR CSRF
csrf = CSRFProtect(app)

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


@app.before_request
def init_db():
    if not hasattr(app, 'db_initialized'):
        db.create_all()
        # 1. Crear Tipo de Ausencia por defecto "Otros" si no existe
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
        
        app.db_initialized = True

# REGISTRO DE BLUEPRINTS
from src.routes import auth_bp, main_bp, fichajes_bp, ausencias_bp, admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(fichajes_bp)
app.register_blueprint(ausencias_bp)
app.register_blueprint(admin_bp)

from src.cli import cerrar_anio_command, import_users_command, init_admin_command
app.cli.add_command(cerrar_anio_command)
app.cli.add_command(import_users_command)
app.cli.add_command(init_admin_command)
