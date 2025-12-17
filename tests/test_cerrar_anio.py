"""Tests for year closing (cerrar-anio) CLI command."""
import pytest
from datetime import date, datetime
from click.testing import CliRunner
from src.cli import cerrar_anio_command
from src.models import Usuario, SaldoVacaciones, Festivo
from src import db


def test_cerrar_anio_carryover_basic(test_app, runner, employee_user):
    """Test that vacation days carry over correctly when closing a year."""
    current_year = datetime.now().year
    
    # Setup: Create saldo for current year with leftover days
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=25,
        dias_disfrutados=10  # Used 10, so 15 remaining
    )
    db.session.add(saldo)
    db.session.commit()
    
    # Action: Close the year with max carryover of 10
    result = runner.invoke(args=[
        'cerrar-anio',
        str(current_year),
        '--max-carryover', '10',
        '--gestionar-festivos', 'mantener',
        '--force'
    ])
    
    assert result.exit_code == 0
    assert "PROCESO COMPLETADO" in result.output
    
    # Verify: New year saldo created with capped carryover
    new_saldo = SaldoVacaciones.query.filter_by(
        usuario_id=employee_user.id,
        anio=current_year + 1
    ).first()
    
    assert new_saldo is not None
    # Employee has 25 base days + 10 carryover (capped from 15)
    assert new_saldo.dias_totales == 25 + 10
    assert new_saldo.dias_carryover == 10


def test_cerrar_anio_carryover_with_debt(test_app, runner, employee_user):
    """Test that vacation debt (negative balance) carries over fully."""
    current_year = datetime.now().year
    
    # Setup: Create saldo with more used than available (debt)
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=25,
        dias_disfrutados=30  # Used 30, so -5 balance
    )
    db.session.add(saldo)
    db.session.commit()
    
    # Action: Close year
    result = runner.invoke(args=[
        'cerrar-anio',
        str(current_year),
        '--max-carryover', '10',
        '--gestionar-festivos', 'mantener',
        '--force'
    ])
    
    assert result.exit_code == 0
    
    # Verify: Debt carries over fully (not capped)
    new_saldo = SaldoVacaciones.query.filter_by(
        usuario_id=employee_user.id,
        anio=current_year + 1
    ).first()
    
    assert new_saldo is not None
    # 25 base - 5 debt = 20 total
    assert new_saldo.dias_totales == 25 + (-5)  # = 20
    assert new_saldo.dias_carryover == -5


def test_cerrar_anio_archives_old_festivos(test_app, runner, employee_user):
    """Test that closing year archives festivos from previous years."""
    current_year = datetime.now().year
    
    # Setup: Create festivos for different years
    # Festivo from 2 years ago (should be archived with default settings)
    old_festivo = Festivo(
        fecha=date(current_year - 2, 12, 25),
        descripcion='Navidad antigua',
        activo=True
    )
    # Festivo from last year (should be archived)
    last_year_festivo = Festivo(
        fecha=date(current_year - 1, 1, 6),
        descripcion='Reyes del año pasado',
        activo=True
    )
    # Festivo from current year (should NOT be archived with default anios_antiguedad=1)
    current_festivo = Festivo(
        fecha=date(current_year, 12, 25),
        descripcion='Navidad actual',
        activo=True
    )
    
    db.session.add_all([old_festivo, last_year_festivo, current_festivo])
    
    # Create minimum saldo to allow year closing
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=25,
        dias_disfrutados=0
    )
    db.session.add(saldo)
    db.session.commit()
    
    # Action: Close year with archiving
    result = runner.invoke(args=[
        'cerrar-anio',
        str(current_year),
        '--gestionar-festivos', 'archivar',
        '--anios-antiguedad', '1',
        '--force'
    ])
    
    assert result.exit_code == 0
    
    # Verify: With fixed logic, closing current_year archives festivos up to current_year
    # anio_limite = (current_year + 1) - 1 + 1 = current_year + 1
    # So festivos < (current_year+1)-01-01 are archived = ALL these festivos
    db.session.refresh(old_festivo)
    db.session.refresh(last_year_festivo)
    db.session.refresh(current_festivo)
    
    assert old_festivo.activo is False, "Old festivo should be archived"
    assert last_year_festivo.activo is False, "Last year festivo should be archived"
    assert current_festivo.activo is False, "Current year festivo should NOW be archived (fixed behavior)"


def test_cerrar_anio_deletes_old_festivos(test_app, runner, employee_user):
    """Test that closing year can delete festivos instead of archiving."""
    current_year = datetime.now().year
    
    # Setup: Create festivo from previous year
    old_festivo = Festivo(
        fecha=date(current_year - 1, 12, 25),
        descripcion='Navidad para eliminar',
        activo=True
    )
    db.session.add(old_festivo)
    
    saldo = SaldoVacaciones(
        usuario_id=employee_user.id,
        anio=current_year,
        dias_totales=25,
        dias_disfrutados=0
    )
    db.session.add(saldo)
    db.session.commit()
    old_festivo_id = old_festivo.id
    
    # Action: Close year with deletion
    result = runner.invoke(args=[
        'cerrar-anio',
        str(current_year),
        '--gestionar-festivos', 'eliminar',
        '--force'
    ])
    
    assert result.exit_code == 0
    
    # Verify: Old festivo deleted
    deleted = Festivo.query.get(old_festivo_id)
    assert deleted is None, "Festivo should be deleted"
