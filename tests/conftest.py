import pytest
from src import app, db
from src.models import Usuario, TipoAusencia, Aprobador
from werkzeug.security import generate_password_hash

@pytest.fixture
def test_app():
    # Configuración de la app para testing
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "SERVER_NAME": "localhost.localdomain"
    })

    # Contexto de la aplicación
    with app.app_context():
        db.create_all()
        app.db_initialized = True 
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(test_app):
    return test_app.test_client()

@pytest.fixture
def runner(test_app):
    return test_app.test_cli_runner()

@pytest.fixture
def admin_user(test_app):
    user = Usuario(
        nombre='Admin Test',
        email='admin@test.com',
        password=generate_password_hash('admin123'),
        rol='admin'
    )
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def employee_user(test_app):
    user = Usuario(
        nombre='Employee Test',
        email='employee@test.com',
        password=generate_password_hash('emp123'),
        rol='empleado',
        dias_vacaciones=25 # Saldo inicial explícito
    )
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def approver_user(test_app, employee_user):
    # 1. Crear usuario con rol aprobador
    user = Usuario(
        nombre='Jefe Test',
        email='boss@test.com',
        password=generate_password_hash('boss123'),
        rol='aprobador'
    )
    db.session.add(user)
    db.session.commit()
    
    # 2. Asignar employee_user a cargo de este aprobador
    relacion = Aprobador(usuario_id=employee_user.id, aprobador_id=user.id)
    db.session.add(relacion)
    db.session.commit()
    
    return user

@pytest.fixture
def absence_type(test_app):
    tipo = TipoAusencia(
        nombre='Vacaciones',
        descripcion='Vacaciones anuales',
        max_dias=25,
        tipo_dias='naturales'
    )
    db.session.add(tipo)
    db.session.commit()
    return tipo

# --- Clientes Autenticados ---

@pytest.fixture
def login_as(client):
    """Helper para loguear un usuario dado su email y password."""
    def _login(email, password):
        return client.post('/login', data={
            'email': email,
            'password': password
        }, follow_redirects=True)
    return _login

@pytest.fixture
def auth_client(client, employee_user):
    """Cliente pre-logueado como empleado."""
    with client:
        client.post('/login', data={
            'email': employee_user.email,
            'password': 'emp123'
        }, follow_redirects=True)
        yield client

@pytest.fixture
def auth_admin_client(client, admin_user):
    """Cliente pre-logueado como admin."""
    with client:
        client.post('/login', data={
            'email': admin_user.email,
            'password': 'admin123'
        }, follow_redirects=True)
        yield client

@pytest.fixture
def auth_approver_client(client, approver_user):
    """Cliente pre-logueado como aprobador (jefe)."""
    with client:
        client.post('/login', data={
            'email': approver_user.email,
            'password': 'boss123'
        }, follow_redirects=True)
        yield client