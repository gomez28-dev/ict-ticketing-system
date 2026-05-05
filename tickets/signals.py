from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import Ticket, TicketAuditLog

@receiver(pre_save, sender=Ticket)
def log_ticket_changes(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_ticket = Ticket.objects.get(pk=instance.pk)
        except Ticket.DoesNotExist:
            return

        changed_by = getattr(instance, '_current_user', None)

        if old_ticket.status != instance.status:
            TicketAuditLog.objects.create(
                ticket=instance,
                changed_by=changed_by,
                action='Status Changed',
                old_value=old_ticket.get_status_display(),
                new_value=dict(Ticket.Status.choices).get(instance.status, instance.status)
            )

        if old_ticket.priority != instance.priority:
            TicketAuditLog.objects.create(
                ticket=instance,
                changed_by=changed_by,
                action='Priority Changed',
                old_value=old_ticket.get_priority_display(),
                new_value=dict(Ticket.Priority.choices).get(instance.priority, instance.priority)
            )

        # Check for assignment changes in admin_notes
        old_assignment = _extract_assignment(old_ticket.admin_notes)
        new_assignment = _extract_assignment(instance.admin_notes)
        
        if old_assignment != new_assignment:
            TicketAuditLog.objects.create(
                ticket=instance,
                changed_by=changed_by,
                action='Assignment Changed',
                old_value=old_assignment or 'Unassigned',
                new_value=new_assignment or 'Unassigned'
            )

def _extract_assignment(notes):
    if notes and 'Assigned to:' in notes:
        for line in notes.split('\n'):
            if 'Assigned to:' in line:
                return line.replace('Assigned to:', '').strip()
    return None
