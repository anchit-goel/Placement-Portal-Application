from flask import Flask
from flask_login import LoginManager
from models import db, Admin
from config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        parts = user_id.split('_')
        role = parts[0]
        uid = int(parts[1])

        if role == 'admin':
            from models import Admin
            return Admin.query.get(uid)
        elif role == 'company':
            from models import Company
            return Company.query.get(uid)
        elif role == 'student':
            from models import Student
            return Student.query.get(uid)
        return None

    from auth.routes import auth_bp
    from admin.routes import admin_bp
    from company.routes import company_bp
    from student.routes import student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(company_bp, url_prefix='/company')
    app.register_blueprint(student_bp, url_prefix='/student')

    with app.app_context():
        db.create_all()
        seed_admin()

    return app


def seed_admin():
    if not Admin.query.first():
        admin = Admin(username='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('Admin seeded successfully.')


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5002)