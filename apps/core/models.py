"""Models for the SafeSpeak anonymous school concern reporting system."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Category(models.Model):
    """Classification category for concerns (e.g., bullying, facilities)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
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

    ticket_number = models.CharField(max_length=36, unique=True, editable=False, default=uuid.uuid4)
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

    class Meta:
        db_table = 'safespeak_concern'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['ticket_number']),
        ]

    def __str__(self):
        return f'{self.ticket_number}: {self.title}'


class ConcernNote(models.Model):
    """Internal notes staff attach to a concern."""

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
        return f'Note on {self.concern.ticket_number} by {self.created_at:%Y-%m-%d}'


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
        return f'Response to {self.concern.ticket_number}'


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
        return f'Response to {self.confession.ticket_number}'


class Confession(models.Model):
    """An anonymous confession submitted through SafeSpeak."""

    ticket_number = models.CharField(max_length=36, unique=True, editable=False, default=uuid.uuid4)
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

    class Meta:
        db_table = 'safespeak_confession'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['ticket_number']),
        ]

    def __str__(self):
        return f'{self.ticket_number}: {self.title}'


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
