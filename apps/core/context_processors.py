"""Template context shared across SafeSpeak pages."""

from .codenames import user_codename


def codename(request):
    """Expose the signed-in user's community code name to templates."""
    if not request.user.is_authenticated:
        return {}
    return {'current_codename': user_codename(request.user.pk)}
