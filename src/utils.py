from datetime import timedelta, date
from src.models import Festivo, SolicitudVacaciones, SolicitudBaja
from sqlalchemy import or_, and_


def calcular_dias_laborables(fecha_inicio, fecha_fin):
    """
    Calcula los días laborables entre dos fechas.
    No cuenta fines de semana (sábados y domingos) ni festivos.
    
    Args:
        fecha_inicio: Fecha de inicio (date)
        fecha_fin: Fecha de fin (date)
    
    Returns:
        int: Número de días laborables
    """
    dias = 0
    fecha_actual = fecha_inicio
    festivos = set([f.fecha for f in Festivo.query.all()])
    
    while fecha_actual <= fecha_fin:
        # No contar fines de semana (5=sábado, 6=domingo)
        if fecha_actual.weekday() < 5 and fecha_actual not in festivos:
            dias += 1
        fecha_actual += timedelta(days=1)
    
    return dias

def es_festivo(fecha):
    """Comprueba si una fecha es fin de semana o festivo nacional."""
    # 1. Fin de semana (5=Sábado, 6=Domingo)
    if fecha.weekday() >= 5:
        return True
    
    # 2. Festivo en Base de Datos
    # Nota: Esto hace una query por día, para optimizar se podría cachear
    # o traer todos los festivos del rango en una sola query.
    # Para este volumen de datos, esto está bien.
    festivo = Festivo.query.filter_by(fecha=fecha).first()
    if festivo:
        return True
        
    return False

def calcular_dias_habiles(fecha_inicio, fecha_fin):
    """Devuelve el número de días laborables entre dos fechas (inclusive)."""
    dias_totales = (fecha_fin - fecha_inicio).days + 1
    dias_habiles = 0
    
    fecha_actual = fecha_inicio
    for _ in range(dias_totales):
        if not es_festivo(fecha_actual):
            dias_habiles += 1
        fecha_actual += timedelta(days=1)
        
    return dias_habiles

def verificar_solapamiento(usuario_id, fecha_inicio, fecha_fin, excluir_solicitud_id=None, tipo='vacaciones'):
    """
    Devuelve True si existe ALGUNA solicitud (Vacaciones o Baja) 
    que se solape con el rango dado.
    
    Lógica de solapamiento: (InicioA <= FinB) y (FinA >= InicioB)
    """
    
    # 1. Comprobar Vacaciones existentes (Pendientes o Aprobadas)
    query_vac = SolicitudVacaciones.query.filter(
        SolicitudVacaciones.usuario_id == usuario_id,
        SolicitudVacaciones.es_actual == True,
        SolicitudVacaciones.estado.in_(['pendiente', 'aprobada']),
        SolicitudVacaciones.fecha_inicio <= fecha_fin,
        SolicitudVacaciones.fecha_fin >= fecha_inicio
    )
    
    # Si estamos editando, excluimos la propia solicitud para que no choque consigo misma
    if tipo == 'vacaciones' and excluir_solicitud_id:
        query_vac = query_vac.filter(SolicitudVacaciones.id != excluir_solicitud_id)
        
    if query_vac.count() > 0:
        return True, "Ya tienes vacaciones solicitadas en estas fechas."

    # 2. Comprobar Bajas existentes (Pendientes o Aprobadas)
    query_baja = SolicitudBaja.query.filter(
        SolicitudBaja.usuario_id == usuario_id,
        SolicitudBaja.es_actual == True,
        SolicitudBaja.estado.in_(['pendiente', 'aprobada']),
        SolicitudBaja.fecha_inicio <= fecha_fin,
        SolicitudBaja.fecha_fin >= fecha_inicio
    )
    
    if tipo == 'baja' and excluir_solicitud_id:
        query_baja = query_baja.filter(SolicitudBaja.id != excluir_solicitud_id)
        
    if query_baja.count() > 0:
        return True, "Ya tienes una baja registrada en estas fechas."
        
    return False, None