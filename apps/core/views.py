from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.urls import reverse
from apps.users.views import _is_superuser

from .models import (
    Category,
    Concern,
    ConcernNote,
    ConcernResponse,
    ConcernStatus,
    Confession,
    ConfessionResponse,
    ReportComment,
)

User = get_user_model()

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=1)
INVALID_LOGIN_MESSAGE = 'Invalid username or password.'
LOCKED_MESSAGE = 'Too many failed attempts. Locked for 1 minute.'


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


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    failed_attempts, remaining = _get_lock_state(request)
    if remaining is not None:
        messages.error(request, f'Too many failed attempts. Try again in {remaining} seconds.')
        return render(request, 'auth/login.html', {'locked': True, 'remaining': remaining})

    if request.method == 'GET':
        return render(request, 'auth/login.html')

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    user = authenticate(request, username=username, password=password)

    if user is not None:
        _reset_lock_state(request)
        login(request, user)
        return redirect('dashboard')

    failed_attempts += 1
    request.session['failed_attempts'] = failed_attempts
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        remaining = _set_lock_state(request)
        messages.error(request, LOCKED_MESSAGE)
        return render(request, 'auth/login.html', {'locked': True, 'remaining': remaining})

    remaining_attempts = MAX_FAILED_ATTEMPTS - failed_attempts
    messages.error(request, f'{INVALID_LOGIN_MESSAGE} {remaining_attempts} attempts remaining.')
    return render(request, 'auth/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


CONCERN_CLASSIFICATION_RULES = (
    ('Bullying', ('bully', 'bullying', 'harass', 'harassment', 'threat', 'intimidat', 'fight', 'violence')),
    ('Safety', ('safety', 'unsafe', 'danger', 'fire', 'accident', 'injury', 'weapon', 'emergency', 'hazard')),
    ('Facilities', (
        'facility', 'facilities', 'broken', 'damage', 'classroom', 'building', 'restroom',
        'canteen', 'chair', 'desk', 'electric', 'water', 'leak', 'aircon', 'fan', 'light',
    )),
    ('Academic', (
        'academic', 'grade', 'teacher', 'class', 'exam', 'assignment', 'lesson',
        'curriculum', 'subject', 'homework',
    )),
    ('Personal', (
        'personal', 'family', 'friend', 'stress', 'mental', 'emotional', 'relationship',
        'depress', 'anxiety',
    )),
)


def _derive_title(description):
    """Build a short report title from the first line of the description."""
    first_line = description.strip().splitlines()[0] if description.strip() else ''
    snippet = ' '.join(first_line.split())
    if len(snippet) > 80:
        return snippet[:77].rstrip() + '...'
    return snippet


def _classify_report(description):
    """Assign an active category using simple keyword classification."""
    text = description.lower()

    for category_name, keywords in CONCERN_CLASSIFICATION_RULES:
        if any(keyword in text for keyword in keywords):
            category = Category.objects.filter(name__iexact=category_name, is_active=True).first()
            if category is not None:
                return category

    return Category.objects.get_or_create(
        name='General',
        defaults={'description': 'Automatically assigned when no other category matches.'},
    )[0]


def submit_concern(request):
    """Allow anonymous submission of a concern report."""
    if request.method == 'GET':
        return render(request, 'submit_concern.html')

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        is_urgent = request.POST.get('is_urgent', '') == 'on'

        if not description:
            messages.error(request, 'Description is required.')
            return render(request, 'submit_concern.html')

        concern = Concern.objects.create(
            title=_derive_title(description),
            description=description,
            category=_classify_report(description),
            location_on_campus='',
            date_of_incident=None,
            is_urgent=is_urgent,
            status=ConcernStatus.SUBMITTED,
            submitted_by=None,  # Anonymous submission
        )

        messages.success(request, f'Your concern has been submitted. Ticket number: {concern.ticket_number}')
        return render(request, 'submit_concern.html', {
            'submission_successful': True,
            'ticket_number': concern.ticket_number,
        })


def submit_confession(request):
    """Allow anonymous submission of a confession."""
    if request.method == 'GET':
        return render(request, 'submit_confession.html')

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        is_urgent = request.POST.get('is_urgent', '') == 'on'

        if not description:
            messages.error(request, 'Description is required.')
            return render(request, 'submit_confession.html')

        confession = Confession.objects.create(
            title=_derive_title(description),
            description=description,
            category=_classify_report(description),
            location_on_campus='',
            date_of_incident=None,
            is_urgent=is_urgent,
            status=ConcernStatus.SUBMITTED,
            submitted_by=None,  # Anonymous submission
        )

        messages.success(request, f'Your confession has been submitted. Ticket number: {confession.ticket_number}')
        return render(request, 'submit_confession.html', {
            'submission_successful': True,
            'ticket_number': confession.ticket_number,
        })


@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
def admin_dashboard(request):
    """Admin dashboard to view and manage all submitted concerns and confessions."""
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

    status_colors = {
        ConcernStatus.SUBMITTED: '#4f46e5',
        ConcernStatus.UNDER_REVIEW: '#c77a0a',
        ConcernStatus.IN_PROGRESS: '#0e8fa8',
        ConcernStatus.RESOLVED: '#17945b',
        ConcernStatus.DISMISSED: '#d64545',
    }
    concern_status_counts = {
        status: total
        for status, total in Concern.objects.values_list('status').annotate(total=Count('id'))
    }
    confession_status_counts = {
        status: total
        for status, total in Confession.objects.values_list('status').annotate(total=Count('id'))
    }
    status_breakdown = [
        {
            'code': code,
            'label': label,
            'total': concern_status_counts.get(code, 0) + confession_status_counts.get(code, 0),
            'color': status_colors.get(code, '#6e7591'),
        }
        for code, label in ConcernStatus.choices
    ]

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

    # Search by ticket number, title, or description
    query = request.GET.get('q', '').strip()
    if query:
        search = Q(ticket_number__icontains=query) | Q(title__icontains=query) | Q(description__icontains=query)
        concerns = concerns.filter(search)
        confessions = confessions.filter(search)

    categories = Category.objects.filter(is_active=True)

    context = {
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
    return render(request, 'admin_dashboard.html', context)


@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
def admin_report_detail(request, kind, pk):
    """View a single report and manage its status, response, and internal notes."""
    if kind == 'concern':
        report = get_object_or_404(Concern, pk=pk)
        kind_label = 'Concern'
        response_model = ConcernResponse
        response_field = 'concern'
    elif kind == 'confession':
        report = get_object_or_404(Confession, pk=pk)
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
                report.status = new_status
                report.resolved_at = (
                    timezone.now()
                    if new_status in [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]
                    else None
                )
                report.save(update_fields=['status', 'resolved_at', 'updated_at'])
                messages.success(
                    request,
                    f'{kind_label} "{report.ticket_number}" status updated to '
                    f'{dict(ConcernStatus.choices)[new_status]}.'
                )
            else:
                messages.error(request, 'Invalid status selected.')

        elif action == 'response':
            message = request.POST.get('message', '').strip()
            if not message:
                messages.error(request, 'Response message is required.')
            else:
                response_model.objects.update_or_create(
                    **{response_field: report},
                    defaults={
                        'message': message,
                        'is_public': request.POST.get('is_public', '') == 'on',
                        'responded_by': request.user,
                    },
                )
                messages.success(
                    request,
                    f'Response saved for {kind_label.lower()} "{report.ticket_number}".'
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
    }
    return render(request, 'admin_report_detail.html', context)


@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
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
        messages.success(request, f'Response saved for concern "{concern.ticket_number}".')
        return HttpResponseRedirect(reverse('admin_report_detail', args=['concern', concern.pk]))

    return HttpResponseRedirect(reverse('admin_report_detail', args=['concern', concern.pk]))


@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
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
        messages.success(request, f'Response saved for confession "{confession.ticket_number}".')
        return HttpResponseRedirect(reverse('admin_report_detail', args=['confession', confession.pk]))

    return HttpResponseRedirect(reverse('admin_report_detail', args=['confession', confession.pk]))


@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
def admin_update_status(request, pk):
    """Admin endpoint to update concern status."""
    concern = get_object_or_404(Concern, pk=pk)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status and new_status in dict(ConcernStatus.choices):
            concern.status = new_status
            concern.resolved_at = timezone.now() if new_status in ['RESOLVED', 'DISMISSED'] else None
            concern.save(update_fields=['status', 'resolved_at', 'updated_at'])
            messages.success(request, f'Concern "{concern.ticket_number}" status updated to {dict(ConcernStatus.choices)[new_status]}')
        else:
            messages.error(request, 'Invalid status selected.')

    return HttpResponseRedirect(reverse('admin_report_detail', args=['concern', concern.pk]))


@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
def admin_update_confession_status(request, pk):
    """Admin endpoint to update confession status."""
    confession = get_object_or_404(Confession, pk=pk)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status and new_status in dict(ConcernStatus.choices):
            confession.status = new_status
            confession.resolved_at = timezone.now() if new_status in ['RESOLVED', 'DISMISSED'] else None
            confession.save(update_fields=['status', 'resolved_at', 'updated_at'])
            messages.success(request, f'Confession "{confession.ticket_number}" status updated to {dict(ConcernStatus.choices)[new_status]}')
        else:
            messages.error(request, 'Invalid status selected.')

    return HttpResponseRedirect(reverse('admin_report_detail', args=['confession', confession.pk]))


@login_required(login_url='login')
def home(request):
    """Dashboard with live statistics and the latest submissions."""
    concerns = Concern.objects.all()
    confessions = Confession.objects.all()

    closed_statuses = [ConcernStatus.RESOLVED, ConcernStatus.DISMISSED]

    total_concerns = concerns.count()
    total_confessions = confessions.count()

    open_reports = (
        concerns.exclude(status__in=closed_statuses).count()
        + confessions.exclude(status__in=closed_statuses).count()
    )
    resolved_reports = (
        concerns.filter(status=ConcernStatus.RESOLVED).count()
        + confessions.filter(status=ConcernStatus.RESOLVED).count()
    )
    urgent_reports = (
        concerns.filter(is_urgent=True).exclude(status__in=closed_statuses).count()
        + confessions.filter(is_urgent=True).exclude(status__in=closed_statuses).count()
    )

    status_breakdown = []
    for code, label in ConcernStatus.choices:
        status_breakdown.append({
            'code': code,
            'label': label,
            'count': concerns.filter(status=code).count() + confessions.filter(status=code).count(),
        })

    category_stats = []
    for category in Category.objects.filter(is_active=True):
        concern_count = concerns.filter(category=category).count()
        confession_count = confessions.filter(category=category).count()
        category_stats.append({
            'name': category.name,
            'concerns': concern_count,
            'confessions': confession_count,
            'total': concern_count + confession_count,
        })

    # Show the most active categories first and normalize counts so the
    # largest category fills the progress bar.
    category_stats.sort(key=lambda row: row['total'], reverse=True)
    max_category_total = max((row['total'] for row in category_stats), default=0)
    for row in category_stats:
        row['percent'] = round(row['total'] * 100 / max_category_total) if max_category_total else 0

    # Build a single chronological timeline for the feed.
    feed = []
    for concern in concerns.select_related('category').prefetch_related('comments').order_by('-submitted_at')[:15]:
        feed.append({'kind': 'concern', 'label': 'Concern', 'report': concern})
    for confession in confessions.select_related('category').prefetch_related('comments').order_by('-submitted_at')[:15]:
        feed.append({'kind': 'confession', 'label': 'Confession', 'report': confession})
    feed.sort(key=lambda item: item['report'].submitted_at, reverse=True)
    feed = feed[:15]

    for item in feed:
        comments = list(item['report'].comments.all())
        item['comments'] = comments
        item['comment_count'] = len(comments)

    context = {
        'total_reports': total_concerns + total_confessions,
        'total_concerns': total_concerns,
        'total_confessions': total_confessions,
        'open_reports': open_reports,
        'resolved_reports': resolved_reports,
        'urgent_reports': urgent_reports,
        'status_breakdown': status_breakdown,
        'category_stats': category_stats,
        'feed': feed,
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
        **parent,
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
    """Edit a comment owned by the current user, or moderate one as staff."""
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

    return HttpResponseRedirect(
        f"{reverse('dashboard')}#{_comment_anchor(comment)}"
    )


@login_required(login_url='login')
@require_POST
def delete_comment(request, pk):
    """Delete a comment owned by the current user, or moderate one as staff."""
    comment = get_object_or_404(ReportComment, pk=pk)

    if not _can_manage_comment(request.user, comment):
        return HttpResponseForbidden('You can only delete your own comments.')

    anchor = _comment_anchor(comment)
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
