# Sistema de Fichaje y Gestión de Ausencias

Aplicación completa desarrollada con Flask para gestionar fichajes de empleados, solicitudes de vacaciones y solicitudes de bajas médicas.
Versión actual: v0.0.1

## Características

- Sistema de fichaje (Entrada/Salida)
- Solicitud y aprobación de **Vacaciones** (descuentan días)
- Solicitud y aprobación de **Bajas** (no descuentan días)
- Sistema de roles (usuario, aprobador, admin)
- Notificaciones por email (simuladas en desarrollo)
- Cronograma de ausencias (Vacaciones y Bajas)
- Resúmenes de horas trabajadas (diario/semanal)
- Panel de administración completo (Gestión de usuarios, festivos, aprobadores)
- Cálculo automático de días laborables (descuenta festivos y fines de semana)

## Requisitos

- Python 3.8+
- Flask
- Flask-SQLAlchemy
- Flask-Login
- Flask-Mail
- Flask-Dance
- Gunicorn (para producción)

## Instalación

### 1. Desarrollo Local

1.  Crear y activar un entorno virtual:
    ```bash
    python -m venv venv
    source venv/bin/activate  # En Windows: venv\Scripts\activate
    ```

2.  Instalar dependencias:
    ```bash
    pip install -r requirements.txt
    ```

3.  Ejecutar la aplicación:
    ```bash
    flask run --debug
    ```
    La aplicación estará disponible en `http://localhost:5000`.

### 2. Ejecutar con Docker (Producción)

1.  Asegúrate de tener Docker y Docker Compose instalados.

2.  Construye y levanta el contenedor:
    ```bash
    docker-compose up --build
    ```

3.  La aplicación estará disponible en `http://localhost:5000`. La base de datos (`fichaje.db`) se guardará en un volumen de Docker llamado `fichador_web_db_data` para persistir los datos.

## Usuario por Defecto

Al iniciar por primera vez, se crea automáticamente un usuario administrador:

-   **Email:** `admin@example.com`
-   **Contraseña:** `admin123`

### 3. Configuración de Google OAuth

1. Configura las credenciales de Google OAuth en el archivo `.env`:
    ```bash
    GOOGLE_CLIENT_ID=your_client_id
    GOOGLE_CLIENT_SECRET=your_client_secret
    ```

2. En la consola de Google Cloud Platform (https://console.cloud.google.com/):
    - Ve a "APIs & Services" → "Credentials"
    - Ve a tu OAuth 2.0 Client ID
    - En "Authorized redirect URIs", añade:
    http://127.0.0.1:5000/login/google/authorized
    http://localhost:5000/login/google/authorized
    - Guarda los cambios

3. Reinicia tu servidor Flask después de hacer cambios en `.env`
