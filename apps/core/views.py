from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.urls import reverse
from apps.users.views import _is_superuser

from .codenames import generated_user_codename, user_codename
from .forms import CodeNameForm
from .models import (
    AdminAction,
    AdminActivityLog,
    Category,
    Concern,
    ConcernNote,
    ConcernResponse,
    ConcernStatus,
    Confession,
    ConfessionResponse,
    ReportComment,
    ReportImage,
    UserCodeName,
)
from .images import MAX_REPORT_IMAGES, prepare_report_images

User = get_user_model()

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=1)
INVALID_LOGIN_MESSAGE = 'Invalid username or password.'
LOCKED_MESSAGE = 'Too many failed attempts. Locked for 1 minute.'


def log_admin_activity(actor, action, report=None, old_value='', new_value='', detail='', target_user=None):
    """Record an auditable action for the activity history."""
    kwargs = {'actor': actor, 'action': action, 'old_value': old_value, 'new_value': new_value, 'detail': detail}
    if target_user is not None:
        kwargs['target_user'] = target_user
    if isinstance(report, Concern):
        kwargs['concern'] = report
    elif isinstance(report, Confession):
        kwargs['confession'] = report
    return AdminActivityLog.objects.create(**kwargs)


def _is_team_member(user):
    """Allow SafeSpeak administrators (the team) to manage reports."""
    return user.is_authenticated and user.is_superuser


def _reset_lock_state(request):
    request.session['failed_attempts'] = 0
    request.session['lock_time'] = None


def _get_lock_state(request):
    failed_attempts = request.session.get('failed_attempts', 0)
    lock_time = request.session.get('lock_time')

    if not lock_time:
        return failed_attempts, None

    try:
        unlock_time = timezone.datetime.fromisoformat(lock_time)
    except (TypeError, ValueError):
        _reset_lock_state(request)
        return 0, None

    if timezone.now() < unlock_time:
        remaining = int((unlock_time - timezone.now()).total_seconds())
        return failed_attempts, remaining

    _reset_lock_state(request)
    return 0, None


def _set_lock_state(request):
    lock_until = timezone.now() + LOCK_DURATION
    request.session['failed_attempts'] = MAX_FAILED_ATTEMPTS
    request.session['lock_time'] = lock_until.isoformat()
    return int(LOCK_DURATION.total_seconds())


def _validate_registration_data(data):
    errors = {}

    username = data.get('username', '').strip()
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not username:
        errors['username'] = 'Username is required.'
    elif User.objects.filter(username=username).exists():
        errors['username'] = 'Username already taken.'

    if not first_name:
        errors['first_name'] = 'First name is required.'

    if not last_name:
        errors['last_name'] = 'Last name is required.'

    if not email:
        errors['email'] = 'Email is required.'
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors['email'] = 'Enter a valid email address.'
        else:
            if User.objects.filter(email=email).exists():
                errors['email'] = 'Email already registered.'

    if not password:
        errors['password'] = 'Password is required.'
    elif len(password) < 8:
        errors['password'] = 'Password must be at least 8 characters.'
    else:
        try:
            validate_password(password)
        except ValidationError as exc:
            errors['password'] = ' '.join(exc.messages)

    if password != confirm_password:
        errors['confirm_password'] = 'Passwords do not match.'

    return errors


def _login_redirect_url(request, user):
    """Return the requested safe page, or the user's default dashboard."""
    next_url = request.POST.get('next') or request.GET.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    if user.is_superuser:
        return reverse('team_management')
    return reverse('dashboard')


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_login_redirect_url(request, request.user))

    next_url = request.POST.get('next') or request.GET.get('next', '')
    failed_attempts, remaining = _get_lock_state(request)
    if remaining is not None:
        messages.error(request, f'Too many failed attempts. Try again in {remaining} seconds.')
        return render(request, 'auth/login.html', {
            'locked': True,
            'remaining': remaining,
            'next': next_url,
        })

    if request.method == 'GET':
        return render(request, 'auth/login.html', {'next': next_url})

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    user = authenticate(request, username=username, password=password)

    if user is not None:
        _reset_lock_state(request)
        login(request, user)
        log_admin_activity(
            user,
            AdminAction.SIGNED_IN,
            target_user=user,
            detail=(
                'Signed in as an administrator.'
                if user.is_superuser
                else 'Signed in to SafeSpeak.'
            ),
        )
        return redirect(_login_redirect_url(request, user))

    failed_attempts += 1
    request.session['failed_attempts'] = failed_attempts
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        remaining = _set_lock_state(request)
        messages.error(request, LOCKED_MESSAGE)
        return render(request, 'auth/login.html', {
            'locked': True,
            'remaining': remaining,
            'next': next_url,
        })

    remaining_attempts = MAX_FAILED_ATTEMPTS - failed_attempts
    messages.error(request, f'{INVALID_LOGIN_MESSAGE} {remaining_attempts} attempts remaining.')
    return render(request, 'auth/login.html', {'next': next_url})


def logout_view(request):
    if request.user.is_authenticated:
        log_admin_activity(
            request.user,
            AdminAction.SIGNED_OUT,
            target_user=request.user,
            detail=(
                'Signed out as an administrator.'
                if request.user.is_superuser
                else 'Signed out of SafeSpeak.'
            ),
        )
    logout(request)
    return redirect('login')


