from flask import Blueprint

# Definición de los Blueprints
auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)
fichajes_bp = Blueprint('fichajes', __name__)
ausencias_bp = Blueprint('ausencias', __name__)
admin_bp = Blueprint('admin', __name__)

# Importamos las rutas para que se registren
from . import auth, main, fichajes, ausencias, admin