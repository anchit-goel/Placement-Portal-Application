from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Admin, Company, Student, PlacementDrive, Application, Placement, Notification
from functools import wraps
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.get_role() != 'admin':
            flash('Access denied. Admins only.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ─── Dashboard ───────────────────────────────────────────────

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    total_students = Student.query.count()
    total_companies = Company.query.count()
    total_drives = PlacementDrive.query.count()
    total_applications = Application.query.count()
    total_placements = Placement.query.count()

    pending_companies = Company.query.filter_by(approval_status='pending').count()
    pending_drives = PlacementDrive.query.filter_by(status='pending').count()

    recent_applications = Application.query.order_by(
        Application.applied_on.desc()
    ).limit(5).all()

    # Data for pie chart — applications by status
    status_counts = {
        'applied': Application.query.filter_by(status='applied').count(),
        'shortlisted': Application.query.filter_by(status='shortlisted').count(),
        'interview': Application.query.filter_by(status='interview').count(),
        'selected': Application.query.filter_by(status='selected').count(),
        'rejected': Application.query.filter_by(status='rejected').count(),
    }

    # Data for bar chart — applications per drive
    drives = PlacementDrive.query.all()
    drive_labels = [d.job_title[:20] for d in drives]
    drive_counts = [len(d.applications) for d in drives]

    return render_template('admin/dashboard.html',
        total_students=total_students,
        total_companies=total_companies,
        total_drives=total_drives,
        total_applications=total_applications,
        total_placements=total_placements,
        pending_companies=pending_companies,
        pending_drives=pending_drives,
        recent_applications=recent_applications,
        status_counts=status_counts,
        drive_labels=drive_labels,
        drive_counts=drive_counts
    )

# ─── Company Management ───────────────────────────────────────

@admin_bp.route('/companies')
@login_required
@admin_required
def companies():
    search = request.args.get('search', '').strip()
    if search:
        if search.isdigit():
            company_list = Company.query.filter(Company.id == int(search)).all()
        else:
            filters = [
                Company.name.ilike(f'%{search}%'),
                Company.email.ilike(f'%{search}%'),
                Company.industry.ilike(f'%{search}%')
            ]
            company_list = Company.query.filter(or_(*filters)).all()
    else:
        company_list = Company.query.order_by(Company.created_at.desc()).all()
    return render_template('admin/companies.html', companies=company_list, search=search)


@admin_bp.route('/company/<int:company_id>/action', methods=['POST'])
@login_required
@admin_required
def company_action(company_id):
    company = Company.query.get_or_404(company_id)
    action = request.form.get('action')

    if action == 'approve':
        company.approval_status = 'approved'
        flash(f'{company.name} has been approved.', 'success')
    elif action == 'reject':
        company.approval_status = 'rejected'
        flash(f'{company.name} has been rejected.', 'warning')
    elif action == 'blacklist':
        company.status = 'blacklisted'
        flash(f'{company.name} has been blacklisted.', 'danger')
    elif action == 'activate':
        company.status = 'active'
        company.approval_status = 'approved'
        flash(f'{company.name} has been reactivated.', 'success')

    db.session.commit()
    return redirect(url_for('admin.companies'))


@admin_bp.route('/company/<int:company_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_company(company_id):
    company = Company.query.get_or_404(company_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        hr_contact = request.form.get('hr_contact', '').strip()
        industry = request.form.get('industry', '').strip()
        website = request.form.get('website', '').strip()
        description = request.form.get('description', '').strip()
        approval_status = request.form.get('approval_status', '').strip()
        status = request.form.get('status', '').strip()

        errors = []

        if not name:
            errors.append('Company name is required.')
        if not email or '@' not in email:
            errors.append('A valid company email is required.')

        existing_company = Company.query.filter_by(email=email).first()
        if existing_company and existing_company.id != company.id:
            errors.append('This email is already used by another company.')

        if approval_status not in ['pending', 'approved', 'rejected']:
            errors.append('Invalid approval status selected.')
        if status not in ['active', 'blacklisted']:
            errors.append('Invalid account status selected.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('admin.edit_company', company_id=company.id))

        company.name = name
        company.email = email
        company.hr_contact = hr_contact
        company.industry = industry
        company.website = website
        company.description = description
        company.approval_status = approval_status
        company.status = status

        db.session.commit()
        flash('Company updated successfully.', 'success')
        return redirect(url_for('admin.view_company', company_id=company.id))

    return render_template('admin/edit_company.html', company=company)


@admin_bp.route('/company/<int:company_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_company(company_id):
    company = Company.query.get_or_404(company_id)
    try:
        # Remove dependent rows first to satisfy NOT NULL foreign key constraints.
        drive_ids = [d.id for d in PlacementDrive.query.filter_by(company_id=company.id).all()]

        if drive_ids:
            Application.query.filter(Application.drive_id.in_(drive_ids)).delete(synchronize_session=False)
            Placement.query.filter(
                or_(
                    Placement.company_id == company.id,
                    Placement.drive_id.in_(drive_ids)
                )
            ).delete(synchronize_session=False)
            PlacementDrive.query.filter(PlacementDrive.id.in_(drive_ids)).delete(synchronize_session=False)
        else:
            Placement.query.filter_by(company_id=company.id).delete(synchronize_session=False)

        db.session.delete(company)
        db.session.commit()
        flash('Company deleted successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Unable to delete company due to related records.', 'danger')

    return redirect(url_for('admin.companies'))


# ─── Student Management ───────────────────────────────────────

@admin_bp.route('/students')
@login_required
@admin_required
def students():
    search = request.args.get('search', '').strip()
    if search:
        if search.isdigit():
            student_list = Student.query.filter(Student.id == int(search)).all()
        else:
            filters = [
                Student.name.ilike(f'%{search}%'),
                Student.email.ilike(f'%{search}%'),
                Student.phone.ilike(f'%{search}%')
            ]
            student_list = Student.query.filter(or_(*filters)).all()
    else:
        student_list = Student.query.order_by(Student.created_at.desc()).all()
    return render_template('admin/students.html', students=student_list, search=search)


@admin_bp.route('/student/<int:student_id>/action', methods=['POST'])
@login_required
@admin_required
def student_action(student_id):
    student = Student.query.get_or_404(student_id)
    action = request.form.get('action')

    if action == 'blacklist':
        student.status = 'blacklisted'
        flash(f'{student.name} has been blacklisted.', 'danger')
    elif action == 'activate':
        student.status = 'active'
        flash(f'{student.name} has been reactivated.', 'success')

    db.session.commit()
    return redirect(url_for('admin.students'))


@admin_bp.route('/student/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        branch = request.form.get('branch', '').strip()
        cgpa = request.form.get('cgpa', '').strip()
        graduation_year = request.form.get('graduation_year', '').strip()
        skills = request.form.get('skills', '').strip()
        status = request.form.get('status', '').strip()

        errors = []

        if not name:
            errors.append('Student name is required.')
        if not email or '@' not in email:
            errors.append('A valid student email is required.')

        existing_student = Student.query.filter_by(email=email).first()
        if existing_student and existing_student.id != student.id:
            errors.append('This email is already used by another student.')

        cgpa_value = None
        if cgpa:
            try:
                cgpa_value = float(cgpa)
                if cgpa_value < 0 or cgpa_value > 10:
                    errors.append('CGPA must be between 0 and 10.')
            except ValueError:
                errors.append('CGPA must be a number.')

        graduation_year_value = None
        if graduation_year:
            try:
                graduation_year_value = int(graduation_year)
                if graduation_year_value < 2000 or graduation_year_value > 2035:
                    errors.append('Graduation year must be between 2000 and 2035.')
            except ValueError:
                errors.append('Graduation year must be a number.')

        if status not in ['active', 'blacklisted']:
            errors.append('Invalid account status selected.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('admin.edit_student', student_id=student.id))

        student.name = name
        student.email = email
        student.phone = phone
        student.branch = branch
        student.cgpa = cgpa_value
        student.graduation_year = graduation_year_value
        student.skills = skills
        student.status = status

        db.session.commit()
        flash('Student updated successfully.', 'success')
        return redirect(url_for('admin.view_student', student_id=student.id))

    return render_template('admin/edit_student.html', student=student)


@admin_bp.route('/student/<int:student_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    try:
        # Remove dependent rows first to satisfy NOT NULL foreign key constraints.
        Application.query.filter_by(student_id=student.id).delete(synchronize_session=False)
        Placement.query.filter_by(student_id=student.id).delete(synchronize_session=False)
        Notification.query.filter_by(student_id=student.id).delete(synchronize_session=False)

        db.session.delete(student)
        db.session.commit()
        flash('Student deleted successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Unable to delete student due to related records.', 'danger')

    return redirect(url_for('admin.students'))


# ─── Placement Drive Management ───────────────────────────────

@admin_bp.route('/drives')
@login_required
@admin_required
def drives():
    drive_list = PlacementDrive.query.order_by(PlacementDrive.created_at.desc()).all()
    return render_template('admin/drives.html', drives=drive_list)


@admin_bp.route('/drive/<int:drive_id>/action', methods=['POST'])
@login_required
@admin_required
def drive_action(drive_id):
    drive = PlacementDrive.query.get_or_404(drive_id)
    action = request.form.get('action')

    if action == 'approve':
        drive.status = 'approved'
        flash(f'Drive "{drive.job_title}" has been approved.', 'success')
    elif action == 'reject':
        drive.status = 'rejected'
        flash(f'Drive "{drive.job_title}" has been rejected.', 'warning')

    db.session.commit()
    return redirect(url_for('admin.drives'))


# ─── Applications ─────────────────────────────────────────────

@admin_bp.route('/applications')
@login_required
@admin_required
def applications():
    application_list = Application.query.order_by(Application.applied_on.desc()).all()
    return render_template('admin/applications.html', applications=application_list)


@admin_bp.route('/placements')
@login_required
@admin_required
def placements():
    placement_list = Placement.query.order_by(Placement.placed_on.desc()).all()
    return render_template('admin/placements.html', placements=placement_list)


# ─── View Student Profile ─────────────────────────────────────

@admin_bp.route('/student/<int:student_id>/view')
@login_required
@admin_required
def view_student(student_id):
    student = Student.query.get_or_404(student_id)
    applications = Application.query.filter_by(student_id=student_id).all()
    return render_template('admin/view_student.html', student=student, applications=applications)


# ─── View Company Profile ─────────────────────────────────────

@admin_bp.route('/company/<int:company_id>/view')
@login_required
@admin_required
def view_company(company_id):
    company = Company.query.get_or_404(company_id)
    drives = PlacementDrive.query.filter_by(company_id=company_id).all()
    return render_template('admin/view_company.html', company=company, drives=drives)