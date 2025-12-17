"""Tests for Festivos (holidays) CRUD operations in admin panel."""
from datetime import date
from src.models import Festivo
from src import db


def test_admin_festivos_list(auth_admin_client):
    """Admin can view festivos list."""
    response = auth_admin_client.get('/admin/festivos')
    assert response.status_code == 200
    assert "Festivos" in response.text


def test_admin_crear_festivo(auth_admin_client):
    """Admin can create a new festivo."""
    response = auth_admin_client.post('/admin/festivos/crear', data={
        'fecha': '2025-12-25',
        'descripcion': 'Navidad'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert "Festivo añadido" in response.text
    
    # Verify in DB
    festivo = Festivo.query.filter_by(descripcion='Navidad').first()
    assert festivo is not None
    assert festivo.fecha == date(2025, 12, 25)
    assert festivo.activo is True


def test_admin_toggle_festivo(auth_admin_client):
    """Admin can toggle festivo active status."""
    # Create a festivo
    festivo = Festivo(fecha=date(2025, 1, 1), descripcion='Año Nuevo', activo=True)
    db.session.add(festivo)
    db.session.commit()
    
    # Toggle to inactive
    response = auth_admin_client.post(f'/admin/festivos/toggle/{festivo.id}', follow_redirects=True)
    assert response.status_code == 200
    
    db.session.refresh(festivo)
    assert festivo.activo is False
    
    # Toggle back to active
    response = auth_admin_client.post(f'/admin/festivos/toggle/{festivo.id}', follow_redirects=True)
    db.session.refresh(festivo)
    assert festivo.activo is True


def test_admin_eliminar_festivo(auth_admin_client):
    """Admin can delete a festivo."""
    festivo = Festivo(fecha=date(2025, 8, 15), descripcion='Asunción', activo=True)
    db.session.add(festivo)
    db.session.commit()
    festivo_id = festivo.id
    
    response = auth_admin_client.post(f'/admin/festivos/eliminar/{festivo_id}', follow_redirects=True)
    assert response.status_code == 200
    assert "Festivo eliminado" in response.text
    
    # Verify deleted
    assert Festivo.query.get(festivo_id) is None


def test_festivo_access_denied_for_employee(auth_client):
    """Non-admin users cannot access festivos management."""
    response = auth_client.get('/admin/festivos', follow_redirects=True)
    assert response.status_code == 200
    assert "Acceso denegado" in response.text
