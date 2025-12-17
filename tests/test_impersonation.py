"""Tests for admin impersonation (creating vacations/bajas on behalf of users)."""
from datetime import date, datetime
from src.models import SolicitudVacaciones, SaldoVacaciones
from src import db


def test_admin_impersonation_vacaciones(auth_admin_client, employee_user):
    """Admin creates vacation on behalf of employee - should be auto-approved."""
    current_year = datetime.now().year
    
    # Create SaldoVacaciones for employee
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=25,
        dias_disfrutados=0
    )
    db.session.add(saldo)
    db.session.commit()
    
    # Admin submits vacation for employee
    response = auth_admin_client.post('/vacaciones/solicitar', data={
        'fecha_inicio': f'{current_year}-07-01',
        'fecha_fin': f'{current_year}-07-05',
        'motivo': 'Vacaciones creadas por admin',
        'usuario_id': str(employee_user.id)  # Impersonation field
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    # Verify the vacation was created and auto-approved
    solicitud = SolicitudVacaciones.query.filter_by(
        usuario_id=employee_user.id,
        motivo='Vacaciones creadas por admin'
    ).first()
    
    assert solicitud is not None
    assert solicitud.estado == 'aprobada'  # Auto-approved when admin creates
    assert solicitud.aprobador_id is not None  # Should have the admin as approver


def test_employee_cannot_impersonate(auth_client, admin_user):
    """Regular employee cannot create vacations for other users."""
    current_year = datetime.now().year
    
    # Employee tries to create vacation for admin (should be ignored)
    # The usuario_id field should be ignored for non-admin users
    response = auth_client.post('/vacaciones/solicitar', data={
        'fecha_inicio': f'{current_year}-08-01',
        'fecha_fin': f'{current_year}-08-05',
        'motivo': 'Attempted impersonation',
        'usuario_id': str(admin_user.id)  # Should be ignored
    }, follow_redirects=True)
    
    # The request should still be processed for the current user (employee),
    # not for the admin. Since employee has no SaldoVacaciones, it might succeed
    # with advance warning or create for their own account.
    # Key check: no vacation should be created for admin_user
    admin_vacation = SolicitudVacaciones.query.filter_by(
        usuario_id=admin_user.id,
        motivo='Attempted impersonation'
    ).first()
    
    assert admin_vacation is None  # Impersonation blocked
