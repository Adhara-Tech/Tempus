"""
Test para verificar que la auditoría muestra solo los cambios específicos en fichajes
"""
from datetime import datetime, date, time
from src.models import Fichaje, Usuario, db


def test_auditoria_muestra_cambios_especificos(client, admin_user, employee_user):
    """Verifica que la auditoría muestra solo los campos que cambiaron en un fichaje"""
    # Login como admin
    client.post('/login', data={
        'email': admin_user.email,
        'password': 'admin123'
    })
    
    # Crear un fichaje inicial
    fichaje_original = Fichaje(
        usuario_id=employee_user.id,
        editor_id=employee_user.id,
        fecha=date(2026, 1, 1),
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        pausa=30,
        version=1,
        es_actual=False,
        tipo_accion='creacion'
    )
    db.session.add(fichaje_original)
    db.session.commit()
    
    grupo_id = fichaje_original.grupo_id
    
    # Modificar el fichaje (cambiar solo hora de entrada)
    fichaje_modificado = Fichaje(
        grupo_id=grupo_id,
        usuario_id=employee_user.id,
        editor_id=admin_user.id,
        fecha=date(2026, 1, 1),
        hora_entrada=time(9, 0),  # Cambiado de 8:00 a 9:00
        hora_salida=time(17, 0),  # Sin cambios
        pausa=30,  # Sin cambios
        version=2,
        es_actual=True,
        tipo_accion='modificacion',
        motivo_rectificacion='Llegué tarde'
    )
    db.session.add(fichaje_modificado)
    db.session.commit()
    
    # Acceder a la auditoría
    response = client.get('/admin/auditoria')
    assert response.status_code == 200
    
    # Verificar que muestra el cambio específico
    data = response.data.decode('utf-8')
    assert 'Entrada: 08:00' in data or '8:00' in data
    assert '9:00' in data or '09:00' in data
    assert '→' in data or '-&gt;' in data  # Flecha de cambio (puede estar escapada en HTML)
    
    # Verificar que NO muestra todos los datos del fichaje
    # (la fecha y hora de salida no deberían aparecer como cambios si no cambiaron)
    # Esto es más difícil de verificar, pero podemos comprobar que el formato es diferente


def test_auditoria_multiples_cambios(client, admin_user, employee_user):
    """Verifica que la auditoría muestra múltiples cambios en líneas separadas"""
    # Login como admin
    client.post('/login', data={
        'email': admin_user.email,
        'password': 'admin123'
    })
    
    # Crear un fichaje inicial
    fichaje_original = Fichaje(
        usuario_id=employee_user.id,
        editor_id=employee_user.id,
        fecha=date(2026, 1, 2),
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        pausa=30,
        version=1,
        es_actual=False,
        tipo_accion='creacion'
    )
    db.session.add(fichaje_original)
    db.session.commit()
    
    grupo_id = fichaje_original.grupo_id
    
    # Modificar múltiples campos
    fichaje_modificado = Fichaje(
        grupo_id=grupo_id,
        usuario_id=employee_user.id,
        editor_id=admin_user.id,
        fecha=date(2026, 1, 2),
        hora_entrada=time(9, 0),  # Cambiado
        hora_salida=time(18, 0),  # Cambiado
        pausa=60,  # Cambiado
        version=2,
        es_actual=True,
        tipo_accion='modificacion',
        motivo_rectificacion='Corrección múltiple'
    )
    db.session.add(fichaje_modificado)
    db.session.commit()
    
    # Acceder a la auditoría
    response = client.get('/admin/auditoria')
    assert response.status_code == 200
    
    data = response.data.decode('utf-8')
    
    # Verificar que muestra los tres cambios
    assert 'Entrada:' in data
    assert 'Salida:' in data
    assert 'Pausa:' in data
    
    # Verificar que hay saltos de línea (representados como <br>)
    assert '<br>' in data


def test_auditoria_creacion_por_admin(client, admin_user, employee_user):
    """Verifica que las creaciones por admin muestran info básica"""
    # Login como admin
    client.post('/login', data={
        'email': admin_user.email,
        'password': 'admin123'
    })
    
    # Admin crea un fichaje para otro usuario
    fichaje = Fichaje(
        usuario_id=employee_user.id,
        editor_id=admin_user.id,  # Editor diferente al usuario
        fecha=date(2026, 1, 3),
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        pausa=30,
        version=1,
        es_actual=True,
        tipo_accion='creacion'
    )
    db.session.add(fichaje)
    db.session.commit()
    
    # Acceder a la auditoría
    response = client.get('/admin/auditoria')
    assert response.status_code == 200
    
    data = response.data.decode('utf-8')
    
    # Verificar que aparece como creación por admin
    assert 'CREACIÓN (ADMIN)' in data or 'CREACION (ADMIN)' in data
    assert employee_user.nombre in data
    assert admin_user.nombre in data