def _derive_title(description):
    """Build a short report title from the first line of the description."""
    first_line = description.strip().splitlines()[0] if description.strip() else ''
    snippet = ' '.join(first_line.split())
    if len(snippet) > 80:
        return snippet[:77].rstrip() + '...'
    return snippet


def _submission_categories():
    """Return the categories a reporter can choose from."""
    return Category.objects.filter(is_active=True)


def _selected_category(raw_category):
    """Return the active category matching a submitted id, or None."""
    if not str(raw_category or '').isdigit():
        return None
    return Category.objects.filter(pk=raw_category, is_active=True).first()


def _link_report_to_account(request):
    """Return the reporter only when they explicitly opted in to linking."""
    if request.user.is_authenticated and request.POST.get('link_to_account') == 'on':
        return request.user
    return None


@login_required(login_url='login')
def submit_concern(request):
    """Allow signed-in users to submit a concern report anonymously."""
    if request.method == 'GET':
        return render(request, 'submit_concern.html', {
            'max_images': MAX_REPORT_IMAGES,
            'categories': _submission_categories(),
        })

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        category_id = request.POST.get('category', '').strip()
        category = _selected_category(category_id)
        is_urgent = request.POST.get('is_urgent', '') == 'on'
        reporter = _link_report_to_account(request)
        images, image_errors = prepare_report_images(
            request.FILES.getlist('images')
        )

        form_context = {
            'max_images': MAX_REPORT_IMAGES,
            'categories': _submission_categories(),
            'form_description': description,
            'form_category': category_id,
            'form_is_urgent': is_urgent,
            'form_link_to_account': request.POST.get('link_to_account') == 'on',
        }

        if not description:
            messages.error(request, 'Description is required.')
            return render(request, 'submit_concern.html', form_context)

        if image_errors:
            for error in image_errors:
                messages.error(request, error)
            return render(request, 'submit_concern.html', form_context)

        if category is None:
            messages.error(request, 'Select a category for this concern.')
            return render(request, 'submit_concern.html', form_context)

        with transaction.atomic():
            concern = Concern.objects.create(
                title=_derive_title(description),
                description=description,
                category=category,
                location_on_campus='',
                date_of_incident=None,
                is_urgent=is_urgent,
                status=ConcernStatus.SUBMITTED,
                submitted_by=reporter,
                poster_codename=(
                    user_codename(request.user.pk)
                    if request.user.is_authenticated else ''
                ),
            )
            for image in images:
                ReportImage.objects.create(concern=concern, image=image)

        detail = (
            'Concern submitted and linked to the reporter account.'
            if reporter is not None
            else 'Anonymous concern submitted.'
        )
        if images:
            count = len(images)
            detail = detail[:-1] + (
                f' with {count} image{"s" if count != 1 else ""}.'
            )

        log_admin_activity(
            None,
            AdminAction.REPORT_SUBMITTED,
            report=concern,
            detail=detail,
        )

        return render(request, 'submit_concern.html', {
            'submission_successful': True,
            'linked_to_account': reporter is not None,
            'submission_codename': concern.codename,
        })


@login_required(login_url='login')
def submit_confession(request):
    """Allow signed-in users to submit a confession anonymously."""
    if request.method == 'GET':
        return render(request, 'submit_confession.html', {
            'max_images': MAX_REPORT_IMAGES,
            'categories': _submission_categories(),
        })

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        category_id = request.POST.get('category', '').strip()
        category = _selected_category(category_id)
        is_urgent = request.POST.get('is_urgent', '') == 'on'
        reporter = _link_report_to_account(request)
        images, image_errors = prepare_report_images(
            request.FILES.getlist('images')
        )

        form_context = {
            'max_images': MAX_REPORT_IMAGES,
            'categories': _submission_categories(),
            'form_description': description,
            'form_category': category_id,
            'form_is_urgent': is_urgent,
            'form_link_to_account': request.POST.get('link_to_account') == 'on',
        }

        if not description:
            messages.error(request, 'Description is required.')
            return render(request, 'submit_confession.html', form_context)

        if image_errors:
            for error in image_errors:
                messages.error(request, error)
            return render(request, 'submit_confession.html', form_context)

        if category is None:
            messages.error(request, 'Select a category for this confession.')
            return render(request, 'submit_confession.html', form_context)

        with transaction.atomic():
            confession = Confession.objects.create(
                title=_derive_title(description),
                description=description,
                category=category,
                location_on_campus='',
                date_of_incident=None,
                is_urgent=is_urgent,
                status=ConcernStatus.SUBMITTED,
                submitted_by=reporter,
                poster_codename=(
                    user_codename(request.user.pk)
                    if request.user.is_authenticated else ''
                ),
            )
            for image in images:
                ReportImage.objects.create(confession=confession, image=image)

        detail = (
            'Confession submitted and linked to the reporter account.'
            if reporter is not None
            else 'Anonymous confession submitted.'
        )
        if images:
            count = len(images)
            detail = detail[:-1] + (
                f' with {count} image{"s" if count != 1 else ""}.'
            )

        log_admin_activity(
            None,
            AdminAction.REPORT_SUBMITTED,
            report=confession,
            detail=detail,
        )

        return render(request, 'submit_confession.html', {
            'submission_successful': True,
            'linked_to_account': reporter is not None,
            'submission_codename': confession.codename,
        })


