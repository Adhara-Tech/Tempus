from src.models import SolicitudVacaciones, SaldoVacaciones
from datetime import date, datetime
from src import db

def test_solicitar_vacaciones_ok(auth_client, employee_user):
    """Solicitud correcta dentro de saldo."""
    # Create SaldoVacaciones for the current year
    current_year = datetime.now().year
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=25,
        dias_disfrutados=0
    )
    db.session.add(saldo)
    db.session.commit()
    
    response = auth_client.post('/vacaciones/solicitar', data={
        'fecha_inicio': f'{current_year}-06-01',
        'fecha_fin': f'{current_year}-06-05',
        'motivo': 'Verano'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert "Solicitud de vacaciones enviada correctamente" in response.text
    
    solicitud = SolicitudVacaciones.query.filter_by(usuario_id=employee_user.id).first()
    assert solicitud is not None
    assert solicitud.estado == 'pendiente'

def test_solicitar_vacaciones_saldo_insuficiente(auth_client, employee_user):
    """Intentar pedir más días de los disponibles (excede límite de adelanto)."""
    current_year = datetime.now().year
    
    # Create SaldoVacaciones with low balance
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=5,  # Only 5 days total
        dias_disfrutados=0
    )
    db.session.add(saldo)
    
    # Also set user's max allowed advance to 5 days
    employee_user.dias_vacaciones = 5
    db.session.commit()

    # Request entire month (approx 22 business days - exceeds both balance AND advance limit)
    response = auth_client.post('/vacaciones/solicitar', data={
        'fecha_inicio': f'{current_year}-01-02',  # Start Monday
        'fecha_fin': f'{current_year}-01-31', 
        'motivo': 'Mes sabático'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # The error message for exceeding advance limit
    assert "Límite de adelanto excedido" in response.text
    
    # Verify no request was created
    assert SolicitudVacaciones.query.count() == 0

def test_solicitar_vacaciones_overlap_http(auth_client, employee_user):
    """El backend debe rechazar la petición si hay overlap."""
    # 1. Crear solicitud A manualmente (aprobada o pendiente)
    sol = SolicitudVacaciones(
        usuario_id=employee_user.id,
        fecha_inicio=date(2023, 1, 1),
        fecha_fin=date(2023, 1, 5),
        dias_solicitados=5,
        estado="aprobada",
        es_actual=True
    )
    db.session.add(sol)
    db.session.commit()
    
    # 2. Intentar pedir vacaciones que chocan (del 4 al 8)
    response = auth_client.post('/vacaciones/solicitar', data={
        'fecha_inicio': '2023-01-04',
        'fecha_fin': '2023-01-08',
        'motivo': 'Solape'
    }, follow_redirects=True)
    
    # Buscamos parte del mensaje de error definido en utils.py
    assert "Ya tienes vacaciones solicitadas" in response.text

def test_aprobacion_flujo(auth_approver_client, employee_user):
    """Un jefe aprueba la solicitud de su empleado."""
    # 1. Crear solicitud pendiente del empleado
    sol = SolicitudVacaciones(
        usuario_id=employee_user.id,
        fecha_inicio=date(2023, 2, 1),
        fecha_fin=date(2023, 2, 5),
        dias_solicitados=5,
        motivo="Pendiente de aprobar",
        estado="pendiente",
        es_actual=True
    )
    db.session.add(sol)
    db.session.commit()
    
    # 2. El jefe entra a la página de aprobaciones
    # Primero listamos para ver si la ve
    resp_list = auth_approver_client.get('/aprobaciones')
    assert resp_list.status_code == 200
    assert "Pendiente de aprobar" in resp_list.text
    
    # 3. Acción de aprobar
    resp_action = auth_approver_client.post(f'/aprobaciones/vacaciones/{sol.id}/aprobar', follow_redirects=True)
    assert resp_action.status_code == 200
    assert "aprobada" in resp_action.text
    
    # 4. Verificar DB
    db.session.refresh(sol)
    assert sol.estado == 'aprobada'