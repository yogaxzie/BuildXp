import os
import uuid
import subprocess
import signal
import sys
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'buildxp-secret-key-2026-secure'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Global dict to track running Python processes
running_processes = {}

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='user')  # user, vip, admin
    vip_expiry = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def is_vip(self):
        if self.role == 'admin':
            return True
        if self.role == 'vip' and self.vip_expiry and self.vip_expiry > datetime.utcnow():
            return True
        return False
    
    def is_admin(self):
        return self.role == 'admin'

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_name = db.Column(db.String(100))
    code_type = db.Column(db.String(20))  # html, python
    code_content = db.Column(db.Text)
    deploy_url = db.Column(db.String(200))
    unique_id = db.Column(db.String(50), unique=True)
    port = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    user = db.relationship('User', backref='projects')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    type = db.Column(db.String(20), default='info')  # info, vip_upgrade
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_global = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    user = db.relationship('User', backref='notifications')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Initialize admin user
def init_admin():
    with app.app_context():
        admin = User.query.filter_by(username='Zbuild').first()
        if not admin:
            admin = User(
                username='Zbuild',
                email='admin@buildxp.app',
                password=generate_password_hash('252532'),
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created: Zbuild / 252532")

# Routes
@app.route('/')
def index():
    notifications = Notification.query.filter_by(is_global=True).order_by(Notification.created_at.desc()).limit(5).all()
    return render_template('index.html', notifications=notifications)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username sudah digunakan!', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email sudah terdaftar!', 'error')
            return redirect(url_for('register'))
        
        new_user = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            role='user',
            vip_expiry=datetime.utcnow() + timedelta(days=7)  # Free trial 7 hari
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registrasi berhasil! Silakan login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter((User.username == username) | (User.email == username)).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f'Selamat datang, {user.username}!', 'success')
            
            if user.is_admin():
                return redirect(url_for('admin_panel'))
            return redirect(url_for('dashboard'))
        
        flash('Username/email atau password salah!', 'error')
        return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Anda telah logout.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get user notifications
    user_notifications = Notification.query.filter(
        (Notification.user_id == current_user.id) | (Notification.is_global == True)
    ).order_by(Notification.created_at.desc()).limit(10).all()
    
    # Get user projects
    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
    
    # Check expiry
    now = datetime.utcnow()
    for project in projects:
        if project.expires_at < now:
            # Stop Python process if expired
            if project.code_type == 'python' and project.unique_id in running_processes:
                try:
                    running_processes[project.unique_id].terminate()
                    del running_processes[project.unique_id]
                except:
                    pass
    
    return render_template('dashboard.html', 
                         notifications=user_notifications, 
                         projects=projects,
                         is_vip=current_user.is_vip())

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    project_name = request.form.get('project_name') or f"Project-{uuid.uuid4().hex[:8]}"
    code_type = request.form.get('code_type')
    code_content = request.form.get('code_content')
    
    if not code_content:
        flash('Kode tidak boleh kosong!', 'error')
        return redirect(url_for('dashboard'))
    
    # Generate unique ID
    unique_id = uuid.uuid4().hex[:12]
    
    # Calculate expiry
    if current_user.is_vip():
        expires_at = current_user.vip_expiry if current_user.vip_expiry else datetime.utcnow() + timedelta(days=30)
    else:
        expires_at = datetime.utcnow() + timedelta(days=7)
    
    # Create project record
    project = Project(
        user_id=current_user.id,
        project_name=project_name,
        code_type=code_type,
        code_content=code_content,
        unique_id=unique_id,
        expires_at=expires_at
    )
    
    db.session.add(project)
    db.session.commit()
    
    # Deploy based on type
    if code_type == 'html':
        deploy_html(project, code_content)
        project.deploy_url = f'/site/{unique_id}/'
    elif code_type == 'python':
        port = deploy_python(project, code_content)
        if port:
            project.port = port
            project.deploy_url = f'http://localhost:{port}/'
    
    db.session.commit()
    
    flash(f'Website berhasil di-deploy! URL: {project.deploy_url}', 'success')
    return redirect(url_for('dashboard'))

