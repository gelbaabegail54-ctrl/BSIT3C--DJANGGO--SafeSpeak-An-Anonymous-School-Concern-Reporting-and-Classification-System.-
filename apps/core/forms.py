"""Forms for SafeSpeak account settings."""

import re

from django import forms
from django.core.exceptions import ValidationError

from .codenames import generated_user_codename
from .models import UserCodeName

CODE_NAME_PATTERN = re.compile(r'^[\w][\w .-]*$')
RESERVED_CODE_NAMES = {
    'admin',
    'administrator',
    'anonymous',
    'moderator',
    'safespeak',
    'system',
}


class CodeNameForm(forms.Form):
    """Validate a student's chosen community code name."""

    codename = forms.CharField(
        max_length=50,
        error_messages={
            'required': 'Enter a code name.',
            'max_length': 'Code name must be 50 characters or fewer.',
        },
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['codename'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'off',
            'placeholder': generated_user_codename(user.pk),
        })

    def clean_codename(self):
        value = ' '.join(self.cleaned_data['codename'].split())

        if len(value) < 3:
            raise ValidationError('Code name must be at least 3 characters.')
        if not CODE_NAME_PATTERN.match(value):
            raise ValidationError(
                'Use only letters, numbers, spaces, periods, hyphens, '
                'and underscores.'
            )
        if value.casefold() in RESERVED_CODE_NAMES:
            raise ValidationError('That code name is reserved.')

        duplicate = UserCodeName.objects.filter(name__iexact=value)
        if self.user.pk:
            duplicate = duplicate.exclude(user=self.user)
        if duplicate.exists():
            raise ValidationError('That code name is already in use.')

        return value
