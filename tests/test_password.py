"""Tests for password management via admin panel."""
from werkzeug.security import check_password_hash, generate_password_hash
from src.models import Usuario
from src import db


def test_admin_change_user_password(auth_admin_client, employee_user):
    """Admin can change a user's password."""
    new_password = 'NewSecurePass123!'
    
    response = auth_admin_client.post(f'/admin/usuarios/editar/{employee_user.id}', data={
        'nombre': employee_user.nombre,
        'email': employee_user.email,
        'rol': employee_user.rol,
        'dias_vacaciones': employee_user.dias_vacaciones,
        'password': new_password  # New password
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert "Usuario actualizado correctamente" in response.text
    
    # Verify password changed
    db.session.refresh(employee_user)
    assert check_password_hash(employee_user.password, new_password)


def test_admin_edit_without_password_keeps_existing(auth_admin_client, employee_user):
    """Editing a user without providing password keeps the existing password."""
    original_password_hash = employee_user.password
    
    response = auth_admin_client.post(f'/admin/usuarios/editar/{employee_user.id}', data={
        'nombre': 'Updated Name',
        'email': employee_user.email,
        'rol': employee_user.rol,
        'dias_vacaciones': employee_user.dias_vacaciones
        # Note: no 'password' field
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    # Verify password unchanged
    db.session.refresh(employee_user)
    assert employee_user.password == original_password_hash
    assert employee_user.nombre == 'Updated Name'


def test_admin_create_user_with_password(auth_admin_client):
    """Admin can create a new user with a password."""
    response = auth_admin_client.post('/admin/usuarios/crear', data={
        'nombre': 'Nuevo Usuario',
        'email': 'nuevo@test.com',
        'password': 'TestPassword123',
        'rol': 'empleado',
        'dias_vacaciones': '22'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert "Usuario creado correctamente" in response.text
    
    # Verify user created with correct password
    user = Usuario.query.filter_by(email='nuevo@test.com').first()
    assert user is not None
    assert check_password_hash(user.password, 'TestPassword123')


def test_password_is_hashed_not_plaintext(auth_admin_client, employee_user):
    """Verify passwords are stored hashed, not in plaintext."""
    new_password = 'PlainTextTest123'
    
    auth_admin_client.post(f'/admin/usuarios/editar/{employee_user.id}', data={
        'nombre': employee_user.nombre,
        'email': employee_user.email,
        'rol': employee_user.rol,
        'dias_vacaciones': employee_user.dias_vacaciones,
        'password': new_password
    }, follow_redirects=True)
    
    db.session.refresh(employee_user)
    
    # Password should NOT be stored as plaintext
    assert employee_user.password != new_password
    # But should verify correctly
    assert check_password_hash(employee_user.password, new_password)
