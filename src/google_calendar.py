"""
Integración con Google Calendar usando tokens de Flask-Dance
"""
import os
import json
from datetime import timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def get_calendar_service(usuario):
    """
    Crea un servicio de Calendar API usando el token del usuario.
    
    Args:
        usuario: Objeto Usuario con google_token guardado
    
    Returns:
        Resource object de Calendar API o None si no tiene token
    """
    if not usuario.google_token or not usuario.google_calendar_enabled:
        return None
    
    try:
        token_data = json.loads(usuario.google_token)
        
        # Crear credenciales desde el token guardado
        credentials = Credentials(
            token=token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ.get('GOOGLE_OAUTH_CLIENT_ID'),
            client_secret=os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET'),
            scopes=['https://www.googleapis.com/auth/calendar.events']
        )
        
        # ✅ Refresh automático si expiró
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request
            credentials.refresh(Request())
            
            # Guardar nuevo token actualizado
            from src import db
            usuario.google_token = json.dumps({
                'access_token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            })
            db.session.commit()
            print(f"🔄 Token refrescado para {usuario.nombre}")
        
        # Construir servicio de Calendar
        service = build('calendar', 'v3', credentials=credentials)
        return service
        
    except Exception as e:
        print(f"❌ Error creando servicio de Calendar para {usuario.nombre}: {e}")
        return None


def crear_evento_vacaciones(solicitud):
    """
    Crea un evento en Google Calendar para vacaciones aprobadas
    
    Args:
        solicitud: Objeto SolicitudVacaciones aprobada
    
    Returns:
        str: ID del evento creado o None si falla
    """
    service = get_calendar_service(solicitud.usuario)
    
    if not service:
        print(f"⏭️ Usuario {solicitud.usuario.nombre} no tiene Calendar habilitado")
        return None
    
    try:
        evento = {
            'summary': '🏖️ Vacaciones',
            'description': (
                f'Vacaciones aprobadas\n'
                f'Empleado: {solicitud.usuario.nombre}\n'
                f'Email: {solicitud.usuario.email}\n'
                f'Días: {solicitud.dias_solicitados}\n'
                f'Motivo: {solicitud.motivo or "No especificado"}'
            ),
            'start': {
                'date': solicitud.fecha_inicio.isoformat(),
                'timeZone': 'Europe/Madrid',
            },
            'end': {
                # Google Calendar: fecha fin es exclusiva, sumamos 1 día
                'date': (solicitud.fecha_fin + timedelta(days=1)).isoformat(),
                'timeZone': 'Europe/Madrid',
            },
            'colorId': '10',  # Verde para vacaciones
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 24 * 60},  # 1 día antes
                ],
            },
        }
        
        evento_creado = service.events().insert(
            calendarId='primary',
            body=evento
        ).execute()
        
        print(f"✅ Evento de vacaciones creado: {evento_creado.get('htmlLink')}")
        return evento_creado.get('id')
        
    except HttpError as error:
        print(f"❌ Error HTTP al crear evento de vacaciones: {error}")
        return None
    except Exception as error:
        print(f"❌ Error al crear evento de vacaciones: {error}")
        return None


def crear_evento_baja(solicitud):
    """
    Crea un evento en Google Calendar para baja aprobada
    
    Args:
        solicitud: Objeto SolicitudBaja aprobada
    
    Returns:
        str: ID del evento creado o None si falla
    """
    service = get_calendar_service(solicitud.usuario)
    
    if not service:
        print(f"⏭️ Usuario {solicitud.usuario.nombre} no tiene Calendar habilitado")
        return None
    
    try:
        tipo_nombre = solicitud.tipo_ausencia.nombre if solicitud.tipo_ausencia else 'Ausencia'
        
        evento = {
            'summary': f'🏥 {tipo_nombre}',
            'description': (
                f'Tipo: {tipo_nombre}\n'
                f'Empleado: {solicitud.usuario.nombre}\n'
                f'Email: {solicitud.usuario.email}\n'
                f'Días: {solicitud.dias_solicitados}\n'
                f'Motivo: {solicitud.motivo}'
            ),
            'start': {
                'date': solicitud.fecha_inicio.isoformat(),
                'timeZone': 'Europe/Madrid',
            },
            'end': {
                'date': (solicitud.fecha_fin + timedelta(days=1)).isoformat(),
                'timeZone': 'Europe/Madrid',
            },
            'colorId': '11',  # Rojo para bajas
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 24 * 60},
                ],
            },
        }
        
        evento_creado = service.events().insert(
            calendarId='primary',
            body=evento
        ).execute()
        
        print(f"✅ Evento de baja creado: {evento_creado.get('htmlLink')}")
        return evento_creado.get('id')
        
    except HttpError as error:
        print(f"❌ Error HTTP al crear evento de baja: {error}")
        return None
    except Exception as error:
        print(f"❌ Error al crear evento de baja: {error}")
        return None


def eliminar_evento(usuario, event_id):
    """
    Elimina un evento del calendario
    
    Args:
        usuario: Objeto Usuario
        event_id: ID del evento en Google Calendar
    
    Returns:
        bool: True si se eliminó correctamente
    """
    service = get_calendar_service(usuario)
    
    if not service or not event_id:
        return False
    
    try:
        service.events().delete(
            calendarId='primary',
            eventId=event_id
        ).execute()
        
        print(f"✅ Evento eliminado: {event_id}")
        return True
        
    except HttpError as error:
        print(f"❌ Error HTTP al eliminar evento: {error}")
        return False
    except Exception as error:
        print(f"❌ Error al eliminar evento: {error}")
        return False


def actualizar_evento(usuario, event_id, solicitud, tipo='vacaciones'):
    """
    Actualiza un evento existente
    
    Args:
        usuario: Objeto Usuario
        event_id: ID del evento en Google Calendar
        solicitud: Objeto SolicitudVacaciones o SolicitudBaja
        tipo: 'vacaciones' o 'baja'
    
    Returns:
        bool: True si se actualizó correctamente
    """
    service = get_calendar_service(usuario)
    
    if not service or not event_id:
        return False
    
    try:
        # Obtener el evento actual
        evento = service.events().get(
            calendarId='primary',
            eventId=event_id
        ).execute()
        
        # Actualizar campos
        emoji = '🏖️' if tipo == 'vacaciones' else '🏥'
        tipo_texto = 'Vacaciones' if tipo == 'vacaciones' else (
            solicitud.tipo_ausencia.nombre if solicitud.tipo_ausencia else 'Ausencia'
        )
        
        evento['summary'] = f'{emoji} {tipo_texto}'
        evento['start']['date'] = solicitud.fecha_inicio.isoformat()
        evento['end']['date'] = (solicitud.fecha_fin + timedelta(days=1)).isoformat()
        
        # Enviar actualización
        service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=evento
        ).execute()
        
        print(f"✅ Evento actualizado: {event_id}")
        return True
        
    except HttpError as error:
        print(f"❌ Error HTTP al actualizar evento: {error}")
        return False
    except Exception as error:
        print(f"❌ Error al actualizar evento: {error}")
        return False