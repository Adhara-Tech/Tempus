import click
from flask.cli import with_appcontext
from src import db
from src.models import Usuario, SaldoVacaciones

@click.command('cerrar-anio')
@click.argument('anio_origen', type=int)
@click.option('--max-carryover', default=10, type=int, help='Máximo de días a traspasar al año siguiente (por defecto: 10)')
@with_appcontext
def cerrar_anio_command(anio_origen, max_carryover):
    """
    Cierra el año fiscal especificado y genera los saldos del siguiente.
    Uso: flask cerrar-anio 2024 --max-carryover 12
    """
    anio_nuevo = anio_origen + 1
    usuarios = Usuario.query.all()
    count = 0
    
    print(f"--- Cerrando Año Fiscal {anio_origen} -> {anio_nuevo} ---")
    print(f"--- Configuración: Máximo Carryover = {max_carryover} días ---")

    for u in usuarios:
        # 1. Obtener saldo del año que cierra
        saldo_antiguo = SaldoVacaciones.query.filter_by(usuario_id=u.id, anio=anio_origen).first()

        # Si no tuvo saldo el año anterior, asumimos 0 sobrante
        sobrante = 0
        if saldo_antiguo:
            sobrante = saldo_antiguo.dias_totales - saldo_antiguo.dias_disfrutados

        # 2. Aplicar política de Carryover
        # Si sobraron días negativos (comió días de más), se restan del año siguiente (deuda)
        # Si sobraron positivos, aplicamos el tope (max_carryover)
        if sobrante > 0:
            dias_a_traspasar = min(sobrante, max_carryover)
        else:
            dias_a_traspasar = sobrante # Arrastra la deuda íntegra

        # 3. Calcular base del nuevo año
        # Usamos u.dias_vacaciones como la "Base Contractual"
        dias_base_nuevo_anio = u.dias_vacaciones 
        total_nuevo = dias_base_nuevo_anio + dias_a_traspasar

        # 4. Crear o Actualizar Saldo del Año Nuevo
        saldo_nuevo = SaldoVacaciones.query.filter_by(usuario_id=u.id, anio=anio_nuevo).first()

        if not saldo_nuevo:
            saldo_nuevo = SaldoVacaciones(
                usuario_id=u.id,
                anio=anio_nuevo,
                dias_totales=total_nuevo,
                dias_disfrutados=0,
                dias_carryover=dias_a_traspasar
            )
            db.session.add(saldo_nuevo)
            count += 1
            print(f"> Generado saldo {anio_nuevo} para {u.nombre}: Base {dias_base_nuevo_anio} + Carryover {dias_a_traspasar} = {total_nuevo}")
        else:
            print(f"> Saltado {u.nombre}: Ya tiene saldo para {anio_nuevo}")

    db.session.commit()
    print(f"✅ Proceso finalizado. Se generaron {count} nuevos saldos.")


@click.command('import-users')
@click.argument('csv_file', type=click.Path(exists=True))
@with_appcontext
def import_users_command(csv_file):
    """
    Importa usuarios desde un fichero CSV.
    Formato esperado: nombre,email
    Columna vacía o resto de columnas se ignoran.
    """
    import csv
    import secrets
    from werkzeug.security import generate_password_hash

    print(f"--- Importando usuarios desde {csv_file} ---")
    
    count_new = 0
    count_skip = 0

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        # Normalizar headers por si acaso tienen espacios
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]

        if 'email' not in reader.fieldnames or 'nombre' not in reader.fieldnames:
            print("❌ Error: El CSV debe tener columnas 'nombre' y 'email'.")
            return

        for row in reader:
            nombre = row.get('nombre', '').strip()
            email = row.get('email', '').strip()

            if not email:
                continue

            # Check existencia
            existing = Usuario.query.filter_by(email=email).first()
            if existing:
                print(f"Assignado {email}: Ya existe. SALTADO.")
                count_skip += 1
                continue

            # Crear usuario
            # Password aleatorio
            raw_pass = secrets.token_urlsafe(8)
            password_hash = generate_password_hash(raw_pass)

            new_user = Usuario(
                nombre=nombre,
                email=email,
                password=password_hash,
                rol='usuario', # Default role
                dias_vacaciones=25 # Default
            )
            
            db.session.add(new_user)
            count_new += 1
            print(f"✅ Creado: {nombre} ({email}) - Pass: {raw_pass}")

    db.session.commit()
    print(f"\nResumen: {count_new} creados, {count_skip} saltados.")
    