STATUS_PROGRESS = {
    ConcernStatus.SUBMITTED: 25,
    ConcernStatus.UNDER_REVIEW: 50,
    ConcernStatus.IN_PROGRESS: 75,
    ConcernStatus.RESOLVED: 100,
    ConcernStatus.DISMISSED: 100,
}

STATUS_PALETTE = {
    ConcernStatus.SUBMITTED: '#7fa98a',
    ConcernStatus.UNDER_REVIEW: '#c9a35a',
    ConcernStatus.IN_PROGRESS: '#6f9c92',
    ConcernStatus.RESOLVED: '#4f7a5b',
    ConcernStatus.DISMISSED: '#b47c7c',
}


def _greeting():
    """Return a time-aware greeting for dashboard headings."""
    hour = timezone.localtime().hour
    if hour < 12:
        return 'Good morning'
    if hour < 18:
        return 'Good afternoon'
    return 'Good evening'


def _status_breakdown(concerns, confessions):
    """Build status totals and percentage shares for dashboard bars."""
    concern_counts = {
        status: total
        for status, total in concerns.values_list('status').annotate(total=Count('id'))
    }
    confession_counts = {
        status: total
        for status, total in confessions.values_list('status').annotate(total=Count('id'))
    }
    overall_total = sum(concern_counts.values()) + sum(confession_counts.values())

    breakdown = []
    for code, label in ConcernStatus.choices:
        total = concern_counts.get(code, 0) + confession_counts.get(code, 0)
        breakdown.append({
            'code': code,
            'label': label,
            'total': total,
            'color': STATUS_PALETTE.get(code, '#7c8b80'),
            'percent': round(total / overall_total * 100) if overall_total else 0,
        })
    return breakdown


def _category_folders(limit=6):
    """Return the most active categories as dashboard folder cards."""
    categories = Category.objects.filter(is_active=True).annotate(
        concern_total=Count('concerns', distinct=True),
        confession_total=Count('confessions', distinct=True),
    )
    folders = [
        {
            'category': category,
            'total': category.concern_total + category.confession_total,
            'concern_total': category.concern_total,
            'confession_total': category.confession_total,
        }
        for category in categories
    ]
    folders.sort(key=lambda item: (-item['total'], item['category'].name.lower()))
    return folders[:limit]


def _recent_report_cards(limit=4):
    """Return the newest reports from both queues for thumbnail cards."""
    cards = []
    for model, kind, label in (
        (Concern, 'concern', 'Concern'),
        (Confession, 'confession', 'Confession'),
    ):
        queryset = (
            model.objects
            .select_related('category')
            .prefetch_related('images')
            .order_by('-submitted_at')[:limit]
        )
        cards.extend({
            'kind': kind,
            'label': label,
            'report': report,
        } for report in queryset)

    cards.sort(key=lambda item: item['report'].submitted_at, reverse=True)
    return cards[:limit]


def _user_report_cards(user, limit=3):
    """Return the newest reports linked to a user's account."""
    cards = []
    for model, kind, label in (
        (Concern, 'concern', 'Concern'),
        (Confession, 'confession', 'Confession'),
    ):
        queryset = (
            model.objects
            .filter(submitted_by=user)
            .select_related('category', 'response')
            .prefetch_related('images')
            .order_by('-submitted_at')[:limit]
        )
        cards.extend({
            'kind': kind,
            'label': label,
            'report': report,
            'progress': STATUS_PROGRESS.get(report.status, 0),
            'has_response': getattr(report, 'response', None) is not None,
        } for report in queryset)

    cards.sort(key=lambda item: item['report'].submitted_at, reverse=True)
    return cards[:limit]


@login_required(login_url='login')
def my_reports(request):
    """Show reports the signed-in user explicitly linked to their account."""
    status_filter = request.GET.get('status', '').strip()
    if status_filter not in dict(ConcernStatus.choices):
        status_filter = ''

    report_type = request.GET.get('type', 'all').strip()
    if report_type not in ('all', 'concern', 'confession'):
        report_type = 'all'

    base_concerns = Concern.objects.filter(submitted_by=request.user)
    base_confessions = Confession.objects.filter(submitted_by=request.user)

    concern_count = base_concerns.count()
    confession_count = base_confessions.count()
    closed_statuses = [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]

    open_count = (
        base_concerns.exclude(status__in=closed_statuses).count()
        + base_confessions.exclude(status__in=closed_statuses).count()
    )
    resolved_count = (
        base_concerns.filter(status=ConcernStatus.RESOLVED).count()
        + base_confessions.filter(status=ConcernStatus.RESOLVED).count()
    )
    response_count = (
        base_concerns.filter(response__isnull=False).count()
        + base_confessions.filter(response__isnull=False).count()
    )

    concerns = base_concerns.select_related('category', 'response').prefetch_related('images')
    confessions = base_confessions.select_related('category', 'response').prefetch_related('images')
    if status_filter:
        concerns = concerns.filter(status=status_filter)
        confessions = confessions.filter(status=status_filter)

    reports = []
    if report_type in ('all', 'concern'):
        for concern in concerns:
            reports.append({
                'kind': 'concern',
                'type_label': 'Concern',
                'report': concern,
                'response': getattr(concern, 'response', None),
                'progress': STATUS_PROGRESS.get(concern.status, 0),
            })
    if report_type in ('all', 'confession'):
        for confession in confessions:
            reports.append({
                'kind': 'confession',
                'type_label': 'Confession',
                'report': confession,
                'response': getattr(confession, 'response', None),
                'progress': STATUS_PROGRESS.get(confession.status, 0),
            })
    reports.sort(key=lambda item: item['report'].submitted_at, reverse=True)

    paginator = Paginator(reports, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'reports': page_obj,
        'page_obj': page_obj,
        'total_count': concern_count + confession_count,
        'concern_count': concern_count,
        'confession_count': confession_count,
        'open_count': open_count,
        'resolved_count': resolved_count,
        'response_count': response_count,
        'filtered_count': paginator.count,
        'status_choices': ConcernStatus.choices,
        'current_status': status_filter,
        'current_type': report_type,
    }
    return render(request, 'my_reports.html', context)


