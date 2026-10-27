from django.contrib import admin

from .models import (
    AdminActivityLog,
    Category,
    Concern,
    ConcernNote,
    ConcernResponse,
    Confession,
    ConfessionResponse,
    ReportComment,
    ReportImage,
)


class ConcernNoteInline(admin.TabularInline):
    model = ConcernNote
    extra = 0


class ConcernResponseInline(admin.StackedInline):
    model = ConcernResponse
    extra = 0


class ConcernImageInline(admin.TabularInline):
    model = ReportImage
    fk_name = 'concern'
    extra = 0
    exclude = ('confession',)
    readonly_fields = ('uploaded_at',)


class ConfessionImageInline(admin.TabularInline):
    model = ReportImage
    fk_name = 'confession'
    extra = 0
    exclude = ('concern',)
    readonly_fields = ('uploaded_at',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(Concern)
class ConcernAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'status', 'is_urgent', 'submitted_at')
    list_filter = ('status', 'category', 'is_urgent')
    search_fields = ('title', 'description')
    inlines = (ConcernNoteInline, ConcernResponseInline, ConcernImageInline)
    readonly_fields = ('submitted_at', 'updated_at', 'resolved_at')


@admin.register(ConcernNote)
class ConcernNoteAdmin(admin.ModelAdmin):
    list_display = ('concern', 'created_at')
    search_fields = ('body',)


@admin.register(Confession)
class ConfessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'status', 'is_urgent', 'submitted_at')
    list_filter = ('status', 'category', 'is_urgent')
    search_fields = ('title', 'description')
    readonly_fields = ('submitted_at', 'updated_at', 'resolved_at')
    inlines = (ConfessionImageInline,)


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


@admin.register(ReportImage)
class ReportImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'concern', 'confession', 'image', 'uploaded_at')
    list_filter = ('uploaded_at',)
    readonly_fields = ('uploaded_at',)


@admin.register(AdminActivityLog)
class AdminActivityLogAdmin(admin.ModelAdmin):
    """Read-only audit trail of administrator actions."""

    list_display = ('created_at', 'actor', 'action', 'target_user', 'concern', 'confession')
    list_filter = ('action', 'created_at')
    search_fields = (
        'actor__username',
        'target_user__username',
        'concern__title',
        'confession__title',
        'detail',
    )
    readonly_fields = ('actor', 'target_user', 'action', 'concern', 'confession', 'old_value', 'new_value', 'detail', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
