from django import forms
from .models import Ticket

class PublicTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            'first_name', 'last_name', 'middle_name',
            'contact_number', 'email',
            'school_district', 'school_name',
            'support_type', 'work_type', 'description'
        ]