def deploy_html(project, code_content):
    """Deploy HTML file to sites folder"""
    site_dir = os.path.join('sites', project.unique_id)
    os.makedirs(site_dir, exist_ok=True)
    
    # Safety check - basic XSS prevention
    forbidden_tags = ['<script>alert', 'javascript:', 'onerror=', 'onload=']
    for tag in forbidden_tags:
        if tag in code_content.lower():
            code_content = code_content.replace(tag, '[REMOVED]')
    
    index_path = os.path.join(site_dir, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(code_content)
    
    return True

def deploy_python(project, code_content):
    """Deploy Python Flask app as subprocess"""
    import random
    
    # Find available port
    port = random.randint(10000, 20000)
    
    site_dir = os.path.join('sites', project.unique_id)
    os.makedirs(site_dir, exist_ok=True)
    
    # Write app.py
    app_path = os.path.join(site_dir, 'app.py')
    
    # Wrap user code with minimal Flask setup
    wrapped_code = f'''
import os
import sys
os.chdir('{site_dir.replace("\\\\", "\\\\\\\\")}')

from flask import Flask, render_template_string
app = Flask(__name__)

# User code injection start
{code_content}
# User code injection end

if __name__ == '__main__':
    app.run(host='0.0.0.0', port={port}, debug=False, use_reloader=False)
'''
    
    with open(app_path, 'w', encoding='utf-8') as f:
        f.write(wrapped_code)
    
    # Start subprocess
    try:
        process = subprocess.Popen(
            [sys.executable, app_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=site_dir
        )
        running_processes[project.unique_id] = process
        return port
    except Exception as e:
        print(f"Error starting Python app: {e}")
        return None

@app.route('/site/<unique_id>/')
@app.route('/site/<unique_id>/<path:filename>')
def serve_site(unique_id, filename=None):
    """Serve deployed HTML sites"""
    site_dir = os.path.join('sites', unique_id)
    
    if not os.path.exists(site_dir):
        return "Site not found", 404
    
    # Check expiry
    project = Project.query.filter_by(unique_id=unique_id).first()
    if project and project.expires_at < datetime.utcnow():
        return "Site expired", 403
    
    if filename is None:
        filename = 'index.html'
    
    try:
        return send_from_directory(site_dir, filename)
    except:
        return "File not found", 404

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin():
        flash('Akses ditolak!', 'error')
        return redirect(url_for('dashboard'))
    
    stats = {
        'total_users': User.query.count(),
        'total_vip': User.query.filter_by(role='vip').count(),
        'total_websites': Project.query.count()
    }
    
    users = User.query.all()
    return render_template('admin.html', stats=stats, users=users)

@app.route('/admin/upgrade', methods=['POST'])
@login_required
def admin_upgrade():
    if not current_user.is_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    
    username = request.form.get('username')
    days = int(request.form.get('days', 30))
    
    user = User.query.filter_by(username=username).first()
    if not user:
        flash('User tidak ditemukan!', 'error')
        return redirect(url_for('admin_panel'))
    
    # Upgrade to VIP
    user.role = 'vip'
    user.vip_expiry = datetime.utcnow() + timedelta(days=days)
    
    # Create notification
    notif = Notification(
        message=f"User '{username}' telah menjadi pengguna VIP selama {days} hari!",
        type='vip_upgrade',
        is_global=True
    )
    
    db.session.add(notif)
    db.session.commit()
    
    flash(f'User {username} berhasil di-upgrade ke VIP selama {days} hari!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete-site/<int:project_id>', methods=['POST'])
@login_required
def delete_site(project_id):
    if not current_user.is_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    
    project = Project.query.get_or_404(project_id)
    
    # Stop process if Python
    if project.code_type == 'python' and project.unique_id in running_processes:
        try:
            running_processes[project.unique_id].terminate()
            del running_processes[project.unique_id]
        except:
            pass
    
    # Delete files
    import shutil
    site_dir = os.path.join('sites', project.unique_id)
    if os.path.exists(site_dir):
        shutil.rmtree(site_dir)
    
    db.session.delete(project)
    db.session.commit()
    
    flash('Website berhasil dihapus!', 'success')
    return redirect(url_for('admin_panel'))

# Cleanup on shutdown
def cleanup():
    for pid, process in running_processes.items():
        try:
            process.terminate()
        except:
            pass

import atexit
atexit.register(cleanup)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_admin()
    
    # Create necessary directories
    os.makedirs('sites', exist_ok=True)
    os.makedirs('instance', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
