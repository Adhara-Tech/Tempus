"""
Script para autenticar con Google Calendar usando OAuth.
Solo necesario si NO usas Service Account.

Uso:
    python scripts/authenticate_calendar.py
    
Esto genera token.pickle que se usa en desarrollo.
"""
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/calendar.events']


def main():
    """Ejecuta el flujo de autenticación OAuth"""
    creds = None
    
    # Cargar credenciales existentes
    if os.path.exists('token.pickle'):
        print("🔄 Token existente encontrado")
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # Si no hay credenciales válidas, pedir login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refrescando token expirado...")
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("❌ Error: No se encontró credentials.json")
                print("   Descárgalo desde Google Cloud Console:")
                print("   https://console.cloud.google.com/apis/credentials")
                return
            
            print("🔐 Iniciando flujo de autenticación...")
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Guardar credenciales
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
        
        print("✅ Token guardado en token.pickle")
    
    print("✅ Autenticación exitosa")
    print("   Ahora puedes usar la app con Calendar")


if __name__ == '__main__':
    main()
