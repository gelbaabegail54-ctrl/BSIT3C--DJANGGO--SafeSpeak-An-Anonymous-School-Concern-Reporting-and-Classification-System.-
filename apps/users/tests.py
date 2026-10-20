import apps.py314_compat  # noqa: F401  (Python 3.14 / Django 5.0 test-client fix)

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='AdminPass123!',
            is_staff=True,
            is_superuser=True,
        )
        self.member = User.objects.create_user(
            username='member',
            email='member@example.com',
            password='MemberPass123!',
        )
        self.client.force_login(self.admin)

    def post_save(self, **overrides):
        data = {
            'username': 'newmember',
            'first_name': 'New',
            'last_name': 'Member',
            'email': 'newmember@example.com',
            'password': 'NewMemberPass123!',
            'role': 'instructor',
            'is_active': 'true',
        }
        data.update(overrides)
        return self.client.post(reverse('users:user_save_ajax'), data)

    def test_list_ajax_includes_roles(self):
        response = self.client.get(reverse('users:user_list_ajax'))

        self.assertEqual(response.status_code, 200)
        roles = {row['username']: row['role'] for row in response.json()['data']}
        self.assertEqual(roles['admin'], 'admin')
        self.assertEqual(roles['member'], 'instructor')

    def test_get_ajax_includes_role(self):
        response = self.client.get(
            reverse('users:user_get_ajax', args=[self.member.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['role'], 'instructor')
        self.assertFalse(response.json()['is_superuser'])

    def test_create_instructor(self):
        response = self.post_save()

        self.assertEqual(response.status_code, 200)
        created = User.objects.get(username='newmember')
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

    def test_create_staff(self):
        response = self.post_save(role='staff')

        self.assertEqual(response.status_code, 200)
        created = User.objects.get(username='newmember')
        self.assertTrue(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertEqual(response.json()['role'], 'staff')

    def test_create_administrator(self):
        response = self.post_save(role='admin')

        self.assertEqual(response.status_code, 200)
        created = User.objects.get(username='newmember')
        self.assertTrue(created.is_staff)
        self.assertTrue(created.is_superuser)
        self.assertEqual(response.json()['role'], 'admin')

    def test_update_role(self):
        response = self.post_save(
            id=self.member.pk,
            username='member',
            email='member@example.com',
            password='',
            role='admin',
            is_active='true',
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_staff)
        self.assertTrue(self.member.is_superuser)
        self.assertEqual(response.json()['role'], 'admin')

    def test_update_without_password_keeps_current_password(self):
        response = self.post_save(
            id=self.member.pk,
            username='member',
            email='member@example.com',
            password='',
            role='instructor',
            is_active='true',
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('MemberPass123!'))

    def test_invalid_role_is_rejected(self):
        response = self.post_save(role='owner')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='newmember').exists())

    def test_invalid_email_is_rejected(self):
        response = self.post_save(email='not-an-email')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='newmember').exists())

    def test_duplicate_username_is_rejected(self):
        response = self.post_save(username='member')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='newmember').exists())

    def test_duplicate_email_is_rejected(self):
        response = self.post_save(email='member@example.com')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='newmember').exists())

    def test_self_deactivation_is_blocked(self):
        response = self.post_save(
            id=self.admin.pk,
            username='admin',
            email='admin@example.com',
            password='',
            role='admin',
            is_active='false',
        )

        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_self_demotion_is_blocked(self):
        response = self.post_save(
            id=self.admin.pk,
            username='admin',
            email='admin@example.com',
            password='',
            role='staff',
            is_active='true',
        )

        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)
        self.assertTrue(self.admin.is_staff)

    def test_self_deletion_is_blocked(self):
        response = self.client.post(
            reverse('users:user_delete_ajax', args=[self.admin.pk])
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_delete_user(self):
        response = self.client.post(
            reverse('users:user_delete_ajax', args=[self.member.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=self.member.pk).exists())

    def test_non_superuser_cannot_use_user_management(self):
        self.client.force_login(self.member)

        page_response = self.client.get(reverse('users:user_list'))
        save_response = self.post_save(username='blocked-account')

        self.assertEqual(page_response.status_code, 302)
        self.assertEqual(save_response.status_code, 302)
        self.assertFalse(User.objects.filter(username='blocked-account').exists())
