from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
from sqlalchemy.schema import UniqueConstraint
import uuid

db = SQLAlchemy()

# Función auxiliar para generar UUIDs
def generate_uuid():
    return str(uuid.uuid4())

class TipoAusencia(db.Model):
    __tablename__ = 'tipos_ausencia'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(255))
    max_dias = db.Column(db.Integer, default=365)
    tipo_dias = db.Column(db.String(20), default='naturales')
    requiere_justificante = db.Column(db.Boolean, default=False)
    descuenta_vacaciones = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=True) # Soft delete
    
    def __repr__(self):
        return f'<TipoAusencia {self.nombre}>'


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False)
    dias_vacaciones = db.Column(db.Integer, default=25)
    fecha_alta = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con fichajes
    fichajes = db.relationship(
        'Fichaje', 
        foreign_keys='Fichaje.usuario_id', 
        backref='usuario', 
        lazy=True, 
        cascade='all, delete-orphan'
    )
    
    solicitudes_vacaciones = db.relationship(
        'SolicitudVacaciones', 
        foreign_keys='SolicitudVacaciones.usuario_id',
        backref='usuario', 
        lazy=True, 
        cascade='all, delete-orphan'
    )

    solicitudes_bajas = db.relationship(
        'SolicitudBaja',
        foreign_keys='SolicitudBaja.usuario_id',
        back_populates='usuario',
        lazy=True,
        cascade='all, delete-orphan'
    )
    
    aprobadores = db.relationship('Aprobador', foreign_keys='Aprobador.usuario_id', 
                                 backref='usuario_rel', lazy=True, cascade='all, delete-orphan')
    usuarios_a_cargo = db.relationship('Aprobador', foreign_keys='Aprobador.aprobador_id',
                                      backref='aprobador_rel', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Usuario {self.nombre}>'
    
    def dias_vacaciones_disponibles(self, anio=None):
        if anio is None:
            anio = datetime.now().year
            
        saldo = SaldoVacaciones.query.filter_by(usuario_id=self.id, anio=anio).first()
        
        if saldo:
            return saldo.dias_totales - saldo.dias_disfrutados
        return 0

    # Relación con saldos de vacaciones
    saldos_vacaciones = db.relationship('SaldoVacaciones', backref='usuario', lazy=True)


class SaldoVacaciones(db.Model):
    __tablename__ = 'saldos_vacaciones'

    __table_args__ = (
        UniqueConstraint('usuario_id', 'anio', name='unique_usuario_anio'),
    )

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    dias_totales = db.Column(db.Integer, default=25)
    dias_disfrutados = db.Column(db.Integer, default=0)
    dias_carryover = db.Column(db.Integer, default=0)

    __table_args__ = (
        UniqueConstraint('usuario_id', 'anio', name='unique_usuario_anio'),
    )

    def __repr__(self):
        return f'<SaldoVacaciones {self.usuario.nombre} - {self.anio}>'


class Fichaje(db.Model):
    __tablename__ = 'fichajes'

    __table_args__ = (
        # 1. Índice principal: Acelera "Mis Fichajes" y los informes mensuales
        # Orden: Filtramos por usuario -> solo actuales -> rango de fechas
        db.Index('idx_fichaje_usuario_fecha', 'usuario_id', 'es_actual', 'fecha'),
        
        # 2. Índice secundario: Para agrupaciones por UUID (historial de versiones)
        db.Index('idx_fichaje_grupo', 'grupo_id'),

        db.Index('idx_fichaje_fecha', 'fecha'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Versionado
    grupo_id = db.Column(db.String(36), default=generate_uuid, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    es_actual = db.Column(db.Boolean, default=True, nullable=False)
    tipo_accion = db.Column(db.String(20), default='creacion')
    motivo_rectificacion = db.Column(db.Text)
    
    # Datos Principales
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    editor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id')) # Quién hizo el cambio
    
    fecha = db.Column(db.Date, nullable=False)
    hora_entrada = db.Column(db.Time, nullable=False)
    hora_salida = db.Column(db.Time, nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Campo pausa
    pausa = db.Column(db.Integer, default=0) # En minutos
    
    # Relación para saber quién editó
    editor = db.relationship('Usuario', foreign_keys=[editor_id])
    
    def __repr__(self):
        estado = "ACTUAL" if self.es_actual else f"V{self.version}"
        return f'<Fichaje {self.fecha} ({estado}) - {self.usuario.nombre}>'
    
    def horas_trabajadas(self):
        entrada = datetime.combine(self.fecha, self.hora_entrada)
        salida = datetime.combine(self.fecha, self.hora_salida)
        
        if salida < entrada:
            salida += timedelta(days=1)
            
        diferencia = salida - entrada
        horas_totales = diferencia.total_seconds() / 3600
        
        # Restar la pausa (convertida de minutos a horas)
        horas_pausa = (self.pausa or 0) / 60
        
        return max(0, horas_totales - horas_pausa)


class SolicitudVacaciones(db.Model):
    __tablename__ = 'solicitudes_vacaciones'

    __table_args__ = (
        # 1. Índice para detección de solapamientos (Overlap Check) y listados
        # Incluimos 'estado' porque siempre filtras 'pendiente' o 'aprobada'
        db.Index('idx_vacaciones_solape', 'usuario_id', 'es_actual', 'estado', 'fecha_inicio', 'fecha_fin'),
        
        # 2. Índice para historial de versiones
        db.Index('idx_vacaciones_grupo', 'grupo_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    grupo_id = db.Column(db.String(36), default=generate_uuid, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    es_actual = db.Column(db.Boolean, default=True, nullable=False)
    motivo_rectificacion = db.Column(db.Text)
    
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    dias_solicitados = db.Column(db.Integer, nullable=False)
    motivo = db.Column(db.Text)
    estado = db.Column(db.String(20), nullable=False)
    fecha_solicitud = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_respuesta = db.Column(db.DateTime)
    aprobador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    comentarios = db.Column(db.Text)
    google_event_id = db.Column(db.String(255))
    
    # Nuevos campos para versionado y auditoría
    tipo_accion = db.Column(db.String(20), default='creacion')
    editor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    aprobador = db.relationship('Usuario', foreign_keys=[aprobador_id])
    editor = db.relationship('Usuario', foreign_keys=[editor_id])

    @property
    def dias_adelanto(self):
        """
        Calcula dinámicamente cuántos días de adelanto supone esta solicitud
        basándose en el saldo actual del usuario para el año de la solicitud.
        """
        if not self.usuario:
            return 0
            
        # Obtenemos el saldo disponible del usuario para el año de estas vacaciones
        # Nota: Usamos self.fecha_inicio.year para ser precisos con el año fiscal
        anio = self.fecha_inicio.year
        disponible = self.usuario.dias_vacaciones_disponibles(anio)
        
        # Si pide más de lo que tiene, la diferencia es el adelanto
        if self.dias_solicitados > disponible:
            return self.dias_solicitados - disponible
            
        return 0
    
    def __repr__(self):
        return f'<SolicitudVacaciones {self.usuario.nombre} - {self.fecha_inicio}>'


class SolicitudBaja(db.Model):
    __tablename__ = 'solicitudes_bajas'

    __table_args__ = (
        # Mismo razonamiento que en vacaciones
        db.Index('idx_bajas_solape', 'usuario_id', 'es_actual', 'estado', 'fecha_inicio', 'fecha_fin'),
        db.Index('idx_bajas_grupo', 'grupo_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    grupo_id = db.Column(db.String(36), default=generate_uuid, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    es_actual = db.Column(db.Boolean, default=True, nullable=False)
    motivo_rectificacion = db.Column(db.Text)

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    tipo_ausencia_id = db.Column(db.Integer, db.ForeignKey('tipos_ausencia.id'), nullable=True)
    tipo_ausencia = db.relationship('TipoAusencia')
    
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    dias_solicitados = db.Column(db.Integer, nullable=False)
    motivo = db.Column(db.Text, nullable=False)
    estado = db.Column(db.String(20), nullable=False)
    fecha_solicitud = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_respuesta = db.Column(db.DateTime)
    aprobador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    comentarios = db.Column(db.Text)
    google_event_id = db.Column(db.String(255))
    
    aprobador = db.relationship('Usuario', foreign_keys=[aprobador_id])
    usuario = db.relationship('Usuario', foreign_keys=[usuario_id], back_populates='solicitudes_bajas')

    # Relación con attachments (uno a muchos)
    attachments = db.relationship(
        'Attachment',
        primaryjoin="and_(SolicitudBaja.id==foreign(Attachment.entidad_id), "
                    "Attachment.tipo_entidad=='baja', "
                    "Attachment.activo==True)",
        viewonly=True,  # No gestiona la relación automáticamente
        lazy='dynamic'  # Permite queries adicionales
    )
    
    def __repr__(self):
        return f'<SolicitudBaja {self.usuario.nombre} - {self.fecha_inicio}>'

    @property
    def tiene_attachments(self):
        """Verifica si esta baja tiene archivos adjuntos"""
        return self.attachments.count() > 0
    
    @property
    def attachments_activos(self):
        """Retorna lista de attachments activos"""
        return self.attachments.filter_by(activo=True).all()


class Aprobador(db.Model):
    __tablename__ = 'aprobadores'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    aprobador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_asignacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    usuario = db.relationship('Usuario', foreign_keys=[usuario_id], overlaps='usuario_rel,aprobadores')
    aprobador = db.relationship('Usuario', foreign_keys=[aprobador_id], overlaps='aprobador_rel,usuarios_a_cargo')
    
    def __repr__(self):
        return f'<Aprobador {self.aprobador.nombre} aprueba a {self.usuario.nombre}>'


class Festivo(db.Model):
    __tablename__ = 'festivos'
    
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, unique=True)
    descripcion = db.Column(db.String(200), nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)  # ✅ AÑADIR
    
    def __repr__(self):
        return f'<Festivo {self.fecha} - {self.descripcion}>'

class Attachment(db.Model):
    """
    Modelo genérico para almacenar adjuntos/archivos.
    Puede asociarse a diferentes entidades (bajas, vacaciones, etc.)
    """
    __tablename__ = 'attachments'
    
    # Índices para optimizar búsquedas
    __table_args__ = (
        db.Index('idx_attachment_entidad', 'tipo_entidad', 'entidad_id', 'activo'),
        db.Index('idx_attachment_usuario', 'uploaded_by', 'fecha_subida'),
    )
    
    # ==========================================
    # CAMPOS PRINCIPALES
    # ==========================================
    id = db.Column(db.Integer, primary_key=True)
    
    # Identificación del archivo
    nombre_original = db.Column(db.String(255), nullable=False)  # Nombre original del archivo
    nombre_almacenado = db.Column(db.String(255), nullable=False, unique=True)  # UUID único en disco
    extension = db.Column(db.String(10), nullable=False)  # .pdf, .jpg, .png, etc.
    mime_type = db.Column(db.String(100))  # application/pdf, image/jpeg, etc.
    
    # Metadatos del archivo
    tamano_bytes = db.Column(db.Integer, nullable=False)  # Tamaño en bytes
    hash_sha256 = db.Column(db.String(64))  # Hash para verificar integridad (opcional)
    
    # Ruta de almacenamiento
    # Ejemplo: "uploads/bajas/2024/12/uuid.pdf"
    ruta_relativa = db.Column(db.String(500), nullable=False)
    
    # ==========================================
    # ASOCIACIÓN POLIMÓRFICA
    # ==========================================
    # Permite asociar a diferentes tipos de entidades
    tipo_entidad = db.Column(db.String(50), nullable=False)  # 'baja', 'vacaciones', 'fichaje', etc.
    entidad_id = db.Column(db.Integer, nullable=False)  # ID de la entidad asociada
    
    # Opcional: Descripción/notas del adjunto
    descripcion = db.Column(db.String(500))  # "Justificante médico", "Parte de baja", etc.
    categoria = db.Column(db.String(50))  # "justificante", "informe", "parte_baja", etc.
    
    # ==========================================
    # AUDITORÍA
    # ==========================================
    uploaded_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Soft delete
    activo = db.Column(db.Boolean, default=True, nullable=False)
    fecha_eliminacion = db.Column(db.DateTime)
    eliminado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    motivo_eliminacion = db.Column(db.String(255))
    
    # ==========================================
    # CONTROL DE ACCESO (FUTURO)
    # ==========================================
    publico = db.Column(db.Boolean, default=False)  # Si es visible para todos o solo admin/aprobadores
    
    # ==========================================
    # RELACIONES
    # ==========================================
    # Usuario que subió el archivo
    uploader = db.relationship('Usuario', foreign_keys=[uploaded_by], backref='attachments_subidos')
    
    # Usuario que eliminó el archivo (si aplica)
    deleter = db.relationship('Usuario', foreign_keys=[eliminado_por])
    
    def __repr__(self):
        return f'<Attachment {self.nombre_original} ({self.tipo_entidad}:{self.entidad_id})>'
    
    # ==========================================
    # MÉTODOS DE UTILIDAD
    # ==========================================
    
    @property
    def tamano_legible(self):
        """Retorna el tamaño en formato legible (KB, MB, etc.)"""
        bytes = self.tamano_bytes
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024.0:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.1f} TB"
    
    @property
    def es_imagen(self):
        """Verifica si el archivo es una imagen"""
        return self.mime_type and self.mime_type.startswith('image/')
    
    @property
    def es_pdf(self):
        """Verifica si el archivo es un PDF"""
        return self.mime_type == 'application/pdf' or self.extension.lower() == '.pdf'
    
    def url_descarga(self):
        """
        Genera la URL de descarga del archivo (a implementar en routes).
        Placeholder para futura implementación.
        """
        return f'/attachments/download/{self.id}'
    
    def puede_ver(self, usuario):
        """
        Verifica si un usuario puede ver este attachment (a extender).
        Por ahora: solo el uploader, admin, o aprobadores.
        """
        if usuario.rol == 'admin':
            return True
        if self.uploaded_by == usuario.id:
            return True
        if self.publico:
            return True

        return False

class UserKnownIP(db.Model):
    __tablename__ = 'user_known_ips'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False) # Supports IPv4 and IPv6
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    # Index for fast lookups during login
    __table_args__ = (
        db.Index('idx_user_ip', 'usuario_id', 'ip_address'),
    )

    def __repr__(self):
        return f'<UserKnownIP {self.ip_address} - User {self.usuario_id}>'