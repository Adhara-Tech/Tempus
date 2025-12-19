import click
from flask.cli import with_appcontext
from src import db
from src.models import Usuario, SaldoVacaciones

@click.command('cerrar-anio')
@click.argument('anio_origen', type=int)
@click.option('--max-carryover', default=10, type=int, help='Máximo de días a traspasar al año siguiente')
@click.option('--gestionar-festivos', 
              type=click.Choice(['archivar', 'eliminar', 'mantener'], case_sensitive=False),
              default='archivar',
              help='Qué hacer con festivos antiguos: archivar (marcar inactivos), eliminar (borrar) o mantener')
@click.option('--anios-antiguedad', default=1, type=int, help='Archivar/eliminar festivos con X años de antiguedad (default: 1)')
@click.option('--force', is_flag=True, help='Forzar ejecución sin confirmación')
@with_appcontext
def cerrar_anio_command(anio_origen, max_carryover, gestionar_festivos, anios_antiguedad, force):
    """
    Cierra el año fiscal especificado y genera los saldos del siguiente.
    Opcionalmente gestiona festivos antiguos.
    
    Ejemplos:
        flask cerrar-anio 2024
        flask cerrar-anio 2024 --max-carryover 12 --gestionar-festivos archivar
        flask cerrar-anio 2024 --gestionar-festivos eliminar --anios-antiguedad 2
    """
    from src.models import Festivo
    from datetime import date
    from src.utils import invalidar_cache_festivos
    
    db.create_all()  # Ensure tables exist
    
    anio_nuevo = anio_origen + 1
    
    print("=" * 70)
    print(f"  CIERRE DE AÑO FISCAL {anio_origen} → {anio_nuevo}")
    print("=" * 70)
    
    # ========================================
    # 1. VERIFICACIONES PREVIAS
    # ========================================
    
    # Verificar si ya existe cierre
    saldos_nuevos = SaldoVacaciones.query.filter_by(anio=anio_nuevo).count()
    if saldos_nuevos > 0 and not force:
        print(f"\n⚠️  ADVERTENCIA: Ya existen {saldos_nuevos} saldos para {anio_nuevo}")
        print("   Si quieres rehacer el cierre, usa --force")
        if not click.confirm('\n¿Continuar de todas formas?', default=False):
            print("❌ Operación cancelada")
            return
    
    # ========================================
    # 2. RESUMEN DE OPERACIONES
    # ========================================
    
    usuarios = Usuario.query.all()
    
    # Calcular festivos afectados
    # FIX: Archive festivos before the NEW year (includes the closing year)
    # With anios_antiguedad=1 and closing 2024→2025: limite=2025, so festivos < 2025-01-01 are archived
    anio_limite = anio_nuevo - anios_antiguedad + 1
    festivos_antiguos = Festivo.query.filter(
        Festivo.fecha < date(anio_limite, 1, 1),
        Festivo.activo == True
    ).all() if gestionar_festivos != 'mantener' else []
    
    print("\n📋 RESUMEN DE OPERACIONES:")
    print(f"   • Usuarios a procesar: {len(usuarios)}")
    print(f"   • Año origen: {anio_origen}")
    print(f"   • Año nuevo: {anio_nuevo}")
    print(f"   • Máximo carryover: {max_carryover} días")
    print(f"   • Gestión de festivos: {gestionar_festivos.upper()}")
    
    if gestionar_festivos != 'mantener':
        print(f"   • Festivos a {gestionar_festivos}: {len(festivos_antiguos)} (anteriores a {anio_limite})")
        if festivos_antiguos and len(festivos_antiguos) <= 10:
            print(f"\n   Festivos afectados:")
            for f in festivos_antiguos:
                print(f"      - {f.fecha.strftime('%d/%m/%Y')}: {f.descripcion}")
    
    # Confirmación
    if not force:
        print("\n" + "=" * 70)
        if not click.confirm('¿Proceder con el cierre de año?', default=False):
            print("❌ Operación cancelada")
            return
    
    print("\n" + "=" * 70)
    print("🔄 INICIANDO PROCESO...")
    print("=" * 70 + "\n")
    
    # ========================================
    # 3. GESTIÓN DE FESTIVOS (PRIMERO)
    # ========================================
    
    festivos_procesados = 0
    if gestionar_festivos != 'mantener' and festivos_antiguos:
        print(f"📅 Gestionando festivos antiguos (< {anio_limite})...")
        
        if gestionar_festivos == 'archivar':
            # Marcar como inactivos (soft delete)
            for festivo in festivos_antiguos:
                festivo.activo = False
                print(f"   ⏸️  Archivado: {festivo.fecha.strftime('%d/%m/%Y')} - {festivo.descripcion}")
                festivos_procesados += 1
        
        elif gestionar_festivos == 'eliminar':
            # Eliminar permanentemente
            for festivo in festivos_antiguos:
                print(f"   🗑️  Eliminado: {festivo.fecha.strftime('%d/%m/%Y')} - {festivo.descripcion}")
                db.session.delete(festivo)
                festivos_procesados += 1
        
        db.session.commit()
        invalidar_cache_festivos()  # ✅ Invalidar cache después de cambios
        
        print(f"   ✅ {festivos_procesados} festivos procesados\n")
    
    # ========================================
    # 4. CIERRE DE SALDOS DE VACACIONES
    # ========================================
    
    print(f"💼 Procesando saldos de vacaciones...")
    print()
    
    count_creados = 0
    count_actualizados = 0
    count_saltados = 0
    errores = []

    for u in usuarios:
        try:
            # 1. Obtener saldo del año que cierra
            saldo_antiguo = SaldoVacaciones.query.filter_by(
                usuario_id=u.id,
                anio=anio_origen
            ).first()

            # Si no tiene saldo del año anterior, usar base contractual
            if not saldo_antiguo:
                sobrante = 0
                print(f"   ⚠️  {u.nombre}: No tiene saldo {anio_origen}, usando base contractual")
            else:
                sobrante = saldo_antiguo.dias_totales - saldo_antiguo.dias_disfrutados

            # 2. Aplicar política de Carryover
            if sobrante > 0:
                dias_a_traspasar = min(sobrante, max_carryover)
                simbolo = "✅"
            elif sobrante < 0:
                dias_a_traspasar = sobrante  # Deuda completa
                simbolo = "⚠️"
            else:
                dias_a_traspasar = 0
                simbolo = "➖"

            # 3. Calcular base del nuevo año
            dias_base_nuevo_anio = u.dias_vacaciones 
            total_nuevo = dias_base_nuevo_anio + dias_a_traspasar

            # 4. Crear o Actualizar Saldo del Año Nuevo
            saldo_nuevo = SaldoVacaciones.query.filter_by(
                usuario_id=u.id,
                anio=anio_nuevo
            ).first()

            if not saldo_nuevo:
                saldo_nuevo = SaldoVacaciones(
                    usuario_id=u.id,
                    anio=anio_nuevo,
                    dias_totales=total_nuevo,
                    dias_disfrutados=0,
                    dias_carryover=dias_a_traspasar
                )
                db.session.add(saldo_nuevo)
                count_creados += 1
                print(f"   {simbolo} {u.nombre:30} | Base: {dias_base_nuevo_anio:2} + Carryover: {dias_a_traspasar:3} = {total_nuevo:3} días")
            
            elif force:
                # Si force, actualizar saldo existente
                saldo_nuevo.dias_totales = total_nuevo
                saldo_nuevo.dias_carryover = dias_a_traspasar
                saldo_nuevo.dias_disfrutados = 0  # Reset
                count_actualizados += 1
                print(f"   🔄 {u.nombre:30} | ACTUALIZADO (force) = {total_nuevo} días")
            
            else:
                count_saltados += 1
                print(f"   ⏭️  {u.nombre:30} | Ya existe saldo {anio_nuevo} (saltado)")

        except Exception as e:
            errores.append(f"{u.nombre}: {str(e)}")
            print(f"   ❌ {u.nombre}: ERROR - {str(e)}")

    # Commit de saldos
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"\n❌ ERROR AL HACER COMMIT: {str(e)}")
        return
    
    # ========================================
    # 5. RESUMEN FINAL
    # ========================================
    
    print("\n" + "=" * 70)
    print("📊 RESUMEN FINAL")
    print("=" * 70)
    
    if gestionar_festivos != 'mantener':
        print(f"\n📅 Festivos:")
        print(f"   • Procesados: {festivos_procesados}")
        print(f"   • Acción: {gestionar_festivos.upper()}")
    
    print(f"\n💼 Saldos de Vacaciones:")
    print(f"   • Creados: {count_creados}")
    if force:
        print(f"   • Actualizados: {count_actualizados}")
    print(f"   • Saltados: {count_saltados}")
    print(f"   • Total procesado: {count_creados + count_actualizados + count_saltados}/{len(usuarios)}")
    
    if errores:
        print(f"\n❌ Errores encontrados ({len(errores)}):")
        for error in errores:
            print(f"   • {error}")
    
    print("\n" + "=" * 70)
    print("✅ PROCESO COMPLETADO")
    print("=" * 70)


