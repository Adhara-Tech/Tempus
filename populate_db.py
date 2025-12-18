import random
from datetime import datetime, timedelta, time
from werkzeug.security import generate_password_hash
from src import app, db
from src.models import Usuario, Fichaje, UserKnownIP

def init_db():
    print("🚀 Iniciando script de población de datos...")
    
    with app.app_context():
        # Crear tablas si no existen
        db.create_all()
        
        # 1. Crear Usuarios de prueba
        usuarios = []
        roles = ['empleado', 'aprobador', 'admin']
        nombres = [
            "Ana García", "Carlos López", "María Rodríguez", "Juan Martínez", 
            "Laura Fernández", "Pedro Sánchez", "Sofía Pérez", "Diego Gómez",
            "Elena Ruiz", "Miguel Díaz", "Lucía Torres", "Javier Romero"
        ]
        
        print(f"👤 Creando {len(nombres)} usuarios...")
        
        for i, nombre in enumerate(nombres):
            email = f"{nombre.lower().replace(' ', '.')}@example.com"
            
            # Verificar si existe
            user = Usuario.query.filter_by(email=email).first()
            if not user:
                user = Usuario(
                    nombre=nombre,
                    email=email,
                    password=generate_password_hash('password123'),
                    rol=roles[i % 3], # Rotar roles
                    dias_vacaciones=25
                )
                db.session.add(user)
                db.session.commit() # Commit para obtener ID
                
                # Crear IP conocida para evitar MFA al probar
                db.session.add(UserKnownIP(usuario_id=user.id, ip_address='127.0.0.1'))
                print(f"   ✅ Creado: {nombre} ({user.rol})")
            else:
                print(f"   ℹ️ Ya existe: {nombre}")
            
            usuarios.append(user)
        
        db.session.commit()
        
        # 2. Crear Fichajes masivos
        print("\n⏱️  Generando fichajes (esto puede tardar un poco)...")
        
        # Generar fichajes para el último año
        fecha_fin = datetime.now().date()
        fecha_inicio = fecha_fin - timedelta(days=365)
        
        total_fichajes = 0
        
        for user in usuarios:
            current_date = fecha_inicio
            while current_date <= fecha_fin:
                # Solo días laborables (L-V)
                if current_date.weekday() < 5: 
                    # Probabilidad del 95% de fichar ese día
                    if random.random() < 0.95:
                        # Hora entrada aleatoria entre 7:30 y 9:30
                        hora_entrada = time(
                            hour=random.randint(7, 9),
                            minute=random.randint(0, 59)
                        )
                        if hora_entrada.hour == 7 and hora_entrada.minute < 30:
                            hora_entrada = hora_entrada.replace(minute=30)
                            
                        # Jornada de aprox 8h + 1h comida
                        duracion_segundos = random.randint(8*3600, 9*3600)
                        dt_entrada = datetime.combine(current_date, hora_entrada)
                        dt_salida = dt_entrada + timedelta(seconds=duracion_segundos)
                        
                        fichaje = Fichaje(
                            usuario_id=user.id,
                            fecha=current_date,
                            hora_entrada=hora_entrada,
                            hora_salida=dt_salida.time(),
                            pausa=60, # 1 hora de pausa estándar
                            es_actual=True,
                            version=1,
                            tipo_accion='creacion'
                        )
                        db.session.add(fichaje)
                        total_fichajes += 1
                        
                current_date += timedelta(days=1)
        
        db.session.commit()
        print(f"\n🎉 Proceso finalizado. Total fichajes creados: {total_fichajes}")

if __name__ == '__main__':
    init_db()
