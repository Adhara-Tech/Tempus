from flask import Flask, redirect, url_for, flash, render_template, request
from flask_login import LoginManager, current_user
from werkzeug.security import generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from functools import wraps
import os

# Import para Flask Migrate
from flask_migrate import Migrate

# Import para Scheduler (Tareas programadas)
from flask_apscheduler import APScheduler

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
# NOTA: db se importa aquí, NO se debe redefinir abajo
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
    logger = logging.getLogger(app.name)
    logger.setLevel(logging.INFO)

    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file_path = os.path.join(log_dir, 'tempus.json')
    file_handler = RotatingFileHandler(log_file_path, maxBytes=10*1024*1024, backupCount=5)
    file_handler.setFormatter(ecs_logging.StdlibFormatter())

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    logger.handlers = []
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)
    
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
app.config['ENABLE_MANUAL_ENTRY'] = os.environ.get('ENABLE_MANUAL_ENTRY', 'True').lower() == 'true'
app.config['MFA_ENABLED'] = os.environ.get('MFA_ENABLED', 'True').lower() == 'true'
app.config['HIDE_TIMELINE'] = os.environ.get('HIDE_TIMELINE', 'False').lower() == 'true'
app.config['DEFAULT_ADMIN_EMAIL'] = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
app.config['DEFAULT_ADMIN_INITIAL_PASSWORD'] = os.environ.get('DEFAULT_ADMIN_INITIAL_PASSWORD', 'admin123')

# Configuración Scheduler
app.config['SCHEDULER_API_ENABLED'] = True

# Configuración de Flask-Dance (Google)
app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

google_bp = make_google_blueprint(
    scope=["profile", "email"],
    redirect_to="main.index"
)
app.register_blueprint(google_bp, url_prefix="/login")

# Límite global
# 5 por segundo para proteger contra ataques de fuerza bruta
# 30 por minuto debería ser suficiente para la mayoría de los usuarios
# 3000 por día como límite máximo global, suficiente incluso si se deja la app abierta la 24 horas del día
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["5 per second", "30 per minute", "5000 per day"],
    storage_uri="memory://"
)

@app.errorhandler(429)
def ratelimit_handler(e):
    ip_origen = get_remote_address() 
    app.logger.warning(
        f"Rate limit excedido desde {ip_origen}", 
        extra={
            "event.action": "rate-limit",
            "source.ip": ip_origen,
            "http.request.method": request.method,
            "url.path": request.path,
            "error.message": e.description
        }
    )
    return render_template('429.html', error=e.description), 429

# ==========================================
# INICIALIZACIÓN DE EXTENSIONES
# ==========================================

# 1. Base de Datos
db.init_app(app)

# 2. Migraciones (CORREGIDO)
migrate = Migrate(app, db)

# 3. Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

# 4. CSRF
csrf = CSRFProtect(app)

# 5. Email
init_mail(app)

# 6. Scheduler (Cierre automático de fichajes)
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# Definir la tarea de cierre automático (03:00 AM)
from src.tasks import cerrar_fichajes_abiertos # Importar aquí para evitar circularidad

@scheduler.task('cron', id='cierre_diario', hour=3, minute=0)
def job_cierre_diario():
    print("⏰ [CRON] Ejecutando tarea de cierre automático...")
    cerrar_fichajes_abiertos(app)

# ==========================================

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
        # db.create_all() # Con migraciones ya no es estrictamente necesario, pero útil en dev
        
        # Crear Tipo de Ausencia por defecto
        # Usamos inspector para no fallar si la tabla no existe aún (primera ejecución)
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if inspector.has_table("tipos_ausencia"):
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