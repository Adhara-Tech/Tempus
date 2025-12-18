from flask_mail import Mail, Message
from flask import current_app
from concurrent.futures import ThreadPoolExecutor
import os
import atexit

# Configuración Flask-Mail
mail = Mail()

# ✅ Executor global para gestionar threads de email
# max_workers=3 permite enviar hasta 3 emails simultáneos
email_executor = ThreadPoolExecutor(
    max_workers=3,
    thread_name_prefix='email_worker'
)

def init_mail(app):
    """Inicializa Flask-Mail con configuración de entorno"""
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@empresa.com')
    
    mail.init_app(app)
    
    # ✅ Registrar shutdown del executor al cerrar la app
    
    # ✅ También registrar con atexit como backup
    atexit.register(lambda: email_executor.shutdown(wait=False))
    
    # ✅ También registrar con atexit como backup
    atexit.register(lambda: email_executor.shutdown(wait=False))


def _send_async(app, msg):
    """
    Función interna que envía email en contexto de app.
    Se ejecuta en thread separado.
    """
    with app.app_context():
        try:
            mail.send(msg)
            print(f"✅ Email enviado: {msg.subject} -> {msg.recipients}")
        except Exception as e:
            print(f"❌ Error enviando email: {e}")
            # Opcional: Loggear a archivo o sistema de monitoring
            # import logging
            # logging.error(f"Email send failed: {e}", exc_info=True)


def enviar_email_solicitud(aprobador, solicitante, solicitud):
    """
    Envía email de notificación de nueva solicitud al aprobador.
    Usa ThreadPoolExecutor para envío asíncrono seguro.
    """
    msg = Message(
        subject=f'Nueva solicitud de vacaciones de {solicitante.nombre}',
        sender=current_app.config['MAIL_DEFAULT_SENDER'],
        recipients=[aprobador.email]
    )
    
    msg.body = f'''
Hola {aprobador.nombre},

{solicitante.nombre} ha solicitado vacaciones:

- Desde: {solicitud.fecha_inicio}
- Hasta: {solicitud.fecha_fin}
- Días solicitados: {solicitud.dias_solicitados}
- Motivo: {solicitud.motivo or 'No especificado'}

Por favor, revisa y responde a esta solicitud en el sistema.

Saludos,
Sistema de Gestión de Fichajes
    '''
    
    # ✅ Enviar usando el executor (gestiona threads automáticamente)
    app = current_app._get_current_object()
    future = email_executor.submit(_send_async, app, msg)
    
    # Opcional: añadir callback para manejar errores
    def handle_email_result(fut):
        try:
            fut.result()  # Lanza excepción si hubo error
        except Exception as e:
            print(f"⚠️ Email callback error: {e}")
    
    future.add_done_callback(handle_email_result)


def enviar_email_respuesta(usuario, solicitud):
    """
    Envía email de notificación de respuesta a solicitud.
    Usa ThreadPoolExecutor para envío asíncrono seguro.
    """
    estado_texto = "APROBADA" if solicitud.estado == 'aprobada' else "RECHAZADA"
    
    msg = Message(
        subject=f'Tu solicitud de vacaciones ha sido {estado_texto}',
        sender=current_app.config['MAIL_DEFAULT_SENDER'],
        recipients=[usuario.email]
    )
    
    msg.body = f'''
Hola {usuario.nombre},

Tu solicitud de vacaciones ha sido {estado_texto}.

Detalles de la solicitud:
- Desde: {solicitud.fecha_inicio}
- Hasta: {solicitud.fecha_fin}
- Días solicitados: {solicitud.dias_solicitados}
- Estado: {estado_texto}
- Respondida por: {solicitud.aprobador.nombre if solicitud.aprobador else 'Sistema'}
- Fecha de respuesta: {solicitud.fecha_respuesta}
{f"- Comentarios: {solicitud.comentarios}" if solicitud.comentarios else ""}

Saludos,
Sistema de Gestión de Fichajes
    '''
    
    # ✅ Enviar usando el executor
    app = current_app._get_current_object()
    future = email_executor.submit(_send_async, app, msg)
    
    def handle_email_result(fut):
        try:
            fut.result()
        except Exception as e:
            print(f"⚠️ Email callback error: {e}")
    
    future.add_done_callback(handle_email_result)

def enviar_email_otp(usuario, codigo):
    """
    Envía email con el código OTP para verificación de MFA.
    """
    msg = Message(
        subject='Código de verificación de seguridad',
        sender=current_app.config['MAIL_DEFAULT_SENDER'],
        recipients=[usuario.email]
    )
    
    msg.body = f'''
Hola {usuario.nombre},

Se ha detectado un inicio de sesión desde una ubicación o dispositivo nuevo.
Por favor, utiliza el siguiente código para verificar tu identidad:

{codigo}

Este código expira en 10 minutos.
Si no has sido tú, por favor contacta con el administrador.

Saludos,
Sistema de Gestión de Fichajes
    '''
    
    app = current_app._get_current_object()
    future = email_executor.submit(_send_async, app, msg)
    
    def handle_email_result(fut):
        try:
            fut.result()
        except Exception as e:
            print(f"⚠️ Email OTP callback error: {e}")
    
    future.add_done_callback(handle_email_result)