@login_required(login_url='login')
def help_resources(request):
    """Show support and safety resources for SafeSpeak users."""
    return render(request, 'help_resources.html')


@login_required(login_url='login')
def privacy_guidelines(request):
    """Explain how anonymity works and the community guidelines."""
    return render(request, 'privacy_guidelines.html')


def _apply_user_codename(user, name):
    """Save or clear a custom code name and refresh the user's public posts."""
    with transaction.atomic():
        if name is None:
            UserCodeName.objects.filter(user=user).delete()
            name = generated_user_codename(user.pk)
        else:
            UserCodeName.objects.update_or_create(
                user=user,
                defaults={'name': name},
            )
        Concern.objects.filter(submitted_by=user).update(
            poster_codename=name,
        )
        Confession.objects.filter(submitted_by=user).update(
            poster_codename=name,
        )
        ReportComment.objects.filter(author=user).update(
            poster_codename=name,
        )
    return name


@login_required(login_url='login')
def my_account(request):
    """Let a signed-in user review their profile and change their password."""
    user = request.user
    profile_values = {
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
    }
    profile_errors = {}
    password_form = PasswordChangeForm(user)
    code_name = UserCodeName.objects.filter(user=user).first()
    codename_form = CodeNameForm(
        user,
        initial={'codename': code_name.name if code_name else ''},
    )

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'profile':
            profile_values = {
                'first_name': request.POST.get('first_name', '').strip(),
                'last_name': request.POST.get('last_name', '').strip(),
                'email': request.POST.get('email', '').strip(),
            }

            if len(profile_values['first_name']) > 150:
                profile_errors['first_name'] = (
                    'First name must be 150 characters or fewer.'
                )
            if len(profile_values['last_name']) > 150:
                profile_errors['last_name'] = (
                    'Last name must be 150 characters or fewer.'
                )

            email = profile_values['email']
            if email:
                if len(email) > 254:
                    profile_errors['email'] = (
                        'Email must be 254 characters or fewer.'
                    )
                else:
                    try:
                        validate_email(email)
                    except ValidationError:
                        profile_errors['email'] = 'Enter a valid email address.'
                    else:
                        duplicate = (
                            User.objects.filter(email__iexact=email)
                            .exclude(pk=user.pk)
                            .exists()
                        )
                        if duplicate:
                            profile_errors['email'] = (
                                'That email is already in use.'
                            )

            if not profile_errors:
                user.first_name = profile_values['first_name']
                user.last_name = profile_values['last_name']
                user.email = profile_values['email']
                user.save(
                    update_fields=['first_name', 'last_name', 'email']
                )
                messages.success(
                    request,
                    'Your account details have been updated.',
                )
                return redirect('my_account')

        elif action == 'codename':
            codename_form = CodeNameForm(user, data=request.POST)
            if codename_form.is_valid():
                try:
                    name = _apply_user_codename(
                        user,
                        codename_form.cleaned_data['codename'],
                    )
                except IntegrityError:
                    codename_form.add_error(
                        'codename',
                        'That code name is already in use.',
                    )
                else:
                    messages.success(
                        request,
                        f'Your community code name is now {name}.',
                    )
                    return redirect('my_account')

        elif action == 'reset_codename':
            name = _apply_user_codename(user, None)
            messages.success(
                request,
                f'Your community code name is back to {name}.',
            )
            return redirect('my_account')

        elif action == 'password':
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, 'Your password has been updated.')
                return redirect('my_account')

    for field in password_form.fields.values():
        field.widget.attrs.setdefault('class', 'form-control')
        # Keep the page at the top when the password form loads.
        field.widget.attrs.pop('autofocus', None)
    password_form.fields['old_password'].widget.attrs['autocomplete'] = (
        'current-password'
    )
    password_form.fields['new_password1'].widget.attrs['autocomplete'] = (
        'new-password'
    )
    password_form.fields['new_password2'].widget.attrs['autocomplete'] = (
        'new-password'
    )

    closed_statuses = [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]
    concerns = Concern.objects.filter(submitted_by=user)
    confessions = Confession.objects.filter(submitted_by=user)

    context = {
        'profile_values': profile_values,
        'profile_errors': profile_errors,
        'password_form': password_form,
        'codename_form': codename_form,
        'generated_codename': generated_user_codename(user.pk),
        'has_custom_codename': code_name is not None,
        'role_label': 'Administrator' if user.is_superuser else 'User',
        'linked_count': concerns.count() + confessions.count(),
        'open_count': (
            concerns.exclude(status__in=closed_statuses).count()
            + confessions.exclude(status__in=closed_statuses).count()
        ),
        'resolved_count': (
            concerns.filter(status=ConcernStatus.RESOLVED).count()
            + confessions.filter(status=ConcernStatus.RESOLVED).count()
        ),
        'response_count': (
            concerns.filter(response__isnull=False).count()
            + confessions.filter(response__isnull=False).count()
        ),
    }
    return render(request, 'my_account.html', context)


