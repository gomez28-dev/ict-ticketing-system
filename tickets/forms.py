import re
from django import forms
from .models import Ticket


def validate_ph_mobile(value):
    """
    Validates that a contact number is a valid 11-digit Philippine mobile number
    starting with '09'.
    """
    cleaned = value.strip()
    if not re.fullmatch(r'09\d{9}', cleaned):
        raise forms.ValidationError(
            "Please enter a valid 11-digit Philippine mobile number starting with 09 (e.g., 09123456789)."
        )
    return cleaned


class PublicTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            'first_name', 'last_name', 'middle_name',
            'contact_number', 'email',
            'school_name',
            'support_type', 'work_type', 'description'
        ]

    def clean_contact_number(self):
        value = self.cleaned_data.get('contact_number', '')
        if value:
            return validate_ph_mobile(value)
        return value


class SubmitForReviewForm(forms.Form):
    resolution_notes = forms.CharField(
        required=True,
        strip=True,
        widget=forms.Textarea(attrs={'rows': 3}),
    )
    resolution_attachment = forms.FileField(required=True)

    def clean_resolution_notes(self):
        resolution_notes = (self.cleaned_data.get('resolution_notes') or '').strip()
        if not resolution_notes:
            raise forms.ValidationError('Please provide a resolution summary before submitting for review.')
        return resolution_notes
