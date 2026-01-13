# Configuración de Google Calendar Compartido

Este documento explica cómo configurar Google Calendar para sincronizar automáticamente las vacaciones y bajas aprobadas a un calendario compartido visible por todos los empleados.

## Opción A: Service Account (Recomendado para Producción)

### Paso 1: Crear Service Account

1. Ve a https://console.cloud.google.com/iam-admin/serviceaccounts
2. Click en **"CREATE SERVICE ACCOUNT"**
3. **Nombre:** `tempus-calendar-service`
4. Click **"CREATE AND CONTINUE"**
5. **Rol:** "Editor" (o crear rol personalizado con permisos de Calendar)
6. Click **"DONE"**

### Paso 2: Crear Clave JSON

1. Click en el service account creado
2. Tab **"KEYS"** → **"ADD KEY"** → **"Create new key"**
3. **Tipo:** JSON
4. Click **"CREATE"**
5. Se descarga `tempus-calendar-service-xxxxx.json`
6. **RENOMBRAR** a `service-account.json`
7. **MOVER** a la raíz del proyecto (junto a `docker-compose.yml`)

> [!CAUTION]
> Añade `service-account.json` al `.gitignore` para no commitear credenciales.

### Paso 3: Crear Calendar Compartido

1. Ve a https://calendar.google.com
2. Click en **"+"** junto a "Otros calendarios"
3. **"Crear calendario"**
4. **Nombre:** `Ausencias y Vacaciones - Tempus`
5. Click **"Crear calendario"**

### Paso 4: Compartir Calendar con Service Account

1. En el calendario recién creado, click en **"⋮"** → **"Configuración y uso compartido"**
2. Sección **"Compartir con determinadas personas"**
3. Click **"Agregar personas"**
4. **Email:** El email del Service Account (ej: `tempus-calendar-service@tu-proyecto.iam.gserviceaccount.com`)
5. **Permisos:** "Hacer cambios en los eventos"
6. Click **"Enviar"**

### Paso 5: Obtener Calendar ID

1. En configuración del calendario
2. Sección **"Integrar calendario"**
3. Copiar **"ID del calendario"** (ej: `abc123@group.calendar.google.com`)

### Paso 6: Configurar .env

```bash
GOOGLE_CALENDAR_ID=abc123@group.calendar.google.com
GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json
```

---

## Opción B: OAuth Usuario Admin (Desarrollo)

### Paso 1: Habilitar Calendar API

1. Ve a https://console.cloud.google.com/apis/library
2. Busca **"Google Calendar API"**
3. Click **"HABILITAR"**

### Paso 2: Crear Credenciales OAuth

1. Ve a https://console.cloud.google.com/apis/credentials
2. **"CREATE CREDENTIALS"** → **"OAuth client ID"**
3. **Tipo:** "Desktop app"
4. **Nombre:** "Tempus Calendar Admin"
5. Click **"CREATE"**
6. Descarga el JSON → renombrar a `credentials.json`
7. Mover a raíz del proyecto

### Paso 3: Crear Calendar Compartido

(Mismo que Opción A, Paso 3)

### Paso 4: Obtener Token

```bash
python scripts/authenticate_calendar.py
```

Esto abrirá el navegador para autorizar. Se generará `token.pickle`.

### Paso 5: Compartir Calendar con Empleados

1. En configuración del calendario
2. **"Permisos de acceso"** → Marcar "Disponible públicamente"
3. O compartir manualmente con cada empleado (ver eventos)

### Paso 6: Configurar .env

```bash
GOOGLE_CALENDAR_ID=abc123@group.calendar.google.com
# NO configurar GOOGLE_SERVICE_ACCOUNT_FILE si usas OAuth
```

---

## Verificación

```bash
# El ID del calendario compartido debe verse así:
# abc123xyz@group.calendar.google.com

# Verificar que el service account tiene acceso:
# 1. Ve al calendar en browser
# 2. Configuración → "Compartir con determinadas personas"
# 3. Debe aparecer el service account con permisos
```

## Troubleshooting

| Error | Solución |
|-------|----------|
| "No se encontraron credenciales" | Verificar que existe `service-account.json` o `token.pickle` |
| "HttpError 403: Forbidden" | El service account no tiene permisos en el calendar. Añadirlo como editor. |
| "Calendar ID not found" | Verificar que `GOOGLE_CALENDAR_ID` es el ID correcto (no el email del usuario) |
| Evento no aparece | Ver logs: `docker-compose logs -f web \| grep Calendar` |
