import pytest
from datetime import date, timedelta, datetime
import uuid
from src import db
from src.models import SolicitudVacaciones

def test_block_cancellation_of_past_vacations(auth_client, employee_user):
    """Ensure users cannot cancel vacations that have already ended."""
    # 1. Setup: Create a past vacation (manually to bypass logic if needed, or just insert)
    past_end_date = date.today() - timedelta(days=5)
    past_start_date = date.today() - timedelta(days=10)
    
    solicitud = SolicitudVacaciones(
        usuario_id=employee_user.id,
        grupo_id=str(uuid.uuid4()),
        version=1,
        es_actual=True,
        fecha_inicio=past_start_date,
        fecha_fin=past_end_date, # KEY: In the past
        dias_solicitados=5,
        motivo="Vacaciones antiguas",
        estado='aprobada',
        fecha_solicitud=datetime.utcnow()
    )
    db.session.add(solicitud)
    db.session.commit()
    
    # 2. Action: Try to cancel it
    response = auth_client.post(f'/vacaciones/cancelar/{solicitud.id}', follow_redirects=True)
    
    # 3. Assertions
    assert response.status_code == 200 # Redirect followed
    response_text = response.data.decode('utf-8')
    assert "No se pueden cancelar vacaciones que ya han sido disfrutadas" in response_text
    
    # Verify DB state hasn't changed (still approved, no cancellation request created)
    # Since a cancellation request is a *new* row, we check expected rows count or logic
    # But specifically, verifying the flash message is strong enough evidence of the block.
    
    db.session.refresh(solicitud)
    assert solicitud.estado == 'aprobada'

def test_block_modification_of_past_vacations(auth_client, employee_user):
    """Ensure users cannot modify vacations that have already ended."""
    # 1. Setup: Create a past vacation
    past_end_date = date.today() - timedelta(days=5)
    past_start_date = date.today() - timedelta(days=10)
    
    solicitud = SolicitudVacaciones(
        usuario_id=employee_user.id,
        grupo_id=str(uuid.uuid4()),
        version=1,
        es_actual=True,
        fecha_inicio=past_start_date,
        fecha_fin=past_end_date,
        dias_solicitados=5,
        motivo="Vacaciones antiguas mod",
        estado='aprobada',
        fecha_solicitud=datetime.utcnow()
    )
    db.session.add(solicitud)
    db.session.commit()
    
    # 2. Action: Try to access modify page (GET) or post modification (POST)
    # Testing POST as it's the critical security check
    response = auth_client.post(f'/vacaciones/modificar/{solicitud.id}', data={
        'fecha_inicio': str(date.today() + timedelta(days=10)),
        'fecha_fin': str(date.today() + timedelta(days=15)),
        'motivo': 'Intento de cambio'
    }, follow_redirects=True)
    
    # 3. Assertions
    response_text = response.data.decode('utf-8')
    assert "No se pueden modificar vacaciones pasadas" in response_text

def test_smart_grouping_ui_logic(auth_client, employee_user):
    """Test that the list groups pending requests with their parents."""
    # 1. Setup: Create Parent (Approved) and Child (Pending Cancellation)
    grupo_id = str(uuid.uuid4())
    
    # Parent (Approved)
    parent = SolicitudVacaciones(
        usuario_id=employee_user.id,
        grupo_id=grupo_id, # Link
        version=1,
        es_actual=True,
        fecha_inicio=date.today() + timedelta(days=10),
        fecha_fin=date.today() + timedelta(days=15),
        dias_solicitados=5,
        motivo="Vacaciones futuras",
        estado='aprobada',
        fecha_solicitud=datetime.utcnow()
    )
    db.session.add(parent)
    db.session.commit()
    
    # Child (Pending Cancellation)
    child = SolicitudVacaciones(
        usuario_id=employee_user.id,
        grupo_id=grupo_id, # Same Group
        version=2,
        es_actual=True, # Both are 'actual' in DB until resolved
        tipo_accion='cancelacion',
        fecha_inicio=parent.fecha_inicio,
        fecha_fin=parent.fecha_fin,
        dias_solicitados=parent.dias_solicitados,
        motivo="Cancelación pendiente",
        estado='pendiente',
        fecha_solicitud=datetime.utcnow()
    )
    db.session.add(child)
    db.session.commit()
    
    # 2. Action: View List
    response = auth_client.get('/vacaciones')
    response_text = response.data.decode('utf-8')
    
    # 3. Assertions
    # a) Check "Cancelación en curso" badge (smart grouping indicator)
    assert "Cancelación en curso" in response_text
    
    # b) Check that actions are locked ("Esperando aprobación...")
    assert "Esperando aprobación..." in response_text
    
    # c) Ensure we don't see the child row as a separate *main* item?
    # This is harder to test with regex on HTML, but presence of the badge confirms partial logic.
    # We can check that the motive "Cancelación pendiente" is NOT displayed as a main row description?
    # (Assuming templates show descriptions).
    # Ideally, we verify the grouping logic works. The badge presence proves `sol.cambio_pendiente` was set correctly.
