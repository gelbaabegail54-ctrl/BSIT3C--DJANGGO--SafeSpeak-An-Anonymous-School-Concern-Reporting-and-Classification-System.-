import apps.py314_compat  # noqa: F401  (Python 3.14 / Django 5.0 test-client fix)

import base64
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.codenames import user_codename
from apps.core.images import MAX_REPORT_IMAGES
from apps.core.models import (
    AdminAction,
    AdminActivityLog,
    Category,
    Concern,
    ConcernResponse,
    ConcernStatus,
    Confession,
    ReportComment,
    ReportImage,
)
from apps.core.nlp import LOW_CONFIDENCE_THRESHOLD, classify_text
from apps.core.views import log_admin_activity


PNG_IMAGE = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2ZQAAAABJRU5ErkJggg=='
)


def uploaded_png(name='photo.png'):
    return SimpleUploadedFile(name, PNG_IMAGE, content_type='image/png')


class HomeViewTests(TestCase):
    def test_home_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username='newuser', email='newuser@example.com', password='newpass123')

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')
        self.assertContains(response, 'dh-home-fullscreen')
        self.assertContains(response, '<span class="nav-link-title">Dashboard</span>')
        self.assertContains(response, reverse('my_reports'))
        self.assertContains(response, 'You post as')
        self.assertContains(response, user_codename(user.pk))
        self.assertNotContains(response, 'Your identity stays private')

    def test_home_requires_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 302)


class AnonymousCodenameTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='codenameuser',
            password='codepass123',
        )
        self.category = Category.objects.create(name='General')
        self.concern = Concern.objects.create(
            title='A private concern',
            description='Something the community should see.',
            category=self.category,
        )

    def test_feed_uses_code_name_for_unlinked_report(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, self.concern.codename)
        self.assertNotContains(response, '<span class="fw-bold">Anonymous</span>')

    def test_feed_uses_user_code_name_for_linked_report(self):
        self.concern.submitted_by = self.user
        self.concern.save(update_fields=['submitted_by'])
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, self.concern.codename)

    def test_comment_uses_author_code_name(self):
        comment = ReportComment.objects.create(
            concern=self.concern,
            author=self.user,
            body='A supportive comment.',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, comment.codename)

    def test_account_shows_community_code_name(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_account'))

        self.assertContains(response, 'Community code name')
        self.assertContains(response, user_codename(self.user.pk))

    def test_submission_pages_show_community_code_name(self):
        self.client.force_login(self.user)

        for url_name in ('submit_concern', 'submit_confession'):
            response = self.client.get(reverse(url_name))

            self.assertContains(response, 'Posting as')
            self.assertContains(response, user_codename(self.user.pk))


class SupportPagesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='supportuser',
            email='support@example.com',
            password='oldpass12345',
        )

    def test_regular_user_sidebar_has_support_links(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Support')
        self.assertContains(response, reverse('help_resources'))
        self.assertContains(response, reverse('privacy_guidelines'))
        self.assertContains(response, reverse('my_account'))
        self.assertContains(response, 'Help &amp; resources')
        self.assertContains(response, 'Privacy &amp; guidelines')

    def test_administrator_sidebar_does_not_show_support_links(self):
        admin = get_user_model().objects.create_superuser(
            username='supportadmin',
            email='supportadmin@example.com',
            password='adminpass123',
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('team_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('help_resources'))
        self.assertNotContains(response, reverse('privacy_guidelines'))
        self.assertNotContains(response, reverse('my_account'))

    def test_support_pages_require_login(self):
        for name in ('help_resources', 'privacy_guidelines', 'my_account'):
            response = self.client.get(reverse(name))

            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('login'), response.url)

    def test_support_pages_render(self):
        self.client.force_login(self.user)

        help_response = self.client.get(reverse('help_resources'))
        privacy_response = self.client.get(reverse('privacy_guidelines'))
        account_response = self.client.get(reverse('my_account'))

        self.assertEqual(help_response.status_code, 200)
        self.assertContains(help_response, 'Support options')
        self.assertContains(help_response, 'Frequently asked questions')
        self.assertEqual(privacy_response.status_code, 200)
        self.assertContains(privacy_response, 'How your anonymity works')
        self.assertContains(privacy_response, 'Community guidelines')
        self.assertEqual(account_response.status_code, 200)
        self.assertContains(account_response, 'Profile details')
        self.assertContains(account_response, self.user.username)
        self.assertContains(account_response, 'Change password')

    def test_user_can_update_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('my_account'),
            {
                'action': 'profile',
                'first_name': 'Alex',
                'last_name': 'Rivera',
                'email': 'alex.rivera@example.com',
            },
        )

        self.assertRedirects(response, reverse('my_account'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Alex')
        self.assertEqual(self.user.last_name, 'Rivera')
        self.assertEqual(self.user.email, 'alex.rivera@example.com')

    def test_profile_rejects_duplicate_email(self):
        get_user_model().objects.create_user(
            username='otheruser',
            email='taken@example.com',
            password='otherpass123',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('my_account'),
            {
                'action': 'profile',
                'first_name': 'Support',
                'last_name': 'User',
                'email': 'taken@example.com',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already in use')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'support@example.com')

    def test_profile_rejects_invalid_email(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('my_account'),
            {
                'action': 'profile',
                'email': 'not-an-email',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a valid email address.')

    def test_user_can_change_password(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('my_account'),
            {
                'action': 'password',
                'old_password': 'oldpass12345',
                'new_password1': 'NewStrongPass456!',
                'new_password2': 'NewStrongPass456!',
            },
        )

        self.assertRedirects(response, reverse('my_account'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPass456!'))
        self.assertEqual(
            self.client.get(reverse('dashboard')).status_code,
            200,
        )

    def test_password_change_rejects_wrong_current_password(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('my_account'),
            {
                'action': 'password',
                'old_password': 'wrong-password',
                'new_password1': 'NewStrongPass456!',
                'new_password2': 'NewStrongPass456!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your old password was entered incorrectly')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('oldpass12345'))


class LoginRedirectTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='loginadmin',
            email='loginadmin@example.com',
            password='adminpass123',
        )
        self.regular = get_user_model().objects.create_user(
            username='loginuser',
            password='testpass123',
        )

    def test_administrator_lands_on_team_dashboard(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'loginadmin', 'password': 'adminpass123'},
        )

        self.assertRedirects(
            response,
            reverse('team_dashboard'),
            fetch_redirect_response=False,
        )

    def test_regular_user_lands_on_home_dashboard(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'loginuser', 'password': 'testpass123'},
        )

        self.assertRedirects(
            response,
            reverse('dashboard'),
            fetch_redirect_response=False,
        )

    def test_safe_next_url_is_honored(self):
        target = reverse('admin_activity_history')
        response = self.client.post(
            f"{reverse('login')}?next={target}",
            {'username': 'loginadmin', 'password': 'adminpass123'},
        )

        self.assertRedirects(response, target, fetch_redirect_response=False)

    def test_external_next_url_is_ignored(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': 'loginadmin',
                'password': 'adminpass123',
                'next': 'https://evil.example.com/',
            },
        )

        self.assertRedirects(
            response,
            reverse('team_dashboard'),
            fetch_redirect_response=False,
        )


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

    def test_superuser_comment_is_logged(self):
        admin = get_user_model().objects.create_superuser(
            username='commentadmin',
            email='commentadmin@example.com',
            password='adminpass123',
        )
        self.client.force_login(admin)

        self.client.post(
            reverse('add_comment', args=['concern', self.concern.pk]),
            {'body': 'Administrator follow-up'},
        )

        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=admin,
                action=AdminAction.COMMENT_ADDED,
                concern=self.concern,
                detail='Administrator follow-up',
            ).exists()
        )

    def test_regular_user_comment_is_not_admin_activity(self):
        self.client.force_login(self.user)

        self.client.post(
            reverse('add_comment', args=['concern', self.concern.pk]),
            {'body': 'Regular user comment'},
        )

        self.assertFalse(
            AdminActivityLog.objects.filter(
                action=AdminAction.COMMENT_ADDED,
            ).exists()
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


class AdminActivityHistoryTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123',
        )
        self.regular = get_user_model().objects.create_user(
            username='regularuser',
            password='testpass123',
        )
        self.category = Category.objects.create(name='General')
        self.concern = Concern.objects.create(
            title='Broken classroom window',
            description='The window in room 201 is broken.',
            category=self.category,
        )
        self.history_url = reverse('admin_activity_history')
        self.detail_url = reverse(
            'admin_report_detail', args=['concern', self.concern.pk]
        )

    def test_history_requires_team_access(self):
        anonymous_response = self.client.get(self.history_url)
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn(reverse('login'), anonymous_response.url)

        self.client.force_login(self.regular)
        response = self.client.get(self.history_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)

    def test_admin_history_includes_account_activity(self):
        AdminActivityLog.objects.create(
            actor=self.admin,
            action=AdminAction.SIGNED_IN,
            target_user=self.admin,
            detail='Signed in to SafeSpeak.',
        )
        self.client.force_login(self.admin)

        response = self.client.get(self.history_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Signed in to SafeSpeak.')
        self.assertContains(response, 'Manage users')
        self.assertContains(response, reverse('team_management'))
        self.assertContains(response, 'Back to management')
        codes = [code for code, _ in response.context['action_choices']]
        self.assertIn(AdminAction.SIGNED_IN, codes)

    def test_status_change_is_logged_and_listed(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.detail_url,
            {'action': 'status', 'status': ConcernStatus.UNDER_REVIEW},
        )

        self.assertEqual(response.status_code, 302)
        log = AdminActivityLog.objects.get(concern=self.concern)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.action, AdminAction.STATUS_CHANGED)
        self.assertEqual(log.old_value, 'Submitted')
        self.assertEqual(log.new_value, 'Under Review')

        history = self.client.get(self.history_url)
        self.assertEqual(history.status_code, 200)
        self.assertTemplateUsed(history, 'admin_activity_history.html')
        self.assertContains(history, 'Status changed')
        self.assertContains(history, self.concern.title)

    def test_unchanged_status_is_not_logged(self):
        self.client.force_login(self.admin)

        self.client.post(
            self.detail_url,
            {'action': 'status', 'status': self.concern.status},
        )

        self.assertFalse(AdminActivityLog.objects.exists())

    def test_response_and_note_are_logged(self):
        self.client.force_login(self.admin)

        self.client.post(
            self.detail_url,
            {
                'action': 'response',
                'message': 'We are looking into this.',
                'is_public': 'on',
            },
        )
        self.client.post(
            self.detail_url,
            {'action': 'note', 'body': 'Facilities team notified.'},
        )

        self.assertEqual(AdminActivityLog.objects.count(), 2)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action=AdminAction.RESPONSE_SAVED,
                new_value='Public',
                detail='We are looking into this.',
            ).exists()
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action=AdminAction.NOTE_ADDED,
                detail='Facilities team notified.',
            ).exists()
        )

    def test_history_action_filter_and_search(self):
        log_admin_activity(
            self.admin,
            AdminAction.STATUS_CHANGED,
            report=self.concern,
            old_value='Submitted',
            new_value='Resolved',
        )
        note_log = log_admin_activity(
            self.admin,
            AdminAction.NOTE_ADDED,
            report=self.concern,
            detail='Follow up with facilities.',
        )
        self.client.force_login(self.admin)

        filtered = self.client.get(
            self.history_url, {'action': AdminAction.NOTE_ADDED}
        )
        self.assertEqual(list(filtered.context['logs']), [note_log])

        searched = self.client.get(self.history_url, {'q': 'facilities'})
        self.assertEqual(list(searched.context['logs']), [note_log])

    def test_report_detail_shows_recent_activity(self):
        log_admin_activity(
            self.admin,
            AdminAction.NOTE_ADDED,
            report=self.concern,
            detail='Checked with the facilities office.',
        )
        self.client.force_login(self.admin)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recent activity')
        self.assertContains(response, 'Checked with the facilities office.')

    def test_admin_sign_in_and_sign_out_are_logged(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'admin', 'password': 'adminpass123'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin, action=AdminAction.SIGNED_IN
            ).exists()
        )

        self.client.get(reverse('logout'))

        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin, action=AdminAction.SIGNED_OUT
            ).exists()
        )

    def test_comment_moderation_is_logged(self):
        comment = ReportComment.objects.create(
            concern=self.concern,
            author=self.regular,
            body='Original comment',
        )
        self.client.force_login(self.admin)

        self.client.post(
            reverse('edit_comment', args=[comment.pk]),
            {'body': 'Moderated comment'},
        )
        self.client.post(reverse('delete_comment', args=[comment.pk]))

        self.assertTrue(
            AdminActivityLog.objects.filter(
                action=AdminAction.COMMENT_EDITED,
                concern=self.concern,
                detail__contains='Moderated comment',
            ).exists()
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action=AdminAction.COMMENT_DELETED,
                concern=self.concern,
                detail__contains='Moderated comment',
            ).exists()
        )

    def test_admin_dashboard_shows_recent_activity(self):
        log_admin_activity(
            self.admin,
            AdminAction.NOTE_ADDED,
            report=self.concern,
            detail='Dashboard activity entry.',
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['recent_activity']), [
            AdminActivityLog.objects.get(detail='Dashboard activity entry.')
        ])
        self.assertContains(response, 'Admin activity history')


class EmergencyBannerTests(TestCase):
    def test_anonymous_reporting_forms_show_emergency_banner(self):
        for url in (reverse('submit_concern'), reverse('submit_confession')):
            response = self.client.get(url)

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Emergency alert')
            self.assertContains(response, 'not monitored 24/7')


class ReportSubmissionActivityTests(TestCase):
    def test_concern_submission_is_logged_anonymously(self):
        response = self.client.post(
            reverse('submit_concern'),
            {'description': 'The cafeteria sink is leaking near the serving counter.'},
        )

        self.assertEqual(response.status_code, 200)
        log = AdminActivityLog.objects.get(action=AdminAction.REPORT_SUBMITTED)
        self.assertIsNone(log.actor)
        self.assertIsNotNone(log.concern_id)
        self.assertIsNone(log.confession_id)
        self.assertEqual(log.detail, 'Anonymous concern submitted.')
        self.assertEqual(
            log.concern.title,
            'The cafeteria sink is leaking near the serving counter.',
        )
        self.assertIn('by System', str(log))

    def test_confession_submission_is_logged_anonymously(self):
        response = self.client.post(
            reverse('submit_confession'),
            {'description': 'I feel overwhelmed by the workload this semester.'},
        )

        self.assertEqual(response.status_code, 200)
        log = AdminActivityLog.objects.get(action=AdminAction.REPORT_SUBMITTED)
        self.assertIsNone(log.actor)
        self.assertIsNotNone(log.confession_id)
        self.assertIsNone(log.concern_id)
        self.assertEqual(log.detail, 'Anonymous confession submitted.')

    def test_submission_activity_appears_in_history(self):
        self.client.post(
            reverse('submit_concern'),
            {'description': 'A broken chair in room 204.'},
        )
        admin = get_user_model().objects.create_superuser(
            username='historyadmin',
            email='historyadmin@example.com',
            password='adminpass123',
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('admin_activity_history'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Report submitted')
        self.assertContains(response, 'Anonymous concern submitted.')


class ReportImageUploadTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, True)
        media_override = override_settings(MEDIA_ROOT=self.media_root)
        media_override.enable()
        self.addCleanup(media_override.disable)

    def _make_concern(self, submitted_by=None):
        category = Category.objects.create(name='General')
        return Concern.objects.create(
            title='Broken window',
            description='The science lab window is broken.',
            category=category,
            submitted_by=submitted_by,
        )

    def test_reporting_forms_accept_multiple_images(self):
        for url in (reverse('submit_concern'), reverse('submit_confession')):
            response = self.client.get(url)

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'enctype="multipart/form-data"')
            self.assertContains(response, 'name="images"')
            self.assertContains(response, 'multiple')
            self.assertContains(
                response,
                f'Up to {MAX_REPORT_IMAGES} images',
            )

    def test_concern_submission_saves_images_with_random_names(self):
        response = self.client.post(
            reverse('submit_concern'),
            {
                'description': 'Broken window in the science lab.',
                'images': [
                    uploaded_png('front-view.png'),
                    uploaded_png('side-view.png'),
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['submission_successful'])
        concern = Concern.objects.get()
        self.assertEqual(concern.images.count(), 2)
        for image in concern.images.all():
            self.assertTrue(image.image.storage.exists(image.image.name))
            self.assertNotIn('front-view', image.image.name)
            self.assertNotIn('side-view', image.image.name)
            self.assertTrue(image.image.name.endswith('.png'))
        log = AdminActivityLog.objects.get(action=AdminAction.REPORT_SUBMITTED)
        self.assertIn('with 2 images', log.detail)

    def test_confession_submission_saves_image(self):
        response = self.client.post(
            reverse('submit_confession'),
            {
                'description': 'I feel overwhelmed by the workload this semester.',
                'images': [uploaded_png('note.png')],
            },
        )

        self.assertEqual(response.status_code, 200)
        confession = Confession.objects.get()
        self.assertEqual(confession.images.count(), 1)
        image = confession.images.first()
        self.assertTrue(image.image.storage.exists(image.image.name))

    def test_unsupported_file_is_rejected(self):
        response = self.client.post(
            reverse('submit_concern'),
            {
                'description': 'Something happened in the hallway.',
                'images': [
                    SimpleUploadedFile(
                        'notes.txt',
                        b'not an image',
                        content_type='text/plain',
                    )
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not a supported image')
        self.assertFalse(Concern.objects.exists())
        self.assertFalse(
            AdminActivityLog.objects.filter(
                action=AdminAction.REPORT_SUBMITTED
            ).exists()
        )

    def test_too_many_images_are_rejected(self):
        response = self.client.post(
            reverse('submit_concern'),
            {
                'description': 'There are several broken chairs in room 204.',
                'images': [
                    uploaded_png(f'image-{index}.png')
                    for index in range(MAX_REPORT_IMAGES + 1)
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'up to {MAX_REPORT_IMAGES} images',
        )
        self.assertFalse(Concern.objects.exists())

    @patch('apps.core.images.MAX_REPORT_IMAGE_BYTES', 10)
    def test_oversized_image_is_rejected(self):
        oversized = SimpleUploadedFile(
            'large.png',
            PNG_IMAGE + b'0' * 20,
            content_type='image/png',
        )

        response = self.client.post(
            reverse('submit_concern'),
            {
                'description': 'A large photo of the damaged ceiling.',
                'images': [oversized],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is larger than')
        self.assertFalse(Concern.objects.exists())

    def test_feed_and_my_reports_show_attached_image(self):
        user = get_user_model().objects.create_user(
            username='imageuser',
            email='imageuser@example.com',
            password='userpass123',
        )
        concern = self._make_concern(submitted_by=user)
        image = ReportImage.objects.create(
            concern=concern,
            image=uploaded_png(),
        )
        self.client.force_login(user)

        feed = self.client.get(reverse('dashboard'))
        my_reports = self.client.get(reverse('my_reports'))

        self.assertContains(feed, image.image.url)
        self.assertContains(my_reports, image.image.url)

    def test_administrator_report_detail_shows_attached_image(self):
        admin = get_user_model().objects.create_superuser(
            username='imageadmin',
            email='imageadmin@example.com',
            password='adminpass123',
        )
        concern = self._make_concern()
        image = ReportImage.objects.create(
            concern=concern,
            image=uploaded_png(),
        )
        self.client.force_login(admin)

        response = self.client.get(
            reverse('admin_report_detail', args=['concern', concern.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, image.image.url)
        self.assertContains(response, 'Attached images')


class TeamDashboardTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='teamadmin',
            email='teamadmin@example.com',
            password='adminpass123',
        )
        self.user = get_user_model().objects.create_user(
            username='teamuser',
            password='userpass123',
        )
        self.category = Category.objects.create(name='General')
        self.concern = Concern.objects.create(
            title='Team concern',
            description='A concern for the team queue.',
            category=self.category,
        )
        self.confession = Confession.objects.create(
            title='Team confession',
            description='A confession for the team queue.',
            category=self.category,
        )
        self.team_url = reverse('team_dashboard')
        self.management_url = reverse('team_management')
        self.detail_url = reverse(
            'admin_report_detail', args=['concern', self.concern.pk]
        )

    def test_team_dashboard_requires_administrator_access(self):
        anonymous = self.client.get(self.team_url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn(reverse('login'), anonymous.url)

        self.client.force_login(self.user)
        response = self.client.get(self.team_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)

    def test_administrator_can_view_team_dashboard(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.team_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'team_dashboard.html')
        self.assertContains(response, 'Team Dashboard')
        self.assertContains(response, 'NLP categorization workspace')
        self.assertContains(response, 'Reports analyzed')
        self.assertContains(response, 'Classification review')
        self.assertContains(response, 'Category model')
        self.assertContains(response, self.concern.title)
        self.assertContains(response, self.confession.title)
        self.assertContains(response, reverse('admin_dashboard'))
        self.assertNotContains(response, reverse('nlp_hub'))
        self.assertContains(response, reverse('admin_activity_history'))
        self.assertContains(response, reverse('users:user_list'))
        self.assertNotContains(response, reverse('my_reports'))
        self.assertNotContains(response, '<span class="nav-link-title">Dashboard</span>')

    def test_team_dashboard_can_run_nlp_analysis(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.team_url,
            {'action': 'analyze_all'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(self.team_url, response.url)
        self.concern.refresh_from_db()
        self.assertIsNotNone(self.concern.nlp_analyzed_at)

    def test_management_requires_administrator_access(self):
        anonymous = self.client.get(self.management_url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn(reverse('login'), anonymous.url)

        self.client.force_login(self.user)
        response = self.client.get(self.management_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)

    def test_administrator_can_view_management_dashboard(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.management_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'team_management.html')
        self.assertContains(response, 'Manage Reports')
        self.assertContains(response, 'NLP categorization hub')
        self.assertContains(response, 'Activity history')
        self.assertContains(response, 'Users')
        self.assertContains(response, reverse('admin_dashboard'))
        self.assertContains(response, reverse('nlp_hub'))
        self.assertContains(response, reverse('admin_activity_history'))
        self.assertContains(response, reverse('users:user_list'))
        self.assertTrue(response.context['can_manage_users'])
        self.assertIn('user_count', response.context)
        self.assertIn('nlp_category_count', response.context)

    def test_regular_user_cannot_access_administrator_tools(self):
        self.client.force_login(self.user)

        for url in (
            reverse('team_dashboard'),
            reverse('team_management'),
            reverse('nlp_hub'),
            reverse('admin_dashboard'),
            reverse('admin_activity_history'),
            reverse('users:user_list'),
        ):
            response = self.client.get(url)

            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('dashboard'), response.url)

    def test_administrator_can_view_activity_history(self):
        log_admin_activity(
            self.admin,
            AdminAction.STATUS_CHANGED,
            report=self.concern,
            old_value='Submitted',
            new_value='In Progress',
        )
        AdminActivityLog.objects.create(
            actor=self.admin,
            action=AdminAction.SIGNED_IN,
            target_user=self.admin,
            detail='Signed in to SafeSpeak.',
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_activity_history'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin_activity_history.html')
        self.assertContains(response, 'Activity history')
        self.assertContains(response, self.concern.title)
        self.assertContains(response, 'Signed in to SafeSpeak.')
        self.assertContains(response, 'Manage users')
        self.assertContains(response, reverse('team_management'))
        codes = [code for code, _ in response.context['action_choices']]
        self.assertIn(AdminAction.SIGNED_IN, codes)

    def test_administrator_can_manage_reports(self):
        self.client.force_login(self.admin)

        status_response = self.client.post(
            self.detail_url,
            {'action': 'status', 'status': ConcernStatus.IN_PROGRESS},
        )
        self.concern.refresh_from_db()
        self.assertEqual(status_response.status_code, 302)
        self.assertEqual(self.concern.status, ConcernStatus.IN_PROGRESS)

        response = self.client.post(
            self.detail_url,
            {
                'action': 'response',
                'message': 'Thank you for reporting this. We are looking into it.',
                'is_public': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ConcernResponse.objects.filter(
                concern=self.concern,
                message='Thank you for reporting this. We are looking into it.',
                responded_by=self.admin,
                is_public=True,
            ).exists()
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                concern=self.concern,
                action=AdminAction.STATUS_CHANGED,
            ).exists()
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                concern=self.concern,
                action=AdminAction.RESPONSE_SAVED,
            ).exists()
        )

    def test_report_detail_links_back_to_team_dashboard(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('team_dashboard'))
        self.assertContains(response, reverse('admin_activity_history'))
        self.assertContains(response, 'View all')

class NLPEngineTests(TestCase):
    def test_empty_library_uses_builtin_model(self):
        result = classify_text('I am being bullied and threatened at school.')

        self.assertTrue(result.matched)
        self.assertEqual(result.category.name, 'Bullying')
        self.assertGreaterEqual(result.confidence, LOW_CONFIDENCE_THRESHOLD)
        self.assertIn('threat', result.signals)

    def test_no_signal_returns_fallback(self):
        result = classify_text('The quick brown fox jumps over the lazy dog.')

        self.assertFalse(result.matched)
        self.assertIsNone(result.category)
        self.assertEqual(result.confidence, 0)
        self.assertEqual(result.signals, [])

    def test_phrase_keywords_match_word_sequences(self):
        Category.objects.create(
            name='Health',
            keywords='mental health, panic attack',
        )

        result = classify_text('I think I had a panic attack before class.')

        self.assertTrue(result.matched)
        self.assertEqual(result.category.name, 'Health')
        self.assertIn('panic attack', result.signals)

    def test_custom_category_keywords_drive_prediction(self):
        Category.objects.create(
            name='Health',
            keywords='clinic*, nurse*, medicine*',
        )

        result = classify_text('I need to visit the clinic for my medicine.')

        self.assertTrue(result.matched)
        self.assertEqual(result.category.name, 'Health')
        self.assertIn('clinic', result.signals)

    def test_prefix_matching_requires_wildcard(self):
        Category.objects.create(name='Facilities', keywords='class')

        result = classify_text('The classroom projector is broken.')

        self.assertFalse(result.matched)


class NLPCategorizationHubTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='nlpadmin',
            email='nlpadmin@example.com',
            password='adminpass123',
        )
        self.user = get_user_model().objects.create_user(
            username='nlpuser',
            password='userpass123',
        )
        self.general = Category.objects.create(name='General')
        self.facilities = Category.objects.create(
            name='Facilities',
            keywords='leak*, roof*, classroom*, broken',
        )
        self.bullying = Category.objects.create(
            name='Bullying',
            keywords='bully*, harass*, threat*',
        )
        self.concern = Concern.objects.create(
            title='Leaking classroom roof',
            description='The classroom roof is leaking in heavy rain.',
            category=self.general,
        )
        self.confession = Confession.objects.create(
            title='Feeling overwhelmed',
            description='I feel stressed and anxious about my exams.',
            category=self.general,
        )
        self.url = reverse('nlp_hub')

    def test_hub_requires_administrator_access(self):
        anonymous = self.client.get(self.url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn(reverse('login'), anonymous.url)

        self.client.force_login(self.user)
        regular = self.client.get(self.url)
        self.assertEqual(regular.status_code, 302)
        self.assertIn(reverse('dashboard'), regular.url)

        self.client.force_login(self.admin)
        administrator = self.client.get(self.url)
        self.assertEqual(administrator.status_code, 200)

    def test_administrator_can_view_hub(self):
        self.concern.nlp_suggested_category = self.facilities
        self.concern.nlp_confidence = 86
        self.concern.nlp_signals = 'roof, leak'
        self.concern.nlp_analyzed_at = timezone.now()
        self.concern.save()

        self.client.force_login(self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'nlp_hub.html')
        self.assertContains(response, 'NLP categorization hub')
        self.assertContains(response, 'Classification review')
        self.assertContains(response, 'Category model')
        self.assertContains(response, self.concern.title)
        self.assertContains(response, 'Facilities')
        self.assertContains(response, '86%')

    def test_analyze_report_action_persists_result(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            {
                'action': 'analyze_report',
                'kind': 'concern',
                'pk': self.concern.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(self.url, response.url)
        self.concern.refresh_from_db()
        self.assertIsNotNone(self.concern.nlp_analyzed_at)
        self.assertEqual(self.concern.nlp_suggested_category_id, self.facilities.pk)
        self.assertGreaterEqual(
            self.concern.nlp_confidence,
            LOW_CONFIDENCE_THRESHOLD,
        )
        self.assertIn('leak', self.concern.nlp_signals)

    def test_analyze_all_updates_every_report(self):
        self.client.force_login(self.admin)

        response = self.client.post(self.url, {'action': 'analyze_all'})

        self.assertEqual(response.status_code, 302)
        self.concern.refresh_from_db()
        self.confession.refresh_from_db()
        self.assertIsNotNone(self.concern.nlp_analyzed_at)
        self.assertIsNotNone(self.confession.nlp_analyzed_at)
        self.assertEqual(self.concern.nlp_suggested_category_id, self.facilities.pk)

    def test_apply_suggestion_reclassifies_and_logs_activity(self):
        self.concern.nlp_suggested_category = self.facilities
        self.concern.nlp_confidence = 88
        self.concern.nlp_signals = 'leak, roof'
        self.concern.nlp_analyzed_at = timezone.now()
        self.concern.save()
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            {
                'action': 'apply',
                'kind': 'concern',
                'pk': self.concern.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.concern.refresh_from_db()
        self.assertEqual(self.concern.category_id, self.facilities.pk)
        log = AdminActivityLog.objects.get(action=AdminAction.CATEGORY_CHANGED)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.concern, self.concern)
        self.assertEqual(log.old_value, 'General')
        self.assertEqual(log.new_value, 'Facilities')

    def test_analyze_sample_renders_prediction(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            {
                'action': 'analyze_sample',
                'sample_text': 'I am being bullied and threatened by a classmate.',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['sample'])
        self.assertEqual(response.context['sample']['category'], 'Bullying')
        self.assertContains(response, 'Matched signals')
        self.assertContains(response, 'bullied')

    def test_create_category_with_keywords(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            {
                'action': 'create_category',
                'name': 'Health',
                'description': 'Clinic and medical concerns.',
                'keywords': 'nurse*, clinic*, medicine*',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('#categories', response.url)
        category = Category.objects.get(name='Health')
        self.assertEqual(category.keywords, 'nurse*, clinic*, medicine*')
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                action=AdminAction.CATEGORY_CREATED,
                detail='Created the "Health" category.',
            ).exists()
        )

    def test_update_category_keywords_and_status(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            {
                'action': 'update_category',
                'category_id': self.facilities.pk,
                'name': 'Facilities',
                'description': 'Campus maintenance and utilities.',
                'keywords': 'leak*, flood*, broken',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.facilities.refresh_from_db()
        self.assertEqual(self.facilities.keywords, 'leak*, flood*, broken')
        self.assertFalse(self.facilities.is_active)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                actor=self.admin,
                action=AdminAction.CATEGORY_UPDATED,
            ).exists()
        )

    def test_seed_defaults_adds_missing_categories(self):
        self.client.force_login(self.admin)

        response = self.client.post(self.url, {'action': 'seed_defaults'})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Category.objects.filter(name='Safety').exists())
        self.assertTrue(Category.objects.filter(name='Academic').exists())
        self.assertTrue(Category.objects.filter(name='Personal').exists())
        self.assertFalse(Category.objects.filter(name='Bullying').count() > 1)

    def test_regular_user_cannot_run_nlp_actions(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url, {'action': 'analyze_all'})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)
        self.concern.refresh_from_db()
        self.assertIsNone(self.concern.nlp_analyzed_at)

    def test_submission_stores_nlp_metadata(self):
        response = self.client.post(
            reverse('submit_concern'),
            {'description': 'The classroom roof is leaking in heavy rain.'},
        )

        self.assertEqual(response.status_code, 200)
        concern = Concern.objects.get(title='The classroom roof is leaking in heavy rain.')
        self.assertEqual(concern.category_id, self.facilities.pk)
        self.assertEqual(concern.nlp_suggested_category_id, self.facilities.pk)
        self.assertGreaterEqual(concern.nlp_confidence, LOW_CONFIDENCE_THRESHOLD)
        self.assertIsNotNone(concern.nlp_analyzed_at)
        self.assertIn('leak', concern.nlp_signals)


class ReportAccountLinkTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='trackedreporter',
            password='testpass123',
        )
        self.concern_url = reverse('submit_concern')
        self.confession_url = reverse('submit_confession')

    def test_logged_in_reports_use_the_users_community_code_name(self):
        self.client.force_login(self.user)

        for url_name in ('submit_concern', 'submit_confession'):
            response = self.client.post(
                reverse(url_name),
                {'description': 'A report shared without linking my account.'},
            )

            report_model = (
                Concern if url_name == 'submit_concern' else Confession
            )
            report = report_model.objects.latest('pk')
            self.assertEqual(
                report.poster_codename,
                user_codename(self.user.pk),
            )
            self.assertEqual(report.codename, user_codename(self.user.pk))
            self.assertContains(response, report.codename)

    def test_anonymous_concern_ignores_link_option(self):
        response = self.client.post(
            self.concern_url,
            {
                'description': 'The gym roof is leaking during heavy rain.',
                'link_to_account': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        concern = Concern.objects.get(
            title='The gym roof is leaking during heavy rain.'
        )
        self.assertIsNone(concern.submitted_by)
        self.assertFalse(response.context['linked_to_account'])

    def test_logged_in_concern_is_anonymous_by_default(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.concern_url,
            {'description': 'A broken chair in room 204 is unsafe.'},
        )

        self.assertEqual(response.status_code, 200)
        concern = Concern.objects.get(title='A broken chair in room 204 is unsafe.')
        self.assertIsNone(concern.submitted_by)
        self.assertFalse(response.context['linked_to_account'])
        self.assertContains(response, 'submitted anonymously')

    def test_logged_in_concern_can_be_linked_to_account(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.concern_url,
            {
                'description': 'The laboratory sink has been leaking for a week.',
                'link_to_account': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        concern = Concern.objects.get(
            title='The laboratory sink has been leaking for a week.'
        )
        self.assertEqual(concern.submitted_by, self.user)
        self.assertTrue(response.context['linked_to_account'])
        self.assertContains(response, reverse('my_reports'))
        log = AdminActivityLog.objects.get(action=AdminAction.REPORT_SUBMITTED)
        self.assertIn('linked to the reporter account', log.detail)

    def test_logged_in_confession_can_be_linked_to_account(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.confession_url,
            {
                'description': 'I feel overwhelmed by the workload this semester.',
                'link_to_account': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        confession = Confession.objects.get(
            title='I feel overwhelmed by the workload this semester.'
        )
        self.assertEqual(confession.submitted_by, self.user)
        self.assertTrue(response.context['linked_to_account'])
        self.assertContains(response, reverse('my_reports'))

    def test_link_option_is_only_shown_to_authenticated_users(self):
        anonymous = self.client.get(self.concern_url)
        self.assertNotContains(anonymous, 'name="link_to_account"')

        self.client.force_login(self.user)
        authenticated = self.client.get(self.concern_url)
        self.assertContains(authenticated, 'name="link_to_account"')


class MyReportsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='reportowner',
            password='testpass123',
        )
        self.other = get_user_model().objects.create_user(
            username='otherreporter',
            password='testpass123',
        )
        self.admin = get_user_model().objects.create_superuser(
            username='reportsadmin',
            email='reportsadmin@example.com',
            password='adminpass123',
        )
        self.category = Category.objects.create(name='General')
        self.concern = Concern.objects.create(
            title='Linked concern',
            description='A linked concern description.',
            category=self.category,
            status=ConcernStatus.UNDER_REVIEW,
            submitted_by=self.user,
        )
        self.confession = Confession.objects.create(
            title='Linked confession',
            description='A linked confession description.',
            category=self.category,
            submitted_by=self.user,
        )
        Concern.objects.create(
            title='Anonymous concern',
            description='This report was never linked to an account.',
            category=self.category,
        )
        Concern.objects.create(
            title='Another user concern',
            description='This report belongs to someone else.',
            category=self.category,
            submitted_by=self.other,
        )
        self.url = reverse('my_reports')

    def test_my_reports_requires_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_my_reports_lists_only_linked_reports(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'my_reports.html')
        self.assertContains(response, 'Linked concern')
        self.assertContains(response, 'Linked confession')
        self.assertNotContains(response, 'Anonymous concern')
        self.assertNotContains(response, 'Another user concern')
        self.assertEqual(response.context['total_count'], 2)
        self.assertEqual(response.context['concern_count'], 1)
        self.assertEqual(response.context['confession_count'], 1)

    def test_my_reports_shows_status_and_response(self):
        ConcernResponse.objects.create(
            concern=self.concern,
            message='Facilities has been notified and will inspect the room.',
            responded_by=self.admin,
            is_public=False,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertContains(response, 'Under Review')
        self.assertContains(
            response,
            'Facilities has been notified and will inspect the room.',
        )
        self.assertContains(response, 'Visible only to you')
        self.assertEqual(response.context['response_count'], 1)

    def test_my_reports_type_filter(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url, {'type': 'confession'})

        self.assertEqual(
            [item['kind'] for item in response.context['reports']],
            ['confession'],
        )
        self.assertContains(response, 'Linked confession')
        self.assertNotContains(response, 'Linked concern')

    def test_my_reports_status_filter(self):
        self.client.force_login(self.user)

        response = self.client.get(
            self.url, {'status': ConcernStatus.UNDER_REVIEW}
        )

        self.assertEqual(
            [item['report'].pk for item in response.context['reports']],
            [self.concern.pk],
        )
        self.assertNotContains(response, 'Linked confession')

    def test_my_reports_empty_state(self):
        empty_user = get_user_model().objects.create_user(
            username='noreports',
            password='testpass123',
        )
        self.client.force_login(empty_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No linked reports yet')
        self.assertEqual(response.context['total_count'], 0)

