import pytest
from flask import session
from src.models import UserKnownIP, db

def test_mfa_flow_new_ip(client, employee_user):
    """
    Test completo del flujo MFA para nueva IP:
    1. Login desde nueva IP -> Redirige a MFA
    2. Verificar OTP correcto -> Redirige a Index y guarda IP
    3. Login desde misma IP -> Acceso directo
    """
    
    # 1. Login desde IP desconocida (1.2.3.4)
    # Usamos environ_overrides para simular REMOTE_ADDR
    response = client.post('/login', data={
        'email': employee_user.email,
        'password': 'emp123'
    }, environ_overrides={'REMOTE_ADDR': '1.2.3.4'})
    
    # Debe redirigir a MFA verify
    assert response.status_code == 302
    assert '/mfa-verify' in response.location
    
    # Verificar que estamos en sesión 'mfa_user_id' pero NO logueados (flask-login)
    # Flask-Login guarda '_user_id' en session cuando está logueado.
    with client.session_transaction() as sess:
        assert 'mfa_user_id' in sess
        assert sess['mfa_user_id'] == employee_user.id
        assert 'mfa_otp' in sess
        otp_code = sess['mfa_otp']
        # '_user_id' NO debería estar si no hemos llamado a login_user todavía...
        # Espera, mi implementación llama a verify_ip_and_login ANTES de login_user.
        # Si IP es nueva, login_user NO se llama, solo se guarda en session y redirect.
        # Correcto.
        assert '_user_id' not in sess 

    # 2. Verificar código incorrecto
    response = client.post('/mfa-verify', data={
        'code': '000000' # Incorrecto
    }, follow_redirects=True, environ_overrides={'REMOTE_ADDR': '1.2.3.4'})
    assert b'C\xc3\xb3digo incorrecto' in response.data or b'Codigo incorrecto' in response.data or b'incorrecto' in response.data

    # 3. Verificar código correcto
    response = client.post('/mfa-verify', data={
        'code': otp_code
    }, follow_redirects=True, environ_overrides={'REMOTE_ADDR': '1.2.3.4'})
    
    # Debe redirigir a index y mostrar éxito
    assert response.status_code == 200
    assert b'Bienvenido' in response.data or b'Login successful' in response.data or b'Inicio de sesi\xc3\xb3n exitoso' in response.data
    
    # Verificar que la IP se guardó en BD
    known_ip = UserKnownIP.query.filter_by(usuario_id=employee_user.id, ip_address='1.2.3.4').first()
    assert known_ip is not None
    
    # Logout
    client.get('/logout', follow_redirects=True)
    
    # 4. Login Subejcutivo desde MISMA IP (1.2.3.4) -> Debe saltar MFA
    response = client.post('/login', data={
        'email': employee_user.email,
        'password': 'emp123'
    }, environ_overrides={'REMOTE_ADDR': '1.2.3.4'})
    
    # Debe redirigir a index directamente
    assert response.status_code == 302
    assert '/mfa-verify' not in response.location
    assert '/login' not in response.location # No error
    
    # Verificar que session tiene login
    with client.session_transaction() as sess:
        assert '_user_id' in sess
        assert int(sess['_user_id']) == employee_user.id

def test_mfa_existing_ip(client, employee_user):
    """
    Test que verifica que una IP pre-existente no pide MFA
    """
    # Pre-crear IP conocida
    ip = UserKnownIP(usuario_id=employee_user.id, ip_address='5.5.5.5')
    db.session.add(ip)
    db.session.commit()
    
    # Login desde esa IP
    response = client.post('/login', data={
        'email': employee_user.email,
        'password': 'emp123'
    }, environ_overrides={'REMOTE_ADDR': '5.5.5.5'})
    
    # Directo al index
    assert response.status_code == 302
    assert '/mfa-verify' not in response.location
