from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
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
    
    def dias_vacaciones_disponibles(self):
        dias_usados = sum([
            s.dias_solicitados for s in self.solicitudes_vacaciones 
            if s.estado == 'aprobada' and s.es_actual
        ])
        return self.dias_vacaciones - dias_usados


class Fichaje(db.Model):
    __tablename__ = 'fichajes'
    
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
    
    aprobador = db.relationship('Usuario', foreign_keys=[aprobador_id])
    
    def __repr__(self):
        return f'<SolicitudVacaciones {self.usuario.nombre} - {self.fecha_inicio}>'


class SolicitudBaja(db.Model):
    __tablename__ = 'solicitudes_bajas'
    
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
    
    def __repr__(self):
        return f'<SolicitudBaja {self.usuario.nombre} - {self.fecha_inicio}>'


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
    
    def __repr__(self):
        return f'<Festivo {self.fecha} - {self.descripcion}>'