import shutil
from pathlib import Path
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Ticket, School, PasswordResetOTP
from .ml_service import validate_ticket_description_for_ai


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

    def test_approve_request_sets_pending_acceptance_and_assigned_at(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        response = self.client.post(reverse('approve_request', args=[self.ticket.id]), {
            'priority': 'HIGH',
            'work_type': 'FIELD WORK',
            'start_date': today.strftime('%Y-%m-%d'),
            'end_date': tomorrow.strftime('%Y-%m-%d'),
            'scheduled_start_time': '09:00',
            'scheduled_end_time': '12:00',
            'assigned_staff': [self.employee.get_full_name()],
            'admin_feedback': 'Please review this urgently.',
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'PENDING_ACCEPTANCE')
        self.assertEqual(self.ticket.assignee, self.employee)
        self.assertIsNotNone(self.ticket.assigned_at)

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


class TicketAssignmentValidationAndAITests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_validator',
            email='admin_val@example.com',
            password='pass1234',
            first_name='Alice',
            last_name='Admin',
            role='ADMIN',
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            username='emp_validator',
            email='emp_val@example.com',
            password='pass1234',
            first_name='Juan',
            last_name='Pedro',
            role='MEMBER',
            expertise='NETWORK, CCTV',
        )
        self.ticket = Ticket.objects.create(
            first_name='Maria',
            last_name='Clara',
            school_name='Mabini Elementary School',
            support_type='NETWORK_MAINTENANCE',
            description='The main office network router has failed and teachers cannot connect to the internet.',
            status='PENDING',
            priority='MEDIUM',
        )

    def test_past_assigned_start_date_validation_rejected(self):
        self.client.force_login(self.admin)
        past_date = timezone.localdate() - timedelta(days=2)
        end_date = timezone.localdate() + timedelta(days=1)

        response = self.client.post(reverse('approve_request', args=[self.ticket.id]), {
            'priority': 'HIGH',
            'work_type': 'FIELD WORK',
            'start_date': past_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'assigned_staff': [self.employee.get_full_name()],
        }, follow=True)

        self.assertContains(response, "Scheduled start date cannot be in the past.")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'PENDING')
        self.assertIsNone(self.ticket.assigned_at)

    def test_end_date_before_start_date_validation_rejected(self):
        self.client.force_login(self.admin)
        start_date = timezone.localdate() + timedelta(days=3)
        earlier_end_date = timezone.localdate() + timedelta(days=1)

        response = self.client.post(reverse('approve_request', args=[self.ticket.id]), {
            'priority': 'HIGH',
            'work_type': 'FIELD WORK',
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': earlier_end_date.strftime('%Y-%m-%d'),
            'assigned_staff': [self.employee.get_full_name()],
        }, follow=True)

        self.assertContains(response, "Scheduled end date cannot be earlier than the start date.")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'PENDING')

    def test_end_time_before_start_time_validation_rejected(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()

        response = self.client.post(reverse('approve_request', args=[self.ticket.id]), {
            'priority': 'HIGH',
            'work_type': 'FIELD WORK',
            'start_date': today.strftime('%Y-%m-%d'),
            'end_date': today.strftime('%Y-%m-%d'),
            'scheduled_start_time': '14:00',
            'scheduled_end_time': '10:00',
            'assigned_staff': [self.employee.get_full_name()],
        }, follow=True)

        self.assertContains(response, "Scheduled end time must be strictly after the start time.")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'PENDING')

    def test_assigned_at_timestamp_lifecycle_assigned_and_declined(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()

        # 1. Approve & Assign ticket
        response = self.client.post(reverse('approve_request', args=[self.ticket.id]), {
            'priority': 'HIGH',
            'work_type': 'FIELD WORK',
            'start_date': today.strftime('%Y-%m-%d'),
            'end_date': today.strftime('%Y-%m-%d'),
            'scheduled_start_time': '09:00',
            'scheduled_end_time': '11:00',
            'assigned_staff': [self.employee.get_full_name()],
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.assigned_at)
        self.assertEqual(self.ticket.status, 'PENDING_ACCEPTANCE')

        # 2. Employee declines ticket back to unassigned queue
        self.client.force_login(self.employee)
        decline_response = self.client.post(reverse('decline_assignment', args=[self.ticket.id]), {
            'decline_reason': 'Conflict with another school visit'
        })
        self.assertRedirects(decline_response, reverse('my_tickets'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'PENDING')
        self.assertIsNone(self.ticket.assignee)
        self.assertIsNone(self.ticket.assigned_at)

    def test_ai_description_pre_validation(self):
        # Valid description
        is_valid, msg = validate_ticket_description_for_ai("Internet connection in the computer lab is completely down.")
        self.assertTrue(is_valid)
        self.assertEqual(msg, "")

        # Too short (< 20 chars)
        is_valid, msg = validate_ticket_description_for_ai("Fix pc now")
        self.assertFalse(is_valid)
        self.assertIn("minimum 20 characters", msg)

        # Too few words (< 3 words)
        is_valid, msg = validate_ticket_description_for_ai("Unbreakablerequestdescriptionhere")
        self.assertFalse(is_valid)
        self.assertIn("minimum 3 words", msg)

        # Repetitive characters
        is_valid, msg = validate_ticket_description_for_ai("The network cable is aaaaaaaaaaaaaaaaa broken")
        self.assertFalse(is_valid)
        self.assertIn("repetitive", msg)

        # Repetitive single word spam
        is_valid, msg = validate_ticket_description_for_ai("problem problem problem problem problem")
        self.assertFalse(is_valid)
        self.assertIn("repetitive", msg)

    def test_triage_view_displays_ai_notice_for_insufficient_description(self):
        bad_ticket = Ticket.objects.create(
            first_name='Shorty',
            last_name='User',
            school_name='Rizal High School',
            support_type='OTHER',
            description='Broken!',
            status='PENDING',
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ticket_triage', args=[bad_ticket.id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['ai_valid'])
        self.assertContains(response, 'AI Analysis Notice')
        self.assertContains(response, 'Description does not contain enough detail for AI analysis')


class PasswordResetTests(TestCase):
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
        self.school = School.objects.create(
            school_id='123456',
            name='Test School',
            ict_email='school@example.com',
        )
        self.school.set_password('pass1234')
        self.school.save()

    def test_forgot_password_routes_correctly_for_school_and_admin(self):
        response_school = self.client.get(reverse('forgot_password') + '?from=school')
        self.assertEqual(response_school.status_code, 200)
        self.assertContains(response_school, 'Back to School Login')

        response_admin = self.client.get(reverse('forgot_password') + '?from=admin')
        self.assertEqual(response_admin.status_code, 200)
        self.assertContains(response_admin, 'Back to Login')

        response = self.client.post(reverse('forgot_password'), {'email': 'school@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['otp_email'], 'school@example.com')
        otp = PasswordResetOTP.objects.filter(school=self.school).first()
        self.assertIsNotNone(otp)

        response = self.client.post(reverse('forgot_password'), {'email': 'adminuser@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['otp_email'], 'adminuser@example.com')
        otp_admin = PasswordResetOTP.objects.filter(user=self.admin).first()
        self.assertIsNotNone(otp_admin)

        session = self.client.session
        session['otp_email'] = 'school@example.com'
        session.save()
        response_verify = self.client.post(reverse('verify_otp'), {'code': otp.code})
        self.assertRedirects(response_verify, reverse('reset_password_confirm'))

        session = self.client.session
        session['otp_email'] = 'adminuser@example.com'
        session.save()
        response_verify_admin = self.client.post(reverse('verify_otp'), {'code': otp_admin.code})
        self.assertRedirects(response_verify_admin, reverse('reset_password_confirm'))
