import apps.py314_compat  # noqa: F401  (Python 3.14 / Django 5.0 test-client fix)

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Category, Concern, ReportComment


class HomeViewTests(TestCase):
    def test_home_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username='newuser', email='newuser@example.com', password='newpass123')

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')

    def test_home_requires_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 302)


class ReportCommentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='commenter',
            password='testpass123',
        )
        self.other = get_user_model().objects.create_user(
            username='otheruser',
            password='testpass123',
        )
        self.category = Category.objects.create(name='General')
        self.concern = Concern.objects.create(
            title='Test concern',
            description='A concern used for comment tests.',
            category=self.category,
        )
        self.comment = ReportComment.objects.create(
            concern=self.concern,
            author=self.user,
            body='Original comment',
        )

    def test_logged_in_user_can_add_comment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('add_comment', args=['concern', self.concern.pk]),
            {'body': 'A new comment'},
        )

        self.assertRedirects(
            response,
            f"{reverse('dashboard')}#report-concern-{self.concern.pk}",
            fetch_redirect_response=False,
        )
        self.assertTrue(
            ReportComment.objects.filter(concern=self.concern, body='A new comment').exists()
        )

    def test_owner_can_edit_comment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('edit_comment', args=[self.comment.pk]),
            {'body': 'Updated comment'},
        )

        self.comment.refresh_from_db()
        self.assertRedirects(
            response,
            f"{reverse('dashboard')}#report-concern-{self.concern.pk}",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.comment.body, 'Updated comment')
        self.assertTrue(self.comment.is_edited)

    def test_owner_can_delete_comment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('delete_comment', args=[self.comment.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ReportComment.objects.filter(pk=self.comment.pk).exists())

    def test_other_user_cannot_edit_or_delete_comment(self):
        self.client.force_login(self.other)

        edit_response = self.client.post(
            reverse('edit_comment', args=[self.comment.pk]),
            {'body': 'Hijacked comment'},
        )
        delete_response = self.client.post(
            reverse('delete_comment', args=[self.comment.pk])
        )

        self.assertEqual(edit_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, 'Original comment')

    def test_empty_edit_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('edit_comment', args=[self.comment.pk]),
            {'body': '   '},
        )

        self.comment.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.comment.body, 'Original comment')

    def test_edit_and_delete_require_login(self):
        edit_response = self.client.post(
            reverse('edit_comment', args=[self.comment.pk]),
            {'body': 'Nope'},
        )
        delete_response = self.client.post(
            reverse('delete_comment', args=[self.comment.pk])
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertEqual(delete_response.status_code, 302)
        self.assertIn(reverse('login'), edit_response.url)
        self.assertIn(reverse('login'), delete_response.url)
