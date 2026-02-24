from django import forms
from .models import Ticket

class PublicTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        # These are the exact fields we want the public to fill out
        fields = [
            'school_district', 'school_name', 'support_type',
            'description', 'first_name', 'last_name',
            'middle_name', 'contact_number', 'email'
        ]