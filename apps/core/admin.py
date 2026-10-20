from django.contrib import admin

from .models import (
    Category,
    Concern,
    ConcernNote,
    ConcernResponse,
    Confession,
    ConfessionResponse,
    ReportComment,
)


class ConcernNoteInline(admin.TabularInline):
    model = ConcernNote
    extra = 0


class ConcernResponseInline(admin.StackedInline):
    model = ConcernResponse
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(Concern)
class ConcernAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'title', 'category', 'status', 'is_urgent', 'submitted_at')
    list_filter = ('status', 'category', 'is_urgent')
    search_fields = ('ticket_number', 'title', 'description')
    inlines = (ConcernNoteInline, ConcernResponseInline)
    readonly_fields = ('ticket_number', 'submitted_at', 'updated_at', 'resolved_at')


@admin.register(ConcernNote)
class ConcernNoteAdmin(admin.ModelAdmin):
    list_display = ('concern', 'created_at')
    search_fields = ('body',)


@admin.register(Confession)
class ConfessionAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'title', 'category', 'status', 'is_urgent', 'submitted_at')
    list_filter = ('status', 'category', 'is_urgent')
    search_fields = ('ticket_number', 'title', 'description')
    readonly_fields = ('ticket_number', 'submitted_at', 'updated_at', 'resolved_at')


@admin.register(ConcernResponse)
class ConcernResponseAdmin(admin.ModelAdmin):
    list_display = ('concern', 'is_public', 'responded_by', 'created_at')
    list_filter = ('is_public',)


@admin.register(ConfessionResponse)
class ConfessionResponseAdmin(admin.ModelAdmin):
    list_display = ('confession', 'is_public', 'responded_by', 'created_at')
    list_filter = ('is_public',)


@admin.register(ReportComment)
class ReportCommentAdmin(admin.ModelAdmin):
    list_display = ('concern', 'confession', 'author', 'is_edited', 'created_at')
    list_filter = ('is_edited', 'created_at')
    search_fields = ('body',)
    readonly_fields = ('created_at',)
