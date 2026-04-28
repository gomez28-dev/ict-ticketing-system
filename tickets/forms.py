from django import forms
from .models import Ticket

class PublicTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            'first_name', 'last_name', 'middle_name',
            'contact_number', 'email',
            'school_name',
            'support_type', 'work_type', 'description'
        ]


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