def _reports_queue_context(request):
    """Build shared report queue data for the admin and team dashboards."""
    concerns = Concern.objects.select_related('category', 'submitted_by').order_by('-submitted_at')
    confessions = Confession.objects.select_related('category', 'submitted_by').order_by('-submitted_at')

    # Summary statistics (always based on all reports, not the filtered set)
    closed_statuses = [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]
    total_concerns = concerns.count()
    total_confessions = confessions.count()

    stats = {
        'total_reports': total_concerns + total_confessions,
        'total_concerns': total_concerns,
        'total_confessions': total_confessions,
        'open_reports': (
            concerns.exclude(status__in=closed_statuses).count()
            + confessions.exclude(status__in=closed_statuses).count()
        ),
        'resolved_reports': (
            concerns.filter(status=ConcernStatus.RESOLVED).count()
            + confessions.filter(status=ConcernStatus.RESOLVED).count()
        ),
        'urgent_reports': (
            concerns.filter(is_urgent=True).exclude(status__in=closed_statuses).count()
            + confessions.filter(is_urgent=True).exclude(status__in=closed_statuses).count()
        ),
    }
    stats['resolution_rate'] = (
        round(stats['resolved_reports'] / stats['total_reports'] * 100)
        if stats['total_reports'] else 0
    )

    # Chart data for the dashboard overview (always unfiltered).
    week_start = timezone.localdate() - timedelta(days=6)
    week_days = [week_start + timedelta(days=offset) for offset in range(7)]

    def _daily_totals(model):
        rows = (
            model.objects.filter(submitted_at__date__gte=week_start)
            .annotate(day=TruncDate('submitted_at'))
            .values('day')
            .annotate(total=Count('id'))
        )
        return {row['day']: row['total'] for row in rows}

    concern_days = _daily_totals(Concern)
    confession_days = _daily_totals(Confession)
    weekly_concerns = [concern_days.get(day, 0) for day in week_days]
    weekly_confessions = [confession_days.get(day, 0) for day in week_days]
    stats['new_this_week'] = sum(weekly_concerns) + sum(weekly_confessions)

    status_breakdown = _status_breakdown(
        Concern.objects.all(),
        Confession.objects.all(),
    )

    # Filter by status if requested
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        concerns = concerns.filter(status=status_filter)
        confessions = confessions.filter(status=status_filter)

    # Filter by category if requested
    category_filter = request.GET.get('category', '').strip()
    if category_filter and category_filter.isdigit():
        concerns = concerns.filter(category_id=category_filter)
        confessions = confessions.filter(category_id=category_filter)
    else:
        category_filter = ''

    # Search by title or description
    query = request.GET.get('q', '').strip()
    if query:
        search = Q(title__icontains=query) | Q(description__icontains=query)
        concerns = concerns.filter(search)
        confessions = confessions.filter(search)

    categories = Category.objects.filter(is_active=True)

    return {
        **stats,
        'concerns': concerns,
        'confessions': confessions,
        'categories': categories,
        'status_choices': ConcernStatus.choices,
        'current_status': status_filter,
        'current_category': category_filter,
        'query': query,
        'filtered_total': concerns.count() + confessions.count(),
        'status_breakdown': status_breakdown,
        'weekly_labels': [day.strftime('%b %d') for day in week_days],
        'weekly_concerns': weekly_concerns,
        'weekly_confessions': weekly_confessions,
    }


@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
@never_cache
def admin_dashboard(request):
    """Admin dashboard to view and manage all submitted concerns and confessions."""
    context = _reports_queue_context(request)
    context['recent_activity'] = (
        AdminActivityLog.objects
        .select_related('actor', 'target_user', 'concern', 'confession')
        .order_by('-created_at')[:6]
    )
    context['category_folders'] = _category_folders(6)
    context['recent_report_cards'] = _recent_report_cards(4)
    return render(request, 'admin_dashboard.html', context)


@login_required(login_url='login')
@user_passes_test(_is_team_member, login_url='dashboard')
def team_management(request):
    """Hub for the SafeSpeak administrators' management tools."""
    closed_statuses = [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]
    total_reports = Concern.objects.count() + Confession.objects.count()
    open_reports = (
        Concern.objects.exclude(status__in=closed_statuses).count()
        + Confession.objects.exclude(status__in=closed_statuses).count()
    )

    context = {
        'manage_reports_url': reverse('admin_dashboard'),
        'can_manage_users': True,
        'total_reports': total_reports,
        'open_reports': open_reports,
        'activity_count': AdminActivityLog.objects.count(),
        'user_count': User.objects.count(),
        'category_count': Category.objects.filter(is_active=True).count(),
    }
    return render(request, 'team_management.html', context)