@click.command('import-users')
@click.argument('csv_file', type=click.Path(exists=True))
@with_appcontext
def import_users_command(csv_file):
    """
    Importa usuarios desde un fichero CSV.
    Formato esperado: nombre,email
    """
    import csv
    import secrets
    from werkzeug.security import generate_password_hash
    from datetime import datetime
    from src.models import SaldoVacaciones  # ✅ Añadir import

    db.create_all()  # Ensure tables exist
    print(f"--- Importando usuarios desde {csv_file} ---")
    
    count_new = 0
    count_skip = 0
    anio_actual = datetime.now().year  # ✅ Calcular una vez

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]

        if 'email' not in reader.fieldnames or 'nombre' not in reader.fieldnames:
            print("❌ Error: El CSV debe tener columnas 'nombre' y 'email'.")
            return

        for row in reader:
            nombre = row.get('nombre', '').strip()
            email = row.get('email', '').strip()

            if not email:
                continue

            existing = Usuario.query.filter_by(email=email).first()
            if existing:
                print(f"Saltado {email}: Ya existe.")
                count_skip += 1
                continue

            # Crear usuario
            raw_pass = secrets.token_urlsafe(8)
            password_hash = generate_password_hash(raw_pass)

            new_user = Usuario(
                nombre=nombre,
                email=email,
                password=password_hash,
                rol='usuario',
                dias_vacaciones=25
            )
            
            db.session.add(new_user)
            db.session.flush()  # ✅ Genera new_user.id
            
            # ✅ NUEVO: Crear saldo automáticamente
            saldo = SaldoVacaciones(
                usuario_id=new_user.id,
                anio=anio_actual,
                dias_totales=25,
                dias_disfrutados=0,
                dias_carryover=0
            )
            db.session.add(saldo)
            
            count_new += 1
            print(f"✅ Creado: {nombre} ({email}) - Pass: {raw_pass}")

    db.session.commit()
    print(f"\nResumen: {count_new} creados, {count_skip} saltados.")


@click.command('init-admin')
@with_appcontext
def init_admin_command():
    """
    Crea el usuario administrador inicial basado en variables de entorno.
    """
    from werkzeug.security import generate_password_hash
    from flask import current_app
    
    db.create_all()  # Ensure tables exist
    
    email = current_app.config.get('DEFAULT_ADMIN_EMAIL')
    password = current_app.config.get('DEFAULT_ADMIN_INITIAL_PASSWORD')
    
    if not email or not password:
        print("❌ Error: DEFAULT_ADMIN_EMAIL o DEFAULT_ADMIN_INITIAL_PASSWORD no definidos.")
        return

    existing = Usuario.query.filter_by(email=email).first()
    if existing:
        print(f"ℹ️ El usuario administrador ({email}) ya existe.")
        return

    admin = Usuario(
        nombre='Administrador',
        email=email,
        password=generate_password_hash(password),
        rol='admin',
        dias_vacaciones=25
    )
    db.session.add(admin)
    db.session.commit()
    print(f"✅ Usuario Administrador creado: {email}")
    