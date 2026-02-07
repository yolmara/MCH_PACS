from models import db, ActivityLog
from flask import session, request

def log_activity(action, resource=None, details=None):
    """
    Log user activity
    
    Args:
        action: Type of action (login, logout, upload, view_study, etc.)
        resource: Resource being accessed (patient_id, study_uid, etc.)
        details: Additional details (can be string or dict)
    """
    try:
        log = ActivityLog(
            user_id=session.get('user_id'),
            username=session.get('username', 'anonymous'),
            action=action,
            resource=resource,
            details=str(details) if details else None,
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Failed to log activity: {e}")
        db.session.rollback()