@login_required(login_url='login')
@user_passes_test(_is_team_member, login_url='dashboard')
def admin_report_detail(request, kind, pk):
    """View a single report and manage its status, response, and internal notes."""
    if kind == 'concern':
        report = get_object_or_404(Concern.objects.prefetch_related('images'), pk=pk)
        kind_label = 'Concern'
        response_model = ConcernResponse
        response_field = 'concern'
    elif kind == 'confession':
        report = get_object_or_404(Confession.objects.prefetch_related('images'), pk=pk)
        kind_label = 'Confession'
        response_model = ConfessionResponse
        response_field = 'confession'
    else:
        raise Http404('Unknown report type.')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'status':
            new_status = request.POST.get('status', '')
            if new_status in dict(ConcernStatus.choices):
                if new_status != report.status:
                    log_admin_activity(
                        request.user,
                        AdminAction.STATUS_CHANGED,
                        report=report,
                        old_value=report.get_status_display(),
                        new_value=dict(ConcernStatus.choices)[new_status],
                    )
                report.status = new_status
                report.resolved_at = (
                    timezone.now()
                    if new_status in [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]
                    else None
                )
                report.save(update_fields=['status', 'resolved_at', 'updated_at'])
                messages.success(
                    request,
                    f'{kind_label} "{report.title}" status updated to '
                    f'{dict(ConcernStatus.choices)[new_status]}.'
                )
            else:
                messages.error(request, 'Invalid status selected.')

        elif action == 'response':
            message = request.POST.get('message', '').strip()
            if not message:
                messages.error(request, 'Response message is required.')
            else:
                is_public = request.POST.get('is_public', '') == 'on'
                response_model.objects.update_or_create(
                    **{response_field: report},
                    defaults={
                        'message': message,
                        'is_public': is_public,
                        'responded_by': request.user,
                    },
                )
                log_admin_activity(
                    request.user,
                    AdminAction.RESPONSE_SAVED,
                    report=report,
                    new_value='Public' if is_public else 'Private',
                    detail=message,
                )
                messages.success(
                    request,
                    f'Response saved for {kind_label.lower()} "{report.title}".'
                )

        elif action == 'note' and kind == 'concern':
            body = request.POST.get('body', '').strip()
            if not body:
                messages.error(request, 'Note cannot be empty.')
            else:
                ConcernNote.objects.create(
                    concern=report,
                    body=body,
                    author=request.user,
                )
                log_admin_activity(
                    request.user,
                    AdminAction.NOTE_ADDED,
                    report=report,
                    detail=body,
                )
                messages.success(request, 'Internal note added.')

        else:
            messages.error(request, 'Unknown action.')

        return redirect('admin_report_detail', kind=kind, pk=pk)

    context = {
        'report': report,
        'kind': kind,
        'kind_label': kind_label,
        'status_choices': ConcernStatus.choices,
        'response': getattr(report, 'response', None),
        'notes': report.notes.select_related('author') if kind == 'concern' else ConcernNote.objects.none(),
        'activity_logs': report.activity_logs.select_related('actor')[:10],
        'back_url': reverse('admin_dashboard'),
        'can_view_activity_history': _is_team_member(request.user),
    }
    return render(request, 'admin_report_detail.html', context)


@login_required(login_url='login')
@user_passes_test(_is_team_member, login_url='dashboard')
def admin_add_concern_response(request, pk):
    """Admin endpoint to create or update a response to a concern."""
    concern = get_object_or_404(Concern, pk=pk)

    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        is_public = request.POST.get('is_public', '') == 'on'

        if not message:
            messages.error(request, 'Response message is required.')
            return HttpResponseRedirect(reverse('admin_report_detail', args=['concern', concern.pk]))

        ConcernResponse.objects.update_or_create(
            concern=concern,
            defaults={
                'message': message,
                'is_public': is_public,
                'responded_by': request.user,
            },
        )
        log_admin_activity(
            request.user,
            AdminAction.RESPONSE_SAVED,
            report=concern,
            new_value='Public' if is_public else 'Private',
            detail=message,
        )
        messages.success(request, f'Response saved for concern "{concern.title}".')
        return HttpResponseRedirect(reverse('admin_report_detail', args=['concern', concern.pk]))

    return HttpResponseRedirect(reverse('admin_report_detail', args=['concern', concern.pk]))


@login_required(login_url='login')
@user_passes_test(_is_team_member, login_url='dashboard')
def admin_add_confession_response(request, pk):
    """Admin endpoint to create or update a response to a confession."""
    confession = get_object_or_404(Confession, pk=pk)

    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        is_public = request.POST.get('is_public', '') == 'on'

        if not message:
            messages.error(request, 'Response message is required.')
            return HttpResponseRedirect(reverse('admin_report_detail', args=['confession', confession.pk]))

        ConfessionResponse.objects.update_or_create(
            confession=confession,
            defaults={
                'message': message,
                'is_public': is_public,
                'responded_by': request.user,
            },
        )
        log_admin_activity(
            request.user,
            AdminAction.RESPONSE_SAVED,
            report=confession,
            new_value='Public' if is_public else 'Private',
            detail=message,
        )
        messages.success(request, f'Response saved for confession "{confession.title}".')
        return HttpResponseRedirect(reverse('admin_report_detail', args=['confession', confession.pk]))

    return HttpResponseRedirect(reverse('admin_report_detail', args=['confession', confession.pk]))


