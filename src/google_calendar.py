"""
Integración con Google Calendar COMPARTIDO.
Todos los eventos van a un calendario único que todos pueden ver.
"""
import os
from datetime import timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def get_calendar_service():
    """
    Crea un servicio de Calendar API usando Service Account o token de admin.
    
    Returns:
        Resource object de Calendar API o None si falla
    
    Prioridad:
        1. Service Account (producción)
        2. Token OAuth de admin (desarrollo)
    """
    try:
        # OPCIÓN A: Service Account (Recomendado)
        service_account_file = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE')
        
        if service_account_file and os.path.exists(service_account_file):
            print("🔑 Usando Service Account para Calendar")
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=['https://www.googleapis.com/auth/calendar.events']
            )
            service = build('calendar', 'v3', credentials=credentials)
            return service
        
        # OPCIÓN B: Token OAuth (Desarrollo)
        token_file = 'token.pickle'
        if os.path.exists(token_file):
            print("🔑 Usando Token OAuth para Calendar")
            import pickle
            with open(token_file, 'rb') as token:
                creds = pickle.load(token)
            
            service = build('calendar', 'v3', credentials=creds)
            return service
        
        # Si no hay ninguna credencial
        print("⏭️ Calendar no configurado, saltando sincronización")
        print("   Opciones:")
        print("   1. Configura GOOGLE_SERVICE_ACCOUNT_FILE en .env")
        print("   2. Ejecuta scripts/authenticate_calendar.py")
        return None
        
    except Exception as e:
        print(f"❌ Error creando servicio de Calendar: {e}")
        return None


def crear_evento_vacaciones(solicitud):
    """
    Crea un evento en el calendario COMPARTIDO para vacaciones aprobadas.
    
    Args:
        solicitud: Objeto SolicitudVacaciones con estado='aprobada'
    
    Returns:
        str: ID del evento creado o None si falla
    
    Uso:
        event_id = crear_evento_vacaciones(solicitud)
        if event_id:
            solicitud.google_event_id = event_id
            db.session.commit()
    """
    service = get_calendar_service()
    
    if not service:
        return None
    
    calendar_id = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')
    
    try:
        evento = {
            'summary': f'🏖️ {solicitud.usuario.nombre} - Vacaciones',
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
            },
        }
        
        evento_creado = service.events().insert(
            calendarId=calendar_id,
            body=evento
        ).execute()
        
        print(f"✅ Evento de vacaciones creado en calendar compartido: {evento_creado.get('htmlLink')}")
        print(f"   Usuario: {solicitud.usuario.nombre}")
        return evento_creado.get('id')
        
    except HttpError as error:
        print(f"❌ Error HTTP al crear evento de vacaciones: {error}")
        return None
    except Exception as error:
        print(f"❌ Error al crear evento de vacaciones: {error}")
        return None


def crear_evento_baja(solicitud):
    """
    Crea un evento en el calendario COMPARTIDO para baja/ausencia aprobada.
    
    Args:
        solicitud: Objeto SolicitudBaja con estado='aprobada'
    
    Returns:
        str: ID del evento creado o None si falla
    """
    service = get_calendar_service()
    
    if not service:
        return None
    
    calendar_id = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')
    
    try:
        tipo_nombre = solicitud.tipo_ausencia.nombre if solicitud.tipo_ausencia else 'Ausencia'
        
        evento = {
            'summary': f'🏥 {solicitud.usuario.nombre} - {tipo_nombre}',
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
            },
        }
        
        evento_creado = service.events().insert(
            calendarId=calendar_id,
            body=evento
        ).execute()
        
        print(f"✅ Evento de baja creado en calendar compartido: {evento_creado.get('htmlLink')}")
        print(f"   Usuario: {solicitud.usuario.nombre}, Tipo: {tipo_nombre}")
        return evento_creado.get('id')
        
    except HttpError as error:
        print(f"❌ Error HTTP al crear evento de baja: {error}")
        return None
    except Exception as error:
        print(f"❌ Error al crear evento de baja: {error}")
        return None


def eliminar_evento(event_id):
    """
    Elimina un evento del calendario compartido.
    
    Args:
        event_id: ID del evento en Google Calendar
    
    Returns:
        bool: True si se eliminó correctamente, False si falló
    
    Uso:
        if solicitud.google_event_id:
            eliminar_evento(solicitud.google_event_id)
            solicitud.google_event_id = None
    """
    service = get_calendar_service()
    
    if not service or not event_id:
        return False
    
    calendar_id = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')
    
    try:
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()
        
        print(f"✅ Evento eliminado del calendar compartido: {event_id}")
        return True
        
    except HttpError as error:
        print(f"❌ Error HTTP al eliminar evento: {error}")
        return False
    except Exception as error:
        print(f"❌ Error al eliminar evento: {error}")
        return False


def actualizar_evento(event_id, solicitud, tipo='vacaciones'):
    """
    Actualiza un evento existente en el calendario compartido.
    
    Args:
        event_id: ID del evento en Google Calendar
        solicitud: Objeto SolicitudVacaciones o SolicitudBaja
        tipo: 'vacaciones' o 'baja'
    
    Returns:
        bool: True si se actualizó correctamente
    """
    service = get_calendar_service()
    
    if not service or not event_id:
        return False
    
    calendar_id = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')
    
    try:
        # Obtener el evento actual
        evento = service.events().get(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()
        
        # Actualizar campos
        emoji = '🏖️' if tipo == 'vacaciones' else '🏥'
        tipo_texto = 'Vacaciones' if tipo == 'vacaciones' else (
            solicitud.tipo_ausencia.nombre if solicitud.tipo_ausencia else 'Ausencia'
        )
        
        evento['summary'] = f'{emoji} {solicitud.usuario.nombre} - {tipo_texto}'
        evento['start']['date'] = solicitud.fecha_inicio.isoformat()
        evento['end']['date'] = (solicitud.fecha_fin + timedelta(days=1)).isoformat()
        
        # Enviar actualización
        service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=evento
        ).execute()
        
        print(f"✅ Evento actualizado en calendar compartido: {event_id}")
        return True
        
    except HttpError as error:
        print(f"❌ Error HTTP al actualizar evento: {error}")
        return False
    except Exception as error:
        print(f"❌ Error al actualizar evento: {error}")
        return False