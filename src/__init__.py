from flask import Flask, redirect, url_for, flash
from flask_login import LoginManager, current_user
from werkzeug.security import generate_password_hash
from functools import wraps
import os

# Importamos las extensiones y modelos
from .models import db, Usuario, Festivo, TipoAusencia  # Añadido TipoAusencia
from .email_service import init_mail
from flask_dance.contrib.google import make_google_blueprint, google

# Carga de fichero env
from dotenv import load_dotenv
load_dotenv()

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
    redirect_to="auth.google_logged_in"  # Actualizado para apuntar al Blueprint de auth
)
app.register_blueprint(google_bp, url_prefix="/login")

# INICIALIZACIÓN DE EXTENSIONES
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'  # Actualizado al endpoint del Blueprint

# INICIALIZAR SERVICIO DE EMAIL
init_mail(app)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# DEFINICIÓN DE DECORADORES (Se mantienen aquí para ser importados por los Blueprints)
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

# REGISTRO DE BLUEPRINTS (NUEVA ESTRUCTURA)
# Importamos al final para evitar dependencias circulares, ya que los blueprints importan db/app de aquí
from src.routes import auth_bp, main_bp, fichajes_bp, ausencias_bp, admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(fichajes_bp)
app.register_blueprint(ausencias_bp)
app.register_blueprint(admin_bp) # Puedes añadir url_prefix='/admin' si quieres prefijar todas

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
        
        # 2. Crear Tipo de Ausencia por defecto "Otros" si no existe (NUEVO)
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