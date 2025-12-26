"""Tests for holiday impact on vacation day calculations."""
from datetime import date, datetime
from src.models import Festivo, SolicitudVacaciones, SaldoVacaciones
from src.utils import calcular_dias_habiles, invalidar_cache_festivos
from src import db


def test_deleted_holiday_returns_vacation_days(test_app, employee_user):
    """
    When a holiday is DELETED, vacation days that previously excluded that day
    should be recalculated (effectively returning a day).
    
    Scenario: User requested Mon-Fri (5 days). Wednesday was a holiday so only 4 days counted.
    If Wednesday holiday is deleted, a new request for the same period would count 5 days.
    """
    # Setup: Create a festivo for Wednesday
    festivo = Festivo(
        fecha=date(2025, 1, 8),  # Wednesday
        descripcion='Festivo a eliminar',
        activo=True
    )
    db.session.add(festivo)
    db.session.commit()
    
    # Clear cache
    invalidar_cache_festivos()
    
    # Calculate days with holiday (Mon-Fri, Wed is holiday = 4 days)
    inicio = date(2025, 1, 6)  # Monday
    fin = date(2025, 1, 10)    # Friday
    dias_con_festivo = calcular_dias_habiles(inicio, fin)
    assert dias_con_festivo == 4, "Should be 4 days when holiday exists"
    
    # Action: Delete the festivo
    db.session.delete(festivo)
    db.session.commit()
    
    # Clear cache after deletion
    invalidar_cache_festivos()
    
    # Recalculate: Should now be 5 days
    dias_sin_festivo = calcular_dias_habiles(inicio, fin)
    assert dias_sin_festivo == 5, "Should be 5 days after holiday deleted"


def test_disabled_holiday_does_not_affect_calculation(test_app):
    """
    When a holiday is DISABLED (archived), it should NOT count as a holiday.
    Disabled holidays are just hidden from the UI and don't affect calculations.
    
    This is CORRECT behavior:
    - Deleted holidays: return days (holiday no longer exists)
    - Disabled holidays: also return days (just invisible, doesn't affect calculation)
    """
    # Setup: Create an active festivo
    festivo = Festivo(
        fecha=date(2025, 2, 12),  # Wednesday
        descripcion='Festivo a deshabilitar',
        activo=True
    )
    db.session.add(festivo)
    db.session.commit()
    
    # Clear cache
    invalidar_cache_festivos()
    
    # Calculate days with active holiday
    inicio = date(2025, 2, 10)  # Monday
    fin = date(2025, 2, 14)     # Friday
    dias_activo = calcular_dias_habiles(inicio, fin)
    assert dias_activo == 4, "Should be 4 days when holiday is active"
    
    # Action: Disable (archive) the festivo
    festivo.activo = False
    db.session.commit()
    
    # Clear cache
    invalidar_cache_festivos()
    
    # Recalculate: Disabled holidays are treated as workdays (correct behavior)
    dias_deshabilitado = calcular_dias_habiles(inicio, fin)
    
    # CORRECT: Disabled holidays don't reduce vacation days
    assert dias_deshabilitado == 5, (
        "Disabled holidays should NOT reduce vacation days - they're just invisible"
    )


def test_only_active_festivos_affect_vacation_calculation(test_app):
    """Active festivos reduce vacation days, inactive ones don't."""
    # Create two festivos: one active, one inactive
    active = Festivo(fecha=date(2025, 3, 12), descripcion='Activo', activo=True)
    inactive = Festivo(fecha=date(2025, 3, 13), descripcion='Inactivo', activo=False)
    
    db.session.add_all([active, inactive])
    db.session.commit()
    
    # Clear cache
    invalidar_cache_festivos()
    
    # Mon-Fri: 5 workdays, minus 1 active festivo = 4 days
    inicio = date(2025, 3, 10)  # Monday
    fin = date(2025, 3, 14)     # Friday
    
    dias = calcular_dias_habiles(inicio, fin)
    # Only the active festivo reduces the count (Wednesday)
    # The inactive festivo on Thursday is treated as a workday
    assert dias == 4, "Only active festivo should reduce day count"
