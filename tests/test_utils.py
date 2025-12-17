from datetime import date
from src.utils import calcular_dias_habiles, verificar_solapamiento
from src.models import Festivo, SolicitudVacaciones
from src import db

def test_calcular_dias_habiles_simple(test_app):
    """Semana normal lunes-viernes."""
    inicio = date(2023, 1, 2) # Lunes
    fin = date(2023, 1, 6)    # Viernes
    assert calcular_dias_habiles(inicio, fin) == 5

def test_calcular_dias_con_finde(test_app):
    """Semana completa (7 días naturales -> 5 hábiles)."""
    inicio = date(2023, 1, 2) # Lunes
    fin = date(2023, 1, 8)    # Domingo
    assert calcular_dias_habiles(inicio, fin) == 5

def test_calcular_dias_con_festivo(test_app):
    """Semana con un festivo entre medias."""
    from src.utils import invalidar_cache_festivos, _get_festivos_cached
    
    # Crear festivo el Miércoles (must be activo=True to be counted)
    festivo = Festivo(fecha=date(2023, 1, 4), descripcion="Festivo Test", activo=True)
    db.session.add(festivo)
    db.session.commit()
    
    # Invalidate festivos cache so the new festivo is picked up
    # Note: utils.py has duplicate @lru_cache decorators, so we need to clear both
    invalidar_cache_festivos()  # Clears outer cache
    if hasattr(_get_festivos_cached, '__wrapped__'):
        _get_festivos_cached.__wrapped__.cache_clear()  # Clears inner cache
    
    inicio = date(2023, 1, 2) # Lunes
    fin = date(2023, 1, 6)    # Viernes
    # L(1) M(1) X(0) J(1) V(1) = 4 días
    assert calcular_dias_habiles(inicio, fin) == 4

def test_verificar_solapamiento_limpio(test_app, employee_user):
    """No hay solapamiento si no hay solicitudes."""
    hay_solape, msg = verificar_solapamiento(employee_user.id, date(2023, 1, 1), date(2023, 1, 5))
    assert hay_solape is False
    assert msg is None

def test_verificar_solapamiento_detectado(test_app, employee_user):
    """Detectar choque con solicitud existente."""
    # 1. Crear solicitud base (1-5 Enero)
    sol = SolicitudVacaciones(
        usuario_id=employee_user.id,
        fecha_inicio=date(2023, 1, 1),
        fecha_fin=date(2023, 1, 5),
        dias_solicitados=5,
        motivo="Test",
        estado="pendiente"
    )
    db.session.add(sol)
    db.session.commit()
    
    # 2. Probar Overlap Total (mismas fechas)
    hay_solape, _ = verificar_solapamiento(employee_user.id, date(2023, 1, 1), date(2023, 1, 5))
    assert hay_solape is True
    
    # 3. Probar Overlap Parcial (3-7 Enero)
    hay_solape, _ = verificar_solapamiento(employee_user.id, date(2023, 1, 3), date(2023, 1, 7))
    assert hay_solape is True
    
    # 4. Probar Sin Overlap (6-10 Enero)
    hay_solape, _ = verificar_solapamiento(employee_user.id, date(2023, 1, 6), date(2023, 1, 10))
    assert hay_solape is False