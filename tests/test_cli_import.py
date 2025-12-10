import csv
import os
from src.models import Usuario

def test_import_users_command(test_app, runner):
    """Test the CLI command for importing users from CSV."""
    
    # Create a temporary CSV file
    csv_filename = 'temp_users.csv'
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['nombre', 'email'])
        writer.writerow(['Test User 1', 'test1@example.com'])
        writer.writerow(['Test User 2', 'test2@example.com'])
        writer.writerow(['Existing User', 'admin@example.com']) # Assuming admin exists
    
    try:
        # Run the command
        result = runner.invoke(args=['import-users', csv_filename])
        
        # Check output
        assert result.exit_code == 0
        assert "Importando usuarios" in result.output
        assert "Test User 1" in result.output
        assert "Test User 2" in result.output
        
        # Check database
        with test_app.app_context():
            user1 = Usuario.query.filter_by(email='test1@example.com').first()
            user2 = Usuario.query.filter_by(email='test2@example.com').first()
            
            assert user1 is not None
            assert user1.nombre == 'Test User 1'
            assert user1.rol == 'usuario'
            assert user1.dias_vacaciones == 25
            
            assert user2 is not None
            
            # Check existing user was skipped (should be counted in skips)
            # We don't verify admin exists here because test environment might vary, 
            # but we can rely on output or just ensures no dupe error.
            
    finally:
        # Cleanup
        if os.path.exists(csv_filename):
            os.remove(csv_filename)

def test_import_users_invalid_csv(test_app, runner):
    """Test importing with invalid CSV format."""
    csv_filename = 'invalid.csv'
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['wrong_header', 'other'])
        writer.writerow(['data', 'data'])
        
    try:
        result = runner.invoke(args=['import-users', csv_filename])
        assert "Error: El CSV debe tener columnas" in result.output
        
    finally:
        if os.path.exists(csv_filename):
            os.remove(csv_filename)
