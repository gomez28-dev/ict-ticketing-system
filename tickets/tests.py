import shutil
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Ticket


User = get_user_model()
TEST_MEDIA_ROOT = Path(__file__).resolve().parent / 'test_media'
TEST_MEDIA_ROOT.mkdir(exist_ok=True)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class TicketWorkflowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            username='adminuser',
            email='adminuser@example.com',
            password='pass1234',
            first_name='Admin',
            last_name='User',
            role='ADMIN',
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            username='employeeuser',
            email='employeeuser@example.com',
            password='pass1234',
            first_name='Employee',
            last_name='User',
            role='MEMBER',
        )
        self.ticket = Ticket.objects.create(
            first_name='Jane',
            last_name='Doe',
            school_name='North High',
            support_type='OTHER',
            description='Need help with network equipment.',
            status='PENDING',
            priority='MEDIUM',
        )

    def test_approve_request_sets_pending_acceptance_for_assigned_ticket(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('approve_request', args=[self.ticket.id]), {
            'priority': 'HIGH',
            'work_type': 'FIELD WORK',
            'assigned_staff': [self.employee.get_full_name()],
            'admin_feedback': 'Please review this urgently.',
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'PENDING_ACCEPTANCE')
        self.assertEqual(self.ticket.assignee, self.employee)

    def test_requests_view_reviewed_tab_includes_pending_acceptance_and_under_review(self):
        self.ticket.assignee = self.employee
        self.ticket.status = 'PENDING_ACCEPTANCE'
        self.ticket.save()
        under_review_ticket = Ticket.objects.create(
            first_name='John',
            last_name='Smith',
            school_name='East High',
            support_type='OTHER',
            description='Need CCTV adjustment.',
            status='UNDER_REVIEW',
            priority='LOW',
            assignee=self.employee,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('requests'))

        reviewed_requests = list(response.context['reviewed_requests'])
        self.assertIn(self.ticket, reviewed_requests)
        self.assertIn(under_review_ticket, reviewed_requests)

    def test_employee_cannot_mark_ticket_resolved_from_kanban_endpoint(self):
        self.ticket.status = 'UNDER_REVIEW'
        self.ticket.assignee = self.employee
        self.ticket.save()
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse('update_ticket_ajax', args=[self.ticket.id]),
            data='{"status":"RESOLVED"}',
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'UNDER_REVIEW')

    def test_submit_for_review_requires_attachment_and_updates_ticket(self):
        self.ticket.status = 'IN_PROGRESS'
        self.ticket.assignee = self.employee
        self.ticket.save()
        self.client.force_login(self.employee)

        missing_file_response = self.client.post(
            reverse('submit_for_review', args=[self.ticket.id]),
            {'resolution_notes': 'Replaced the cable and tested connectivity.'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(missing_file_response.status_code, 400)

        upload = SimpleUploadedFile('evidence.txt', b'proof of completion', content_type='text/plain')
        response = self.client.post(
            reverse('submit_for_review', args=[self.ticket.id]),
            data={
                'resolution_notes': 'Replaced the cable and tested connectivity.',
                'resolution_attachment': upload,
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'UNDER_REVIEW')
        self.assertEqual(self.ticket.resolution_notes, 'Replaced the cable and tested connectivity.')
        self.assertTrue(self.ticket.resolution_attachment.name.endswith('evidence.txt'))
