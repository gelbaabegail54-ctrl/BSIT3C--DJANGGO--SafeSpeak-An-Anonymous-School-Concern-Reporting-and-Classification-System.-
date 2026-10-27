import apps.py314_compat  # noqa: F401  (Python 3.14 / Django 5.0 test-client fix)

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.core.models import (
    AdminAction,
    AdminActivityLog,
    Category,
    Concern,
    ReportComment,
)


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
            'role': 'user',
            'is_active': 'true',
        }
        data.update(overrides)
        return self.client.post(reverse('users:user_save_ajax'), data)

    def test_list_ajax_includes_roles(self):
        response = self.client.get(reverse('users:user_list_ajax'))

        self.assertEqual(response.status_code, 200)
        roles = {row['username']: row['role'] for row in response.json()['data']}
        self.assertEqual(roles['admin'], 'admin')
        self.assertEqual(roles['member'], 'user')

    def test_get_ajax_includes_role(self):
        response = self.client.get(
            reverse('users:user_get_ajax', args=[self.member.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['role'], 'user')
        self.assertFalse(response.json()['is_superuser'])

    def test_create_user(self):
        response = self.post_save()

        self.assertEqual(response.status_code, 200)
        created = User.objects.get(username='newmember')
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertEqual(response.json()['role'], 'user')

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
            role='user',
            is_active='true',
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('MemberPass123!'))

    def test_invalid_role_is_rejected(self):
        for role in ('owner', 'staff', 'instructor'):
            response = self.post_save(role=role)

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
            role='user',
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

    def test_user_management_actions_are_audited(self):
        self.post_save()
        created = User.objects.get(username='newmember')
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                action=AdminAction.USER_CREATED,
                detail__contains='newmember',
            ).exists()
        )

        self.post_save(
            id=created.pk,
            username='newmember',
            email='newmember@example.com',
            password='',
            role='admin',
            is_active='true',
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                action=AdminAction.USER_ROLE_CHANGED,
                detail__contains='newmember',
            ).exists()
        )

        self.client.post(
            reverse('users:user_delete_ajax', args=[created.pk])
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                action=AdminAction.USER_DELETED,
                detail__contains='newmember',
            ).exists()
        )

    def test_password_reset_is_audited(self):
        response = self.post_save(
            id=self.member.pk,
            username='member',
            email='member@example.com',
            password='NewMemberPass123!',
            role='user',
            is_active='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                action=AdminAction.USER_PASSWORD_RESET,
                detail__contains='member',
            ).exists()
        )

    def test_deactivation_is_audited(self):
        response = self.post_save(
            id=self.member.pk,
            username='member',
            email='member@example.com',
            password='',
            role='user',
            is_active='false',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                action=AdminAction.USER_DEACTIVATED,
                detail__contains='member',
            ).exists()
        )

    def test_non_superuser_cannot_use_user_management(self):
        self.client.force_login(self.member)

        page_response = self.client.get(reverse('users:user_list'))
        save_response = self.post_save(username='blocked-account')

        self.assertEqual(page_response.status_code, 302)
        self.assertEqual(save_response.status_code, 302)
        self.assertFalse(User.objects.filter(username='blocked-account').exists())


class UserHistoryTests(TestCase):
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
        self.category = Category.objects.create(name='General')
        self.history_url = reverse('users:user_history', args=[self.member.pk])
        self.client.force_login(self.admin)

    def test_history_requires_superuser(self):
        self.client.logout()
        response = self.client.get(self.history_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

        self.client.force_login(self.member)
        response = self.client.get(self.history_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)

    def test_history_lists_account_activity(self):
        AdminActivityLog.objects.create(
            actor=self.admin,
            action=AdminAction.USER_ROLE_CHANGED,
            target_user=self.member,
            detail='Changed role for "member" from User to Administrator.',
        )

        response = self.client.get(self.history_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/history.html')
        self.assertContains(response, 'User role changed')
        self.assertContains(response, 'Changed role for')

    def test_history_filters_account_activity(self):
        AdminActivityLog.objects.create(
            actor=self.admin,
            action=AdminAction.USER_UPDATED,
            target_user=self.member,
            detail='Updated the member account.',
        )

        account_response = self.client.get(self.history_url, {'type': 'account'})
        report_response = self.client.get(self.history_url, {'type': 'reports'})

        self.assertEqual(account_response.context['account_count'], 1)
        self.assertContains(account_response, 'Updated the member account.')
        self.assertEqual(report_response.context['report_count'], 0)
        self.assertNotContains(report_response, 'Updated the member account.')

    def test_history_includes_reports_and_comments(self):
        concern = Concern.objects.create(
            title='Broken classroom window',
            description='The window in room 201 is broken.',
            category=self.category,
            submitted_by=self.member,
        )
        ReportComment.objects.create(
            concern=concern,
            author=self.member,
            body='Following up on this report.',
        )

        response = self.client.get(self.history_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['report_count'], 1)
        self.assertEqual(response.context['comment_count'], 1)
        self.assertContains(response, 'Broken classroom window')
        self.assertContains(response, 'Following up on this report.')

    def test_user_management_actions_target_the_affected_user(self):
        data = {
            'username': 'newmember',
            'first_name': 'New',
            'last_name': 'Member',
            'email': 'newmember@example.com',
            'password': 'NewMemberPass123!',
            'role': 'user',
            'is_active': 'true',
        }
        self.client.post(reverse('users:user_save_ajax'), data)
        created = User.objects.get(username='newmember')
        created_log = AdminActivityLog.objects.get(action=AdminAction.USER_CREATED)
        self.assertEqual(created_log.target_user, created)

        data.update({'id': created.pk, 'password': '', 'role': 'admin'})
        self.client.post(reverse('users:user_save_ajax'), data)
        role_log = AdminActivityLog.objects.get(action=AdminAction.USER_ROLE_CHANGED)
        self.assertEqual(role_log.target_user, created)

    def test_sign_in_and_sign_out_are_recorded_for_regular_users(self):
        self.client.logout()
        self.client.post(
            reverse('login'),
            {'username': 'member', 'password': 'MemberPass123!'},
        )
        self.client.get(reverse('logout'))

        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.member,
                target_user=self.member,
                action=AdminAction.SIGNED_IN,
            ).exists()
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.member,
                target_user=self.member,
                action=AdminAction.SIGNED_OUT,
            ).exists()
        )

        self.client.force_login(self.admin)
        response = self.client.get(self.history_url)
        actions = [
            item['log'].action
            for item in response.context['timeline']
            if item['kind'] == 'account'
        ]
        self.assertIn(AdminAction.SIGNED_IN, actions)
        self.assertIn(AdminAction.SIGNED_OUT, actions)