@login_required(login_url='login')
@user_passes_test(_is_team_member, login_url='dashboard')
def admin_update_status(request, pk):
    """Admin endpoint to update concern status."""
    concern = get_object_or_404(Concern, pk=pk)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status and new_status in dict(ConcernStatus.choices):
            if new_status != concern.status:
                log_admin_activity(
                    request.user,
                    AdminAction.STATUS_CHANGED,
                    report=concern,
                    old_value=concern.get_status_display(),
                    new_value=dict(ConcernStatus.choices)[new_status],
                )
            concern.status = new_status
            concern.resolved_at = timezone.now() if new_status in ['RESOLVED', 'DISMISSED'] else None
            concern.save(update_fields=['status', 'resolved_at', 'updated_at'])
            messages.success(request, f'Concern "{concern.title}" status updated to {dict(ConcernStatus.choices)[new_status]}')
        else:
            messages.error(request, 'Invalid status selected.')

    return HttpResponseRedirect(reverse('admin_report_detail', args=['concern', concern.pk]))


@login_required(login_url='login')
@user_passes_test(_is_team_member, login_url='dashboard')
def admin_update_confession_status(request, pk):
    """Admin endpoint to update confession status."""
    confession = get_object_or_404(Confession, pk=pk)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status and new_status in dict(ConcernStatus.choices):
            if new_status != confession.status:
                log_admin_activity(
                    request.user,
                    AdminAction.STATUS_CHANGED,
                    report=confession,
                    old_value=confession.get_status_display(),
                    new_value=dict(ConcernStatus.choices)[new_status],
                )
            confession.status = new_status
            confession.resolved_at = timezone.now() if new_status in ['RESOLVED', 'DISMISSED'] else None
            confession.save(update_fields=['status', 'resolved_at', 'updated_at'])
            messages.success(request, f'Confession "{confession.title}" status updated to {dict(ConcernStatus.choices)[new_status]}')
        else:
            messages.error(request, 'Invalid status selected.')

    return HttpResponseRedirect(reverse('admin_report_detail', args=['confession', confession.pk]))


@login_required(login_url='login')
@user_passes_test(_is_team_member, login_url='dashboard')
def admin_activity_history(request):
    """Chronological audit trail of report and account activity."""
    logs = AdminActivityLog.objects.select_related('actor', 'target_user', 'concern', 'confession')

    action_filter = request.GET.get('action', '').strip()
    if action_filter in dict(AdminAction.choices):
        logs = logs.filter(action=action_filter)
    else:
        action_filter = ''

    query = request.GET.get('q', '').strip()
    if query:
        logs = logs.filter(
            Q(actor__username__icontains=query)
            | Q(target_user__username__icontains=query)
            | Q(concern__title__icontains=query)
            | Q(confession__title__icontains=query)
            | Q(detail__icontains=query)
        )

    paginator = Paginator(logs, 20)
    page = paginator.get_page(request.GET.get('page', 1))

    context = {
        'logs': page,
        'action_choices': AdminAction.choices,
        'current_action': action_filter,
        'query': query,
        'total_count': paginator.count,
        'back_url': reverse('team_management'),
    }
    return render(request, 'admin_activity_history.html', context)


def home(request):
    """Public feed plus personal progress for signed-in users."""
    concerns = Concern.objects.all()
    confessions = Confession.objects.all()

    # Build a single chronological timeline for the feed.
    feed = []
    for concern in concerns.select_related('category').prefetch_related('comments', 'images').order_by('-submitted_at')[:15]:
        feed.append({'kind': 'concern', 'label': 'Concern', 'report': concern})
    for confession in confessions.select_related('category').prefetch_related('comments', 'images').order_by('-submitted_at')[:15]:
        feed.append({'kind': 'confession', 'label': 'Confession', 'report': confession})
    feed.sort(key=lambda item: item['report'].submitted_at, reverse=True)
    feed = feed[:15]

    for item in feed:
        comments = list(item['report'].comments.all())
        item['comments'] = comments
        item['comment_count'] = len(comments)

    # Personal, linked-report summary (signed-in users only).
    if request.user.is_authenticated:
        my_concerns = Concern.objects.filter(submitted_by=request.user)
        my_confessions = Confession.objects.filter(submitted_by=request.user)
        closed_statuses = [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]
        my_total = my_concerns.count() + my_confessions.count()
        my_open = (
            my_concerns.exclude(status__in=closed_statuses).count()
            + my_confessions.exclude(status__in=closed_statuses).count()
        )
        my_resolved = (
            my_concerns.filter(status=ConcernStatus.RESOLVED).count()
            + my_confessions.filter(status=ConcernStatus.RESOLVED).count()
        )
        my_responses = (
            my_concerns.filter(response__isnull=False).count()
            + my_confessions.filter(response__isnull=False).count()
        )
        my_resolution_rate = round(my_resolved / my_total * 100) if my_total else 0
        my_recent_reports = _user_report_cards(request.user, 5)
    else:
        closed_statuses = [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]
        my_total = my_open = my_resolved = my_responses = 0
        my_resolution_rate = 0
        my_recent_reports = []

    # Community-wide pulse used by the progress ring and status bars.
    community_total = concerns.count() + confessions.count()
    community_open = (
        concerns.exclude(status__in=closed_statuses).count()
        + confessions.exclude(status__in=closed_statuses).count()
    )
    community_resolved = (
        concerns.filter(status=ConcernStatus.RESOLVED).count()
        + confessions.filter(status=ConcernStatus.RESOLVED).count()
    )
    community_resolution_rate = (
        round(community_resolved / community_total * 100)
        if community_total else 0
    )

    context = {
        'feed': feed,
        'greeting': _greeting(),
        'my_total': my_total,
        'my_open': my_open,
        'my_resolved': my_resolved,
        'my_responses': my_responses,
        'my_resolution_rate': my_resolution_rate,
        'my_recent_reports': my_recent_reports,
        'community_total': community_total,
        'community_open': community_open,
        'community_resolved': community_resolved,
        'community_resolution_rate': community_resolution_rate,
        'community_status_breakdown': _status_breakdown(concerns, confessions),
        'category_folders': _category_folders(6),
    }
    return render(request, 'home.html', context)


