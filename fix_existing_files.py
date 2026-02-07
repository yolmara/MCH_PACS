# fix_existing_files.py
import os
from app import create_app
from models import db, Instance

app = create_app()

with app.app_context():
    instances = Instance.query.all()
    fixed = 0
    not_found = 0
    
    for inst in instances:
        old_path = inst.file_path
        
        # Skip if already has .dcm
        if old_path and old_path.endswith('.dcm'):
            continue
            
        # Make path absolute (relative to /app)
        abs_old_path = os.path.join('/app', old_path) if not old_path.startswith('/') else old_path
        
        # Check if file exists
        if os.path.exists(abs_old_path):
            # Rename file to add .dcm extension
            abs_new_path = f"{abs_old_path}.dcm"
            rel_new_path = f"{old_path}.dcm"
            
            os.rename(abs_old_path, abs_new_path)
            inst.file_path = rel_new_path
            fixed += 1
            print(f"✓ Fixed: {old_path}")
        else:
            not_found += 1
            print(f"✗ Not found: {abs_old_path}")
    
    db.session.commit()
    print(f"\n✅ Fixed {fixed} files")
    print(f"⚠️  {not_found} files not found on disk")