from flask import Blueprint, request, render_template, redirect, url_for, session, flash
from models import db, User, ActivityLog
from functools import wraps
from sqlalchemy import desc
from dicom_utils.activity_logger import log_activity

auth_bp = Blueprint('auth_bp', __name__, url_prefix='/auth')

# Decorator to require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth_bp.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Decorator to require specific role
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth_bp.login'))
            
            user = User.query.get(session['user_id'])
            if not user or user.role not in roles:
                return render_template('error.html', 
                    message='Access denied. Insufficient permissions.'), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@auth_bp.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    return render_template('profile.html', user=user)



# User management page (admin only)
@auth_bp.route('/users', methods=['GET'])
@login_required
@role_required('admin')
def manage_users():
    users = User.query.all()
    return render_template('manage_users.html', users=users)

# Create new user (admin only)
@auth_bp.route('/users/create', methods=['POST'])
@login_required
@role_required('admin')
def create_user():
    data = request.form
    
    # Check if username exists
    existing = User.query.filter_by(username=data['username']).first()
    if existing:
        flash('Username already exists', 'error')
        return redirect(url_for('auth_bp.manage_users'))
    
    user = User(
        username=data['username'],
        role=data['role'],
        full_name=data.get('full_name'),
        email=data.get('email'),
        is_active=True
    )
    user.set_password(data['password'])
    
    db.session.add(user)
    db.session.commit()
    
    flash(f'User {user.username} created successfully!', 'success')
    return redirect(url_for('auth_bp.manage_users'))

# Toggle user active status
@auth_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User {user.username} {status}', 'success')
    return redirect(url_for('auth_bp.manage_users'))

# Reset user password (admin only)
@auth_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@role_required('admin')
def reset_user_password(user_id):
    user = User.query.get_or_404(user_id)

    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not new_password or not confirm_password:
        flash('Both password fields are required', 'error')
        return redirect(url_for('auth_bp.manage_users'))

    if len(new_password) < 6:
        flash('Password must be at least 6 characters', 'error')
        return redirect(url_for('auth_bp.manage_users'))

    if new_password != confirm_password:
        flash('Password confirmation does not match', 'error')
        return redirect(url_for('auth_bp.manage_users'))

    user.set_password(new_password)
    db.session.commit()

    log_activity(
        'password_reset',
        resource=f'user_{user.username}',
        details=f'Password reset by admin {session.get("username")}'
    )

    flash(f'Password reset successfully for {user.username}', 'success')
    return redirect(url_for('auth_bp.manage_users'))

# Activity logs page (admin only)
@auth_bp.route('/activity-logs', methods=['GET'])
@login_required
@role_required('admin')
def activity_logs():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    logs = ActivityLog.query.order_by(desc(ActivityLog.timestamp)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('activity_logs.html', logs=logs)

# Login / Logout LogActivity
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('home_bp.home_page'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please enter both username and password', 'error')
            return render_template('login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password) and user.is_active:
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session['full_name'] = user.full_name or user.username
            
            # Log the login
            log_activity('login', details=f'Successful login from {request.remote_addr}')
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home_bp.home_page'))
        else:
            # Log failed login attempt
            log_activity('login_failed', details=f'Failed login attempt for username: {username}')
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    # Log the logout before clearing session
    log_activity('logout')
    
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('auth_bp.login'))