@login_required(login_url='login')
@require_POST
def add_comment(request, kind, pk):
    """Add an anonymous comment to a concern or confession."""
    if kind == 'concern':
        report = get_object_or_404(Concern, pk=pk)
        parent = {'concern': report}
    elif kind == 'confession':
        report = get_object_or_404(Confession, pk=pk)
        parent = {'confession': report}
    else:
        raise Http404

    body = request.POST.get('body', '').strip()

    if not body:
        messages.error(request, 'Comment cannot be empty.')
        return HttpResponseRedirect(reverse('dashboard'))

    if len(body) > 1000:
        messages.error(request, 'Comment must be 1000 characters or fewer.')
        return HttpResponseRedirect(reverse('dashboard'))

    ReportComment.objects.create(
        author=request.user,
        body=body,
        poster_codename=user_codename(request.user.pk),
        **parent,
    )

    if request.user.is_superuser:
        log_admin_activity(
            request.user,
            AdminAction.COMMENT_ADDED,
            report=report,
            detail=body,
        )

    return HttpResponseRedirect(
        f"{reverse('dashboard')}#report-{kind}-{report.pk}"
    )


def _comment_anchor(comment):
    """Return the feed anchor for the report a comment belongs to."""
    if comment.concern_id is not None:
        return f'report-concern-{comment.concern_id}'
    return f'report-confession-{comment.confession_id}'


def _can_manage_comment(user, comment):
    """Allow the comment author or a superuser to change a comment."""
    return user.is_superuser or (
        comment.author_id is not None and comment.author_id == user.pk
    )


@login_required(login_url='login')
@require_POST
def edit_comment(request, pk):
    """Edit a comment owned by the current user, or moderate one as an administrator."""
    comment = get_object_or_404(ReportComment, pk=pk)

    if not _can_manage_comment(request.user, comment):
        return HttpResponseForbidden('You can only edit your own comments.')

    body = request.POST.get('body', '').strip()

    if not body:
        messages.error(request, 'Comment cannot be empty.')
        return HttpResponseRedirect(reverse('dashboard'))

    if len(body) > 1000:
        messages.error(request, 'Comment must be 1000 characters or fewer.')
        return HttpResponseRedirect(reverse('dashboard'))

    if body != comment.body:
        comment.body = body
        comment.is_edited = True
        comment.save(update_fields=['body', 'is_edited'])

        if request.user.is_superuser and comment.author_id != request.user.pk:
            log_admin_activity(
                request.user,
                AdminAction.COMMENT_EDITED,
                report=comment.concern or comment.confession,
                detail=f'Moderated a comment: "{body[:200]}"',
            )

    return HttpResponseRedirect(
        f"{reverse('dashboard')}#{_comment_anchor(comment)}"
    )


@login_required(login_url='login')
@require_POST
def delete_comment(request, pk):
    """Delete a comment owned by the current user, or moderate one as an administrator."""
    comment = get_object_or_404(ReportComment, pk=pk)

    if not _can_manage_comment(request.user, comment):
        return HttpResponseForbidden('You can only delete your own comments.')

    anchor = _comment_anchor(comment)
    if request.user.is_superuser and comment.author_id != request.user.pk:
        log_admin_activity(
            request.user,
            AdminAction.COMMENT_DELETED,
            report=comment.concern or comment.confession,
            detail=f'Deleted a comment: "{comment.body[:200]}"',
        )
    comment.delete()
    return HttpResponseRedirect(f"{reverse('dashboard')}#{anchor}")


@require_http_methods(['GET', 'POST'])
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'GET':
        return render(request, 'auth/register.html')

    form_data = {
        'username': request.POST.get('username', ''),
        'first_name': request.POST.get('first_name', ''),
        'last_name': request.POST.get('last_name', ''),
        'email': request.POST.get('email', ''),
        'password': request.POST.get('password', ''),
        'confirm_password': request.POST.get('confirm_password', ''),
    }

    errors = _validate_registration_data(form_data)
    if errors:
        return render(request, 'auth/register.html', {'errors': errors, 'form_data': form_data})

    user = User.objects.create_user(
        username=form_data['username'].strip(),
        first_name=form_data['first_name'].strip(),
        last_name=form_data['last_name'].strip(),
        email=form_data['email'].strip(),
        password=form_data['password'],
    )
    login(request, user)
    return redirect('dashboard')
