import pytest
from src.models import SaldoVacaciones, SolicitudVacaciones, Usuario
from src import db
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime

def test_saldo_vacaciones_creation(test_app, employee_user):
    """Test creating a SaldoVacaciones entry."""
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=2024,
        dias_totales=25,
        dias_disfrutados=0
    )
    db.session.add(saldo)
    db.session.commit()

    assert saldo.id is not None
    assert saldo.usuario_id == employee_user.id
    assert saldo.anio == 2024

def test_saldo_vacaciones_unique_constraint(test_app, employee_user):
    """Test that duplicate SaldoVacaciones for same user/year fails."""
    saldo1 = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=2025,
        dias_totales=25
    )
    db.session.add(saldo1)
    db.session.commit()

    saldo2 = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=2025,
        dias_totales=30
    )
    db.session.add(saldo2)
    
    with pytest.raises(IntegrityError):
        db.session.commit()
    
    db.session.rollback()

def test_solicitud_vacaciones_audit_fields(test_app, employee_user, admin_user):
    """Test new fields in SolicitudVacaciones."""
    solicitud = SolicitudVacaciones(
        usuario_id=employee_user.id,
        fecha_inicio=date(2024, 7, 1),
        fecha_fin=date(2024, 7, 15),
        dias_solicitados=10,
        motivo="Vacaciones verano",
        estado="pendiente",
        tipo_accion="creacion",
        editor_id=admin_user.id
    )
    db.session.add(solicitud)
    db.session.commit()

    assert solicitud.tipo_accion == "creacion"
    assert solicitud.editor_id == admin_user.id
    assert solicitud.editor == admin_user

def test_dias_vacaciones_disponibles_new_logic(test_app, employee_user):
    """Test the new dias_vacaciones_disponibles logic."""
    # Case 1: No Saldo entry
    assert employee_user.dias_vacaciones_disponibles(anio=2024) == 0

    # Case 2: Saldo entry exists
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=2024,
        dias_totales=25,
        dias_disfrutados=5
    )
    db.session.add(saldo)
    db.session.commit()

    # Should be 25 - 5 = 20
    assert employee_user.dias_vacaciones_disponibles(anio=2024) == 20
    
    # Case 3: Default year (should be current year)
    current_year = datetime.now().year
    saldo_curr = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=22,
        dias_disfrutados=2
    )
    db.session.add(saldo_curr)
    db.session.commit()
    
    assert employee_user.dias_vacaciones_disponibles() == 20
