# 1. Usar una imagen base ligera de Python
FROM python:3.11.14-slim

# 2. Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# 3. Copiar el archivo de requisitos e instalarlos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copiar todo el código de la aplicación
COPY . .

# 4.5 Copiar service account si existe (opcional para Calendar)
COPY service-account.json* ./

# 5. Exponer el puerto en el que correrá Gunicorn
EXPOSE 5000

# 6. Copiar el script entrypoint
COPY entrypoint.sh .

# 7. Dar permisos de ejecución al script entrypoint
RUN chmod +x entrypoint.sh

# 8. Definir el ENTRYPOINT
# Esto se ejecutará SIEMPRE. Recibe el CMD como argumento ("$@")
ENTRYPOINT ["./entrypoint.sh"]

# 9. Comando para ejecutar la aplicación
#    Inicia 4 "workers" para la app, apuntando al objeto 'app' dentro del archivo 'app.py'
CMD ["gunicorn", "-k", "gevent", "-w", "4", "--bind", "0.0.0.0:5000", "app:app"]