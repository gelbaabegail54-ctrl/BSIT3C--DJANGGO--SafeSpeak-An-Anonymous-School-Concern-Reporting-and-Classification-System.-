from django.shortcuts import render
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import IntegrityError
from django.db.models import Q
from django.views.decorators.http import require_POST


VALID_ROLES = {'instructor', 'staff', 'admin'}


def _is_superuser(user):
    return user.is_superuser


def _user_role(user):
    if user.is_superuser:
        return 'admin'
    if user.is_staff:
        return 'staff'
    return 'instructor'


def _other_active_admins(user):
    return User.objects.filter(
        is_superuser=True,
        is_active=True,
    ).exclude(pk=user.pk)


def _serialize_user(user):
    return {
        'id': user.id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'is_active': user.is_active,
        'role': _user_role(user),
        'date_joined': user.date_joined,
    }


# PAGE
@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
def user_list_page(request):
    query = request.GET.get('q', '').strip()

    users_list = User.objects.all().order_by('-date_joined')

    if query:
        users_list = users_list.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )

    paginator = Paginator(users_list, 10)
    page_number = request.GET.get('page', 1)
    users = paginator.get_page(page_number)

    return render(request, 'users/list.html', {
        'users': users,
        'query': query,
    })


# LIST USERS (AJAX)
@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
def user_list_ajax(request):
    users_list = User.objects.all().order_by('-date_joined')
    paginator = Paginator(users_list, 10)
    page_number = request.GET.get('page', 1)
    users = paginator.get_page(page_number)
    data = [_serialize_user(user) for user in users.object_list]
    return JsonResponse({
        "data":     data,
        "has_next": users.has_next(),
        "has_prev": users.has_previous(),
        "page":     users.number,
        "pages":    users.paginator.num_pages,
        "total":    users.paginator.count,
    })


# GET SINGLE USER (AJAX)
@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
def user_get_ajax(request, pk):
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found."}, status=404)

    return JsonResponse(_serialize_user(user))


# CREATE / UPDATE USER (AJAX)
@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
@require_POST
def user_save_ajax(request):
    user_id = request.POST.get("id")

    if user_id:
        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, TypeError, ValueError):
            return JsonResponse({"error": "User not found."}, status=404)
        is_update = True
    else:
        user = User()
        is_update = False

    username = request.POST.get("username", "").strip()
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    email = request.POST.get("email", "").strip()
    role = request.POST.get("role", "instructor").strip().lower()
    is_active = request.POST.get("is_active") == "true"

    if not username:
        return JsonResponse({"error": "Username is required."}, status=400)

    if role not in VALID_ROLES:
        return JsonResponse({"error": "Please choose a valid role."}, status=400)

    if email:
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({"error": "Please enter a valid email address."}, status=400)

    duplicate_users = User.objects.all()
    if is_update:
        duplicate_users = duplicate_users.exclude(pk=user.pk)

    if duplicate_users.filter(username__iexact=username).exists():
        return JsonResponse({"error": "That username is already taken."}, status=400)

    if email and duplicate_users.filter(email__iexact=email).exists():
        return JsonResponse({"error": "That email is already in use."}, status=400)

    if is_update:
        if user.pk == request.user.pk and not is_active:
            return JsonResponse(
                {"error": "You cannot deactivate your own account."},
                status=400,
            )

        if user.pk == request.user.pk and role != 'admin':
            return JsonResponse(
                {"error": "You cannot remove your own administrator access."},
                status=400,
            )

        # Never allow the final active administrator to lose that access.
        if user.is_superuser and user.is_active and (role != 'admin' or not is_active):
            if not _other_active_admins(user).exists():
                return JsonResponse(
                    {"error": "At least one active administrator is required."},
                    status=400,
                )

    password = request.POST.get("password")
    if not is_update and not password:
        return JsonResponse({"error": "Password is required for new users."}, status=400)

    if password:
        user.set_password(password)

    user.username = username
    user.first_name = first_name
    user.last_name = last_name
    user.email = email
    user.is_active = is_active
    user.is_superuser = role == 'admin'
    user.is_staff = role in ('admin', 'staff')

    try:
        user.save()
    except IntegrityError:
        return JsonResponse(
            {"error": "Could not save user due to a conflict (duplicate username/email)."},
            status=400,
        )

    messages.success(
        request,
        f'User "{user.username}" has been '
        f'{"updated" if is_update else "created"} successfully.'
    )

    return JsonResponse({
        "status": "success",
        **_serialize_user(user),
    })


# DELETE USER (AJAX)
@login_required(login_url='login')
@user_passes_test(_is_superuser, login_url='dashboard')
@require_POST
def user_delete_ajax(request, pk):
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found."}, status=404)

    if request.user == user:
        return JsonResponse({"error": "You cannot delete your own account."}, status=400)

    # Keep a working administrator account at all times.
    if user.is_superuser and user.is_active and not _other_active_admins(user).exists():
        return JsonResponse(
            {"error": "You cannot delete the last active administrator."},
            status=400,
        )

    username = user.username
    user.delete()
    return JsonResponse({
        "status": "deleted",
        "message": f'User "{username}" has been deleted successfully.',
    })
