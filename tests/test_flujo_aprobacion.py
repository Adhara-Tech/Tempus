
import pytest
from src import db
from src.models import Usuario, Aprobador, SolicitudVacaciones, SaldoVacaciones, UserKnownIP
from datetime import date, timedelta
from werkzeug.security import generate_password_hash

@pytest.fixture
def workflow_setup(test_app):
    """
    Setup specific for approval workflow:
    - Admin User (Approver)
    - Normal User (Requester)
    - Approver relationship: Admin -> Normal
    - Initial Vacation Balance for Normal User
    """
    # 1. Create Admin User
    admin = Usuario(
        nombre="Admin Manager",
        email="admin_flow@test.com",
        password=generate_password_hash("admin123"),
        rol="admin"
    )
    db.session.add(admin)
    
    # 2. Create Normal User
    employee = Usuario(
        nombre="Pepe Employee",
        email="pepe_flow@test.com",
        password=generate_password_hash("pepe123"),
        rol="empleado",
        dias_vacaciones=25
    )
    db.session.add(employee)
    db.session.add(employee)
    db.session.commit() # Commit to get IDs

    # Whitelist IP
    db.session.add(UserKnownIP(usuario_id=admin.id, ip_address='127.0.0.1'))
    db.session.add(UserKnownIP(usuario_id=employee.id, ip_address='127.0.0.1'))
    db.session.commit()

    # 3. Establish Approval Relationship (Admin approves Employee)
    relacion = Aprobador(usuario_id=employee.id, aprobador_id=admin.id)
    db.session.add(relacion)

    # 4. Create Vacation Balance for Current Year
    current_year = date.today().year
    saldo = SaldoVacaciones(
        usuario_id=employee.id,
        anio=current_year,
        dias_totales=25,
        dias_disfrutados=0
    )
    db.session.add(saldo)
    db.session.commit()

    return {
        'admin': admin,
        'employee': employee,
        'app': test_app
    }

def test_full_approval_flow(client, workflow_setup):
    """
    Test Case 1: Vacation Request -> Approval
    """
    admin = workflow_setup['admin']
    employee = workflow_setup['employee']
    
    # --- Step 1: Employee requests vacations ---
    # Login as Employee
    with client:
        client.post('/login', data={'email': employee.email, 'password': 'pepe123'}, follow_redirects=True)
        
        # Request dates
        start_date = date.today() + timedelta(days=10) # Future date
        end_date = start_date + timedelta(days=4) # 5 days total
        
        resp = client.post('/vacaciones/solicitar', data={
            'fecha_inicio': start_date.strftime('%Y-%m-%d'),
            'fecha_fin': end_date.strftime('%Y-%m-%d'),
            'motivo': 'Vacaciones de Verano',
            'usuario_id': employee.id
        }, follow_redirects=True)
        
        assert resp.status_code == 200
        assert b"Solicitud de vacaciones enviada correctamente" in resp.data

    # Verify request is created and pending
    solicitud = SolicitudVacaciones.query.filter_by(usuario_id=employee.id, motivo='Vacaciones de Verano').first()
    assert solicitud is not None
    assert solicitud.estado == 'pendiente'

    # --- Step 2: Admin approves the request ---
    # Login as Admin
    client.get('/logout', follow_redirects=True) 
    with client:
        client.post('/login', data={'email': admin.email, 'password': 'admin123'}, follow_redirects=True)
        
        # POST approval
        resp = client.post(f'/aprobaciones/vacaciones/{solicitud.id}/aprobar', follow_redirects=True)
        assert resp.status_code == 200
        # Check flash message
        assert b"aprobada" in resp.data.lower()

    # Verify status in DB
    db.session.refresh(solicitud)
    assert solicitud.estado == 'aprobada'

    # --- Step 3: Employee checks status ---
    client.get('/logout', follow_redirects=True)
    with client:
        client.post('/login', data={'email': employee.email, 'password': 'pepe123'}, follow_redirects=True)
        resp = client.get('/vacaciones')
        # In UI, status is Capitalized "Aprobada"
        assert b"Aprobada" in resp.data
        
        # Motivo and GroupID are NOT in the table. We check the date to confirm it's this request.
        # "10 days from now"
        expected_date = (date.today() + timedelta(days=10)).strftime('%d/%m/%Y').encode()
        assert expected_date in resp.data


def test_request_denial_flow(client, workflow_setup):
    """
    Test Case 2: Vacation Request -> Rejection
    """
    admin = workflow_setup['admin']
    employee = workflow_setup['employee']

    # --- Step 1: Employee requests ANOTHER vacation ---
    start_date = date.today() + timedelta(days=30)
    end_date = start_date + timedelta(days=2)
    s_date_str = start_date.strftime('%Y-%m-%d')
    e_date_str = end_date.strftime('%Y-%m-%d')
    
    with client:
        client.post('/login', data={'email': employee.email, 'password': 'pepe123'}, follow_redirects=True)
        client.post('/vacaciones/solicitar', data={
            'fecha_inicio': s_date_str,
            'fecha_fin': e_date_str,
            'motivo': 'Escapada Invierno'
        }, follow_redirects=True)

    solicitud = SolicitudVacaciones.query.filter_by(usuario_id=employee.id, motivo='Escapada Invierno').first()
    assert solicitud is not None
    assert solicitud.estado == 'pendiente'

    # --- Step 2: Admin DENIES the request ---
    client.get('/logout', follow_redirects=True)
    with client:
        client.post('/login', data={'email': admin.email, 'password': 'admin123'}, follow_redirects=True)
        resp = client.post(f'/aprobaciones/vacaciones/{solicitud.id}/rechazar', follow_redirects=True)
        assert resp.status_code == 200
        # flash message says "rechazada". Use lower() to be safe.
        if b"rechazada" not in resp.data.lower():
            print("DEBUG REJECTION HTML:", resp.data.decode())
        assert b"rechazada" in resp.data.lower()

    # Verify status DB
    db.session.refresh(solicitud)
    assert solicitud.estado == 'rechazada'

    # --- Step 3: Employee checks status ---
    client.get('/logout', follow_redirects=True)
    with client:
        client.post('/login', data={'email': employee.email, 'password': 'pepe123'}, follow_redirects=True)
        resp = client.get('/vacaciones')
        
        # Rejected requests are hidden in the main list.
        # Ensure it is NOT shown.
        # Check by Date (since Motivo is hidden)
        expected_date_str = start_date.strftime('%d/%m/%Y').encode()
        assert expected_date_str not in resp.data
        
        # Verify DB state
        assert solicitud.estado == 'rechazada'
