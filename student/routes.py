import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from flask_login import login_required, current_user, logout_user
from models import db, Student, PlacementDrive, Application, Placement
from functools import wraps
from werkzeug.utils import secure_filename
from datetime import date

student_bp = Blueprint('student', __name__)

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.get_role() != 'student':
            flash('Access denied. Students only.', 'danger')
            return redirect(url_for('auth.login'))

        # Ensure status checks reflect latest DB state if admin changed account flags.
        try:
            db.session.refresh(current_user)
        except Exception:
            pass

        if current_user.status == 'blacklisted':
            logout_user()
            session.pop('_user_id', None)
            session.pop('_fresh', None)
            session.pop('_id', None)
            flash('Your account has been blacklisted. Contact admin.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ─── Dashboard ───────────────────────────────────────────────

@student_bp.route('/dashboard')
@login_required
@student_required
def dashboard():
    today = date.today()

    available_drives = PlacementDrive.query.filter_by(
        status='approved'
    ).order_by(PlacementDrive.created_at.desc()).all()

    my_applications = Application.query.filter_by(
        student_id=current_user.id
    ).order_by(Application.applied_on.desc()).all()

    applied_drive_ids = [app.drive_id for app in my_applications]

    # Chart data — status counts
    student_status_counts = {
        'applied': sum(1 for a in my_applications if a.status == 'applied'),
        'shortlisted': sum(1 for a in my_applications if a.status == 'shortlisted'),
        'interview': sum(1 for a in my_applications if a.status == 'interview'),
        'selected': sum(1 for a in my_applications if a.status == 'selected'),
        'rejected': sum(1 for a in my_applications if a.status == 'rejected'),
    }

    # Chart data — applications over time by month
    from collections import defaultdict
    monthly = defaultdict(int)
    for app in my_applications:
        key = app.applied_on.strftime('%b %Y')
        monthly[key] += 1
    student_time_labels = list(monthly.keys())
    student_time_counts = list(monthly.values())

    return render_template('student/dashboard.html',
        available_drives=available_drives,
        my_applications=my_applications,
        applied_drive_ids=applied_drive_ids,
        today=today,
        student_status_counts=student_status_counts,
        student_time_labels=student_time_labels,
        student_time_counts=student_time_counts
    )

# ─── View All Drives ─────────────────────────────────────────

@student_bp.route('/drives')
@login_required
@student_required
def drives():
    search = request.args.get('search', '')
    today = date.today()

    query = PlacementDrive.query.filter_by(status='approved')

    if search:
        query = query.filter(
            PlacementDrive.job_title.ilike(f'%{search}%') |
            PlacementDrive.required_skills.ilike(f'%{search}%') |
            PlacementDrive.location.ilike(f'%{search}%')
        )

    drives = query.order_by(PlacementDrive.created_at.desc()).all()

    my_applications = Application.query.filter_by(student_id=current_user.id).all()
    applied_drive_ids = [app.drive_id for app in my_applications]

    return render_template('student/drives.html',
        drives=drives,
        applied_drive_ids=applied_drive_ids,
        search=search,
        today=today
    )


# ─── View Drive Detail ────────────────────────────────────────

@student_bp.route('/drive/<int:drive_id>')
@login_required
@student_required
def view_drive(drive_id):
    drive = PlacementDrive.query.get_or_404(drive_id)
    today = date.today()

    if drive.status not in ['approved', 'closed']:
        flash('This drive is not available.', 'warning')
        return redirect(url_for('student.drives'))

    already_applied = Application.query.filter_by(
        student_id=current_user.id,
        drive_id=drive_id
    ).first()

    return render_template('student/view_drive.html',
        drive=drive,
        already_applied=already_applied,
        today=today
    )


# ─── Apply for Drive ─────────────────────────────────────────

@student_bp.route('/drive/<int:drive_id>/apply', methods=['POST'])
@login_required
@student_required
def apply(drive_id):
    drive = PlacementDrive.query.get_or_404(drive_id)

    if drive.status == 'closed':
        flash('This drive is closed and no longer accepting applications.', 'danger')
        return redirect(url_for('student.drives'))

    if drive.status != 'approved':
        flash('This drive is not open for applications.', 'danger')
        return redirect(url_for('student.drives'))

    if drive.deadline < date.today():
        flash('The deadline for this drive has passed.', 'danger')
        return redirect(url_for('student.drives'))

    existing = Application.query.filter_by(
        student_id=current_user.id,
        drive_id=drive_id
    ).first()

    if existing:
        flash('You have already applied for this drive.', 'warning')
        return redirect(url_for('student.drives'))

    application = Application(
        student_id=current_user.id,
        drive_id=drive_id
    )
    db.session.add(application)
    db.session.commit()

    flash(f'Successfully applied for {drive.job_title}!', 'success')
    return redirect(url_for('student.my_applications'))


# ─── My Applications ─────────────────────────────────────────

@student_bp.route('/applications')
@login_required
@student_required
def my_applications():
    applications = Application.query.filter_by(
        student_id=current_user.id
    ).order_by(Application.applied_on.desc()).all()

    return render_template('student/applications.html', applications=applications)


# ─── Placement History ────────────────────────────────────────

@student_bp.route('/history')
@login_required
@student_required
def history():
    placements = Placement.query.filter_by(
        student_id=current_user.id
    ).order_by(Placement.placed_on.desc()).all()

    return render_template('student/history.html', placements=placements)


# ─── Notifications ────────────────────────────────────────────

@student_bp.route('/notifications')
@login_required
@student_required
def notifications():
    from models import Notification
    notifs = Notification.query.filter_by(
        student_id=current_user.id
    ).order_by(Notification.created_at.desc()).all()

    for n in notifs:
        n.is_read = True
    db.session.commit()

    return render_template('student/notifications.html', notifications=notifs)


# ─── Edit Profile ─────────────────────────────────────────────

@student_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
@student_required
def edit_profile():
    if request.method == 'POST':
        current_user.name = request.form.get('name', '').strip()
        current_user.phone = request.form.get('phone', '').strip()
        current_user.branch = request.form.get('branch', '').strip()
        current_user.skills = request.form.get('skills', '').strip()

        cgpa = request.form.get('cgpa', '').strip()
        graduation_year = request.form.get('graduation_year', '').strip()

        errors = []

        if cgpa:
            try:
                cgpa_value = float(cgpa)
                if cgpa_value < 0 or cgpa_value > 10:
                    errors.append('CGPA must be between 0 and 10.')
                else:
                    current_user.cgpa = cgpa_value
            except ValueError:
                errors.append('CGPA must be a number.')
        else:
            current_user.cgpa = None

        if graduation_year:
            try:
                grad_year_value = int(graduation_year)
                if grad_year_value < 2000 or grad_year_value > 2035:
                    errors.append('Graduation year must be between 2000 and 2035.')
                else:
                    current_user.graduation_year = grad_year_value
            except ValueError:
                errors.append('Graduation year must be a number.')
        else:
            current_user.graduation_year = None

        if 'resume' in request.files:
            file = request.files['resume']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(f"resume_{current_user.email}_{file.filename}")
                upload_folder = current_app.config['UPLOAD_FOLDER']
                os.makedirs(upload_folder, exist_ok=True)
                file.save(os.path.join(upload_folder, filename))
                current_user.resume_path = filename
            elif file and file.filename != '' and not allowed_file(file.filename):
                errors.append('Resume must be a PDF file.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('student.edit_profile'))

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('student.edit_profile'))

    return render_template('student/edit_profile.html')