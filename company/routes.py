from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user, logout_user
from models import db, Company, PlacementDrive, Application, Student
from functools import wraps
from datetime import date
from sqlalchemy.exc import IntegrityError

company_bp = Blueprint('company', __name__)


def company_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.get_role() != 'company':
            flash('Access denied. Companies only.', 'danger')
            return redirect(url_for('auth.login'))

        # Ensure status checks reflect latest DB state if admin changed account flags.
        try:
            db.session.refresh(current_user)
        except Exception:
            pass

        if current_user.approval_status != 'approved':
            logout_user()
            session.pop('_user_id', None)
            session.pop('_fresh', None)
            session.pop('_id', None)
            flash('Your account is not approved yet.', 'warning')
            return redirect(url_for('auth.login'))
        if current_user.status == 'blacklisted':
            logout_user()
            session.pop('_user_id', None)
            session.pop('_fresh', None)
            session.pop('_id', None)
            flash('Your account has been blacklisted.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ─── Dashboard ───────────────────────────────────────────────

@company_bp.route('/dashboard')
@login_required
@company_required
def dashboard():
    drives = PlacementDrive.query.filter_by(
        company_id=current_user.id
    ).order_by(PlacementDrive.created_at.desc()).all()

    total_drives = len(drives)
    total_applications = Application.query.join(PlacementDrive).filter(
        PlacementDrive.company_id == current_user.id
    ).count()
    total_selected = Application.query.join(PlacementDrive).filter(
        PlacementDrive.company_id == current_user.id,
        Application.status == 'selected'
    ).count()

    # Chart data
    app_status_counts = {
        'applied': Application.query.join(PlacementDrive).filter(
            PlacementDrive.company_id == current_user.id,
            Application.status == 'applied'
        ).count(),
        'shortlisted': Application.query.join(PlacementDrive).filter(
            PlacementDrive.company_id == current_user.id,
            Application.status == 'shortlisted'
        ).count(),
        'interview': Application.query.join(PlacementDrive).filter(
            PlacementDrive.company_id == current_user.id,
            Application.status == 'interview'
        ).count(),
        'selected': Application.query.join(PlacementDrive).filter(
            PlacementDrive.company_id == current_user.id,
            Application.status == 'selected'
        ).count(),
        'rejected': Application.query.join(PlacementDrive).filter(
            PlacementDrive.company_id == current_user.id,
            Application.status == 'rejected'
        ).count(),
    }

    company_drive_labels = [d.job_title[:20] for d in drives]
    company_drive_counts = [len(d.applications) for d in drives]

    return render_template('company/dashboard.html',
        drives=drives,
        total_drives=total_drives,
        total_applications=total_applications,
        total_selected=total_selected,
        app_status_counts=app_status_counts,
        company_drive_labels=company_drive_labels,
        company_drive_counts=company_drive_counts
    )

# ─── Create Drive ─────────────────────────────────────────────

@company_bp.route('/drive/create', methods=['GET', 'POST'])
@login_required
@company_required
def create_drive():
    if request.method == 'POST':
        job_title = request.form.get('job_title', '').strip()
        job_description = request.form.get('job_description', '').strip()
        eligibility = request.form.get('eligibility', '').strip()
        required_skills = request.form.get('required_skills', '').strip()
        experience_required = request.form.get('experience_required', '').strip()
        salary_min = request.form.get('salary_min', '').strip()
        salary_max = request.form.get('salary_max', '').strip()
        location = request.form.get('location', '').strip()
        deadline = request.form.get('deadline', '').strip()

        errors = []

        if not job_title:
            errors.append('Job title is required.')
        if not deadline:
            errors.append('Deadline is required.')
        else:
            try:
                deadline_date = date.fromisoformat(deadline)
                if deadline_date <= date.today():
                    errors.append('Deadline must be a future date.')
            except ValueError:
                errors.append('Invalid deadline format.')

        if salary_min and salary_max:
            try:
                if int(salary_min) > int(salary_max):
                    errors.append('Minimum salary cannot be greater than maximum salary.')
            except ValueError:
                errors.append('Salary must be a number.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('company.create_drive'))

        drive = PlacementDrive(
            company_id=current_user.id,
            job_title=job_title,
            job_description=job_description,
            eligibility=eligibility,
            required_skills=required_skills,
            experience_required=experience_required,
            salary_min=int(salary_min) if salary_min else None,
            salary_max=int(salary_max) if salary_max else None,
            location=location,
            deadline=date.fromisoformat(deadline)
        )
        db.session.add(drive)
        db.session.commit()

        flash('Placement drive submitted for admin approval.', 'success')
        return redirect(url_for('company.dashboard'))

    return render_template('company/create_drive.html')


# ─── Edit Drive ───────────────────────────────────────────────

@company_bp.route('/drive/<int:drive_id>/edit', methods=['GET', 'POST'])
@login_required
@company_required
def edit_drive(drive_id):
    drive = PlacementDrive.query.get_or_404(drive_id)

    if drive.company_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('company.dashboard'))

    if request.method == 'POST':
        job_title = request.form.get('job_title', '').strip()
        job_description = request.form.get('job_description', '').strip()
        eligibility = request.form.get('eligibility', '').strip()
        required_skills = request.form.get('required_skills', '').strip()
        experience_required = request.form.get('experience_required', '').strip()
        location = request.form.get('location', '').strip()
        salary_min = request.form.get('salary_min', '').strip()
        salary_max = request.form.get('salary_max', '').strip()
        deadline = request.form.get('deadline', '').strip()

        errors = []

        if not job_title:
            errors.append('Job title is required.')

        salary_min_value = None
        salary_max_value = None

        if salary_min:
            try:
                salary_min_value = int(salary_min)
            except ValueError:
                errors.append('Minimum salary must be a number.')

        if salary_max:
            try:
                salary_max_value = int(salary_max)
            except ValueError:
                errors.append('Maximum salary must be a number.')

        if salary_min_value is not None and salary_max_value is not None and salary_min_value > salary_max_value:
            errors.append('Minimum salary cannot be greater than maximum salary.')

        deadline_value = None
        if not deadline:
            errors.append('Deadline is required.')
        else:
            try:
                deadline_value = date.fromisoformat(deadline)
            except ValueError:
                errors.append('Invalid deadline format.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('company.edit_drive', drive_id=drive.id))

        drive.job_title = job_title
        drive.job_description = job_description
        drive.eligibility = eligibility
        drive.required_skills = required_skills
        drive.experience_required = experience_required
        drive.location = location
        drive.salary_min = salary_min_value
        drive.salary_max = salary_max_value
        drive.deadline = deadline_value

        db.session.commit()
        flash('Drive updated successfully.', 'success')
        return redirect(url_for('company.dashboard'))

    return render_template('company/edit_drive.html', drive=drive)


# ─── Close Drive ──────────────────────────────────────────────

@company_bp.route('/drive/<int:drive_id>/close', methods=['POST'])
@login_required
@company_required
def close_drive(drive_id):
    drive = PlacementDrive.query.get_or_404(drive_id)

    if drive.company_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('company.dashboard'))

    drive.status = 'closed'
    db.session.commit()
    flash('Drive has been closed.', 'success')
    return redirect(url_for('company.dashboard'))


# ─── Delete Drive ─────────────────────────────────────────────

@company_bp.route('/drive/<int:drive_id>/delete', methods=['POST'])
@login_required
@company_required
def delete_drive(drive_id):
    drive = PlacementDrive.query.get_or_404(drive_id)

    if drive.company_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('company.dashboard'))

    try:
        Application.query.filter_by(drive_id=drive.id).delete(synchronize_session=False)
        from models import Placement
        Placement.query.filter_by(drive_id=drive.id).delete(synchronize_session=False)

        db.session.delete(drive)
        db.session.commit()
        flash('Drive deleted successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Unable to delete drive due to related records.', 'danger')

    return redirect(url_for('company.dashboard'))


# ─── View Applicants ──────────────────────────────────────────

@company_bp.route('/drive/<int:drive_id>/applicants')
@login_required
@company_required
def view_applicants(drive_id):
    drive = PlacementDrive.query.get_or_404(drive_id)

    if drive.company_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('company.dashboard'))

    applications = Application.query.filter_by(drive_id=drive_id).all()
    return render_template('company/applicants.html', drive=drive, applications=applications)


# ─── Update Application Status ────────────────────────────────

@company_bp.route('/application/<int:app_id>/status', methods=['POST'])
@login_required
@company_required
def update_status(app_id):
    application = Application.query.get_or_404(app_id)
    drive = PlacementDrive.query.get_or_404(application.drive_id)

    if drive.company_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('company.dashboard'))

    new_status = request.form.get('status')
    if new_status in ['shortlisted', 'interview', 'selected', 'rejected']:
        application.status = new_status

        # Create notification for student
        from models import Notification
        message = f'Your application for {drive.job_title} at {current_user.name} has been updated to: {new_status.upper()}'
        notification = Notification(
            student_id=application.student_id,
            message=message
        )
        db.session.add(notification)

        # If selected, create placement record
        if new_status == 'selected':
            from models import Placement
            existing = Placement.query.filter_by(
                student_id=application.student_id,
                drive_id=application.drive_id
            ).first()
            if not existing:
                placement = Placement(
                    student_id=application.student_id,
                    drive_id=application.drive_id,
                    company_id=current_user.id
                )
                db.session.add(placement)

        db.session.commit()
        flash('Application status updated.', 'success')

    return redirect(url_for('company.view_applicants', drive_id=application.drive_id))

# ─── View Student Profile ─────────────────────────────────────

@company_bp.route('/student/<int:student_id>/view')
@login_required
@company_required
def view_student(student_id):
    student = Student.query.get_or_404(student_id)
    return render_template('company/view_student.html', student=student)


# ─── Edit Company Profile ─────────────────────────────────────

@company_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
@company_required
def edit_profile():
    if request.method == 'POST':
        current_user.hr_contact = request.form.get('hr_contact')
        current_user.website = request.form.get('website')
        current_user.description = request.form.get('description')
        current_user.industry = request.form.get('industry')
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('company.dashboard'))

    return render_template('company/edit_profile.html')