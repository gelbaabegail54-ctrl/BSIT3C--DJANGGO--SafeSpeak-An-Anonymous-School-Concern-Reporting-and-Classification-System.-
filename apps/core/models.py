"""Models for the SafeSpeak anonymous school concern reporting system."""

import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .codenames import comment_codename, report_codename, user_codename


class Category(models.Model):
    """Classification category for concerns (e.g., bullying, facilities)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    keywords = models.TextField(
        blank=True,
        help_text=(
            'Comma-separated words or phrases used by the NLP classifier. '
            'End a word with * to match its beginning (for example, harass*).'
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safespeak_category'
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class ConcernStatus(models.TextChoices):
    """Workflow statuses for a submitted concern."""

    SUBMITTED = 'SUBMITTED', 'Submitted'
    UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
    RESOLVED = 'RESOLVED', 'Resolved'
    DISMISSED = 'DISMISSED', 'Dismissed'


class Concern(models.Model):
    """An anonymous concern report submitted through SafeSpeak."""

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='concerns',
    )
    status = models.CharField(
        max_length=20,
        choices=ConcernStatus.choices,
        default=ConcernStatus.SUBMITTED,
    )
    location_on_campus = models.CharField(max_length=255, blank=True)
    date_of_incident = models.DateField(null=True, blank=True)
    is_urgent = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='filed_concerns',
    )
    poster_codename = models.CharField(max_length=50, blank=True, editable=False)
    nlp_suggested_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suggested_concerns',
    )
    nlp_confidence = models.FloatField(default=0)
    nlp_signals = models.CharField(max_length=255, blank=True)
    nlp_analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'safespeak_concern'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['category', 'status']),
        ]

    def __str__(self):
        return self.title

    @property
    def codename(self):
        """Return the public code name shown instead of an identity."""
        if self.poster_codename:
            return self.poster_codename
        if self.submitted_by_id:
            return user_codename(self.submitted_by_id)
        if self.pk is None:
            return 'Anonymous'
        return report_codename('concern', self.pk)


class ConcernNote(models.Model):
    """Internal notes administrators attach to a concern."""

    concern = models.ForeignKey(
        Concern,
        on_delete=models.CASCADE,
        related_name='notes',
    )
    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='concern_notes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safespeak_concern_note'
        ordering = ['created_at']

    def __str__(self):
        return f'Note on {self.concern.title} by {self.created_at:%Y-%m-%d}'


class ConcernResponse(models.Model):
    """A response to the reporter for a concern, optionally visible publicly."""

    concern = models.OneToOneField(
        'Concern',
        on_delete=models.CASCADE,
        related_name='response',
    )
    message = models.TextField()
    is_public = models.BooleanField(default=False)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='concern_responses',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safespeak_concern_response'

    def __str__(self):
        return f'Response to {self.concern.title}'


class ConfessionResponse(models.Model):
    """A response to the reporter for a confession, optionally visible publicly."""

    confession = models.OneToOneField(
        'Confession',
        on_delete=models.CASCADE,
        related_name='response',
    )
    message = models.TextField()
    is_public = models.BooleanField(default=False)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confession_responses',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safespeak_confession_response'

    def __str__(self):
        return f'Response to {self.confession.title}'


class Confession(models.Model):
    """An anonymous confession submitted through SafeSpeak."""

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='confessions',
    )
    status = models.CharField(
        max_length=20,
        choices=ConcernStatus.choices,
        default=ConcernStatus.SUBMITTED,
    )
    location_on_campus = models.CharField(max_length=255, blank=True)
    date_of_incident = models.DateField(null=True, blank=True)
    is_urgent = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='filed_confessions',
    )
    poster_codename = models.CharField(max_length=50, blank=True, editable=False)
    nlp_suggested_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suggested_confessions',
    )
    nlp_confidence = models.FloatField(default=0)
    nlp_signals = models.CharField(max_length=255, blank=True)
    nlp_analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'safespeak_confession'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['category', 'status']),
        ]

    def __str__(self):
        return self.title

    @property
    def codename(self):
        """Return the public code name shown instead of an identity."""
        if self.poster_codename:
            return self.poster_codename
        if self.submitted_by_id:
            return user_codename(self.submitted_by_id)
        if self.pk is None:
            return 'Anonymous'
        return report_codename('confession', self.pk)


def report_image_upload_path(instance, filename):
    """Store report images under a random name to avoid leaking filenames."""
    extension = Path(filename).suffix.lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.webp'}:
        extension = ''
    return f'reports/images/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}'


class ReportImage(models.Model):
    """An image attached to a concern or confession."""

    concern = models.ForeignKey(
        Concern,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='images',
    )
    confession = models.ForeignKey(
        Confession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='images',
    )
    image = models.FileField(upload_to=report_image_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safespeak_report_image'
        ordering = ['uploaded_at']

    def __str__(self):
        report = self.concern or self.confession
        return f'Image for {report.title}' if report else 'Report image'

    def clean(self):
        if bool(self.concern_id) == bool(self.confession_id):
            raise ValidationError(
                'An image must belong to exactly one report.'
            )


class AdminAction(models.TextChoices):
    """Types of auditable actions recorded in the activity log."""

    REPORT_SUBMITTED = 'REPORT_SUBMITTED', 'Report submitted'
    STATUS_CHANGED = 'STATUS_CHANGED', 'Status changed'
    CATEGORY_CHANGED = 'CATEGORY_CHANGED', 'Category changed'
    CATEGORY_CREATED = 'CATEGORY_CREATED', 'Category created'
    CATEGORY_UPDATED = 'CATEGORY_UPDATED', 'Category updated'
    RESPONSE_SAVED = 'RESPONSE_SAVED', 'Response saved'
    NOTE_ADDED = 'NOTE_ADDED', 'Note added'
    COMMENT_ADDED = 'COMMENT_ADDED', 'Comment added'
    COMMENT_EDITED = 'COMMENT_EDITED', 'Comment edited'
    COMMENT_DELETED = 'COMMENT_DELETED', 'Comment deleted'
    USER_CREATED = 'USER_CREATED', 'User created'
    USER_UPDATED = 'USER_UPDATED', 'User updated'
    USER_ROLE_CHANGED = 'USER_ROLE_CHANGED', 'User role changed'
    USER_PASSWORD_RESET = 'USER_PASSWORD_RESET', 'Password reset'
    USER_ACTIVATED = 'USER_ACTIVATED', 'User activated'
    USER_DEACTIVATED = 'USER_DEACTIVATED', 'User deactivated'
    USER_DELETED = 'USER_DELETED', 'User deleted'
    SIGNED_IN = 'SIGNED_IN', 'Signed in'
    SIGNED_OUT = 'SIGNED_OUT', 'Signed out'


class AdminActivityLog(models.Model):
    """Audit trail of administrator and user account activity."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_activity_logs',
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='targeted_activity_logs',
    )
    action = models.CharField(max_length=32, choices=AdminAction.choices)
    concern = models.ForeignKey(
        Concern,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='activity_logs',
    )
    confession = models.ForeignKey(
        Confession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='activity_logs',
    )
    old_value = models.CharField(max_length=255, blank=True)
    new_value = models.CharField(max_length=255, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safespeak_admin_activity_log'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['action']),
            models.Index(fields=['target_user', '-created_at']),
        ]

    def __str__(self):
        report = self.concern or self.confession
        actor = self.actor or 'System'
        if report is None:
            return f'{self.get_action_display()} by {actor}'
        return f'{self.get_action_display()} on {report} by {actor}'

    @property
    def report(self):
        """Return the concern or confession this entry refers to."""
        return self.concern or self.confession

    @property
    def kind(self):
        """Return 'concern' or 'confession' for the linked report."""
        if self.concern_id:
            return 'concern'
        if self.confession_id:
            return 'confession'
        return None

    @property
    def icon(self):
        """Return the Font Awesome icon that represents this action."""
        return {
            AdminAction.SIGNED_IN: 'fa-right-to-bracket',
            AdminAction.SIGNED_OUT: 'fa-right-from-bracket',
            AdminAction.REPORT_SUBMITTED: 'fa-file-circle-plus',
            AdminAction.STATUS_CHANGED: 'fa-arrows-rotate',
            AdminAction.CATEGORY_CHANGED: 'fa-tags',
            AdminAction.CATEGORY_CREATED: 'fa-folder-plus',
            AdminAction.CATEGORY_UPDATED: 'fa-pen-to-square',
            AdminAction.RESPONSE_SAVED: 'fa-reply',
            AdminAction.NOTE_ADDED: 'fa-note-sticky',
            AdminAction.COMMENT_ADDED: 'fa-comment',
            AdminAction.COMMENT_EDITED: 'fa-comment-dots',
            AdminAction.COMMENT_DELETED: 'fa-comment-slash',
            AdminAction.USER_CREATED: 'fa-user-plus',
            AdminAction.USER_UPDATED: 'fa-user-pen',
            AdminAction.USER_ROLE_CHANGED: 'fa-user-shield',
            AdminAction.USER_PASSWORD_RESET: 'fa-key',
            AdminAction.USER_ACTIVATED: 'fa-user-check',
            AdminAction.USER_DEACTIVATED: 'fa-user-slash',
            AdminAction.USER_DELETED: 'fa-user-xmark',
        }.get(self.action, 'fa-clock-rotate-left')


class ReportComment(models.Model):
    """An anonymous comment on a concern or confession in the home feed."""

    concern = models.ForeignKey(
        Concern,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='comments',
    )
    confession = models.ForeignKey(
        Confession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='comments',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='report_comments',
    )
    body = models.TextField(max_length=1000)
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safespeak_report_comment'
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(concern__isnull=False, confession__isnull=True)
                    | Q(concern__isnull=True, confession__isnull=False)
                ),
                name='report_comment_exactly_one_parent',
            ),
        ]

    def __str__(self):
        report = self.concern or self.confession
        if report is None:
            return 'Orphan comment'
        return f'Comment on {report}'

    @property
    def codename(self):
        """Return the public code name shown instead of an identity."""
        if self.author_id:
            return user_codename(self.author_id)
        if self.pk is None:
            return 'Anonymous'
        return comment_codename(self.pk)
