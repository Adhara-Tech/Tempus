import pytest
from flask import session
from src.models import UserKnownIP, db

def test_mfa_enabled_by_default(client, employee_user):
    """
    Verifica que por defecto (MFA_ENABLED=True) se pide MFA para nueva IP.
    """
    # 1. Login desde IP desconocida (1.2.3.4)
    response = client.post('/login', data={
        'email': employee_user.email,
        'password': 'emp123'
    }, environ_overrides={'REMOTE_ADDR': '1.2.3.4'})
    
    # Debe redirigir a MFA verify
    assert response.status_code == 302
    assert '/mfa-verify' in response.location
    
    with client.session_transaction() as sess:
        assert 'mfa_user_id' in sess
        assert '_user_id' not in sess

def test_mfa_disabled(client, employee_user, test_app):
    """
    Verifica que si MFA_ENABLED=False no se pide MFA para nueva IP.
    """
    # Desactivar MFA en config
    test_app.config['MFA_ENABLED'] = False
    
    # Login desde IP desconocida (9.9.9.9)
    # follow_redirects=True para ver hasta donde llegamos
    response = client.post('/login', data={
        'email': employee_user.email,
        'password': 'emp123'
    }, environ_overrides={'REMOTE_ADDR': '9.9.9.9'}, follow_redirects=True)
    
    # Debe ir directo al index (200 OK tras redirect)
    assert response.status_code == 200
    assert b'Inicio de sesi\xc3\xb3n exitoso' in response.data
    
    # Verificar que estamos logueados
    with client.session_transaction() as sess:
        assert '_user_id' in sess
        assert int(sess['_user_id']) == employee_user.id
        assert 'mfa_user_id' not in sess
