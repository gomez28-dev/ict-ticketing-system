import shutil
from pathlib import Path
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Ticket, School, PasswordResetOTP, SchoolAccountRequest, TicketAuditLog, UserSettings
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

    def test_send_otp_email_utility(self):
        from django.core import mail
        from tickets.email_utils import send_otp_email
        success, error = send_otp_email('test@gmail.com', '123456', recipient_name='Juan Dela Cruz')
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ['test@gmail.com'])
        self.assertIn('123456', sent_email.body)
        self.assertIn('Juan Dela Cruz', sent_email.body)

    def test_forgot_password_shows_error_when_email_fails(self):
        from unittest.mock import patch
        with patch('tickets.views.send_otp_email', return_value=(False, 'Connection timed out')):
            response = self.client.post(reverse('forgot_password'), {'email': 'school@example.com'})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Unable to send verification code')

    def test_test_smtp_management_command(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('test_smtp', 'testrecipient@gmail.com', stdout=out)
        output = out.getvalue()
        self.assertIn('SMTP Configuration Diagnostic Tool', output)
        self.assertTrue('SUCCESS' in output or 'SIMULATED' in output)

    def test_forgot_password_unregistered_email_shows_error(self):
        response = self.client.post(reverse('forgot_password'), {'email': 'nonexistent@gmail.com'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No account found with this email address')

    def test_forgot_password_registered_gmail_succeeds(self):
        # Update school's email to a gmail account
        self.school.ict_email = 'school.coordinator@gmail.com'
        self.school.save()
        response = self.client.post(reverse('forgot_password'), {'email': 'school.coordinator@gmail.com'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Check Your Email')
        self.assertEqual(self.client.session['otp_email'], 'school.coordinator@gmail.com')

    def test_request_school_access_with_gmail(self):
        # Create a new test school
        new_school = School.objects.create(
            name="Gmail Test Elementary School",
            school_id="119999",
            district="District 1",
        )
        data = {
            'school': new_school.id,
            'ict_name': 'Test Coordinator',
            'email': 'coordinator.test@gmail.com',
            'contact_number': '09123456789',
        }
        response = self.client.post(reverse('request_access'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Request Submitted')
        req = SchoolAccountRequest.objects.filter(email='coordinator.test@gmail.com').first()
        self.assertIsNotNone(req)
        self.assertFalse(req.domain_verified)  # non-deped is flagged for manual admin review


class AnalyticsReportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_analytics',
            email='admin_analytics@example.com',
            password='password123',
            first_name='Admin',
            last_name='Tester',
            role='ADMIN',
            is_staff=True,
        )
        self.member = User.objects.create_user(
            username='member_user',
            email='member@example.com',
            password='password123',
            first_name='Juan',
            last_name='Dela Cruz',
            role='MEMBER',
            overall_rating=4.5,
        )
        # Create test tickets
        Ticket.objects.create(
            ticket_number='TKT-2026-9001',
            school_name='Valenzuela National High School',
            support_type='CCTV',
            status='COMPLETED',
            admin_notes='Assigned to: Juan Dela Cruz',
            description='Test CCTV maintenance issue'
        )
        Ticket.objects.create(
            ticket_number='TKT-2026-9002',
            school_name='Polo National High School',
            support_type='NETWORK_MAINTENANCE',
            status='PENDING',
            description='Network configuration support'
        )

    def test_analytics_dashboard_requires_admin(self):
        # Unauthenticated redirects to dashboard login
        response = self.client.get(reverse('analytics'))
        self.assertRedirects(response, f"{reverse('dashboard')}?next={reverse('analytics')}", fetch_redirect_response=False)

        # Member user redirects to dashboard
        self.client.force_login(self.member)
        response = self.client.get(reverse('analytics'))
        self.assertRedirects(response, f"{reverse('dashboard')}?next={reverse('analytics')}")

        # Admin user succeeds
        self.client.force_login(self.admin)
        response = self.client.get(reverse('analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Performance & Analytics')
        self.assertContains(response, 'Export Report (PDF)')

    def test_analytics_report_print_view(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('analytics_report_print'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DIVISION OFFICE OF VALENZUELA')
        self.assertContains(response, 'DASHBOARD ANALYTICS AND PERFORMANCE REPORT')
        self.assertContains(response, 'I. SYSTEM SUMMARY')
        self.assertContains(response, 'II. SCHOOL COMPLAINT / REQUEST ANALYSIS')
        self.assertContains(response, 'III. MOST REQUESTED SERVICES')
        self.assertContains(response, 'IV. EMPLOYEE PERFORMANCE ANALYSIS')
        self.assertContains(response, 'V. SYSTEM ANALYTICS')
        self.assertContains(response, 'VI. REPORT CERTIFICATION')
        self.assertContains(response, 'Valenzuela National High School')
        self.assertContains(response, 'Juan Dela Cruz')


class SchoolAccountApprovalWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_approver',
            email='admin_approver@deped.gov.ph',
            password='password123',
            first_name='Admin',
            last_name='Approver',
            role='ADMIN',
            is_staff=True,
        )
        self.school = School.objects.create(
            name="Approval Test National High School",
            school_id="320999",
            district="District 2",
        )
        self.request = SchoolAccountRequest.objects.create(
            school=self.school,
            ict_name="Maria Santos",
            email="maria.santos@gmail.com",
            contact_number="09123456789",
            status="PENDING",
        )

    def test_generate_temporary_password(self):
        from tickets.email_utils import generate_temporary_password
        pwd1 = generate_temporary_password()
        pwd2 = generate_temporary_password()
        self.assertTrue(pwd1.startswith("DepEd-"))
        self.assertTrue(pwd1.endswith("!"))
        self.assertNotEqual(pwd1, pwd2)
        self.assertEqual(len(pwd1), len("DepEd-") + 6 + 1)

    def test_send_school_approval_email_utility(self):
        from django.core import mail
        from tickets.email_utils import send_school_approval_email
        success, error = send_school_approval_email(self.request, "DepEd-Test123!")
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["maria.santos@gmail.com"])
        self.assertIn("Approval Test National High School", sent.body)
        self.assertIn("320999", sent.body)
        self.assertIn("DepEd-Test123!", sent.body)
        # Check HTML alternative
        self.assertTrue(any(content_type == 'text/html' for content, content_type in sent.alternatives))

    def test_approve_account_request_success(self):
        from django.core import mail
        self.client.force_login(self.admin)
        response = self.client.post(reverse('approve_account_request', args=[self.request.id]))
        self.assertRedirects(response, reverse('schools_management'))

        # Request should now be APPROVED (not deleted)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'APPROVED')

        # School record updated
        self.school.refresh_from_db()
        self.assertEqual(self.school.ict_first_name, "Maria")
        self.assertEqual(self.school.ict_last_name, "Santos")
        self.assertEqual(self.school.ict_email, "maria.santos@gmail.com")
        self.assertEqual(self.school.ict_contact_number, "09123456789")

        # Email dispatched
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("maria.santos@gmail.com", mail.outbox[0].to)

        # School password properly hashed
        self.assertTrue(self.school.password.startswith('pbkdf2_'))

    def test_approve_account_request_email_failure_warning(self):
        from unittest.mock import patch
        self.client.force_login(self.admin)
        with patch('tickets.views.send_school_approval_email', return_value=(False, "SMTP Timeout")):
            response = self.client.post(reverse('approve_account_request', args=[self.request.id]), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'notification email failed to send')
            self.assertContains(response, 'Generated temporary password is:')
            self.request.refresh_from_db()
            self.assertEqual(self.request.status, 'APPROVED')

    def test_send_school_rejection_email_utility(self):
        from django.core import mail
        from tickets.email_utils import send_school_rejection_email
        success, error = send_school_rejection_email(self.request)
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["maria.santos@gmail.com"])
        self.assertIn("Approval Test National High School", sent.body)
        self.assertIn("320999", sent.body)
        self.assertIn("request-access", sent.body)
        # Check HTML alternative
        self.assertTrue(any(content_type == 'text/html' for content, content_type in sent.alternatives))

    def test_reject_account_request_success(self):
        from django.core import mail
        self.client.force_login(self.admin)
        response = self.client.post(reverse('reject_account_request', args=[self.request.id]))
        self.assertRedirects(response, reverse('schools_management'))

        # Request should now be REJECTED (not deleted)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'REJECTED')

        # Email dispatched
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("maria.santos@gmail.com", mail.outbox[0].to)

    def test_reject_account_request_email_failure_warning(self):
        from unittest.mock import patch
        self.client.force_login(self.admin)
        with patch('tickets.views.send_school_rejection_email', return_value=(False, "SMTP Timeout")):
            response = self.client.post(reverse('reject_account_request', args=[self.request.id]), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'notification email failed to send')
            self.request.refresh_from_db()
            self.assertEqual(self.request.status, 'REJECTED')

    def test_approve_already_processed_request_redirects_gracefully(self):
        self.client.force_login(self.admin)
        self.request.status = 'APPROVED'
        self.request.save()
        response = self.client.post(reverse('approve_account_request', args=[self.request.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already been processed')

    def test_reject_already_processed_request_redirects_gracefully(self):
        self.client.force_login(self.admin)
        self.request.status = 'REJECTED'
        self.request.save()
        response = self.client.post(reverse('reject_account_request', args=[self.request.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already been processed')


class SecurityAndCacheTests(TestCase):
    def test_login_pages_never_cache_and_ensure_csrf_cookie(self):
        for route_name in ['admin_login', 'school_login', 'request_access']:
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 200)
            cache_control = response.headers.get('Cache-Control', '')
            self.assertIn('no-cache', cache_control)
            self.assertIn('no-store', cache_control)
            # Ensure CSRF cookie is delivered to browser
            self.assertIn('csrftoken', response.cookies)

    def test_health_check_endpoint(self):
        response = self.client.get(reverse('health_check'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')

    def test_custom_csrf_failure_view_returns_403_and_branded_template(self):
        from django.test import RequestFactory
        from tickets.views import csrf_failure

        factory = RequestFactory()
        
        # Test admin source path
        req_admin = factory.post('/login/', HTTP_ORIGIN='http://malicious.example.com')
        resp_admin = csrf_failure(req_admin, reason="CSRF cookie not set.")
        self.assertEqual(resp_admin.status_code, 403)
        self.assertIn(b"Session Security Notice", resp_admin.content)
        self.assertIn(b"/admin-login/", resp_admin.content)

        # Test school portal path
        req_school = factory.post('/school-login/', HTTP_ORIGIN='http://malicious.example.com')
        resp_school = csrf_failure(req_school, reason="CSRF token missing.")
        self.assertEqual(resp_school.status_code, 403)
        self.assertIn(b"Session Security Notice", resp_school.content)
        self.assertIn(b'href="/"', resp_school.content)


class KanbanUnresolvedReasonTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='adminuser2',
            email='adminuser2@example.com',
            password='pass1234',
            first_name='Admin',
            last_name='Two',
            role='ADMIN',
            is_staff=True,
        )
        self.ticket = Ticket.objects.create(
            first_name='Juan',
            last_name='Dela Cruz',
            school_name='Rizal High',
            support_type='HARDWARE',
            description='Defective router in laboratory.',
            status='IN_PROGRESS',
            priority='HIGH',
        )

    def test_unresolved_without_reason_returns_400(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('update_ticket_ajax', args=[self.ticket.id]),
            data='{"status": "UNRESOLVED"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        json_data = response.json()
        self.assertFalse(json_data.get('success'))
        self.assertIn('unresolved reason is mandatory', json_data.get('message', '').lower())
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'IN_PROGRESS')

    def test_unresolved_with_reason_json_succeeds_and_logs_notes(self):
        self.client.force_login(self.admin)
        payload = {
            'status': 'UNRESOLVED',
            'unresolved_reason': 'Parts unavailable from supplier until next month.',
        }
        import json
        response = self.client.post(
            reverse('update_ticket_ajax', args=[self.ticket.id]),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('success'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'UNRESOLVED')
        self.assertIn('Parts unavailable from supplier', self.ticket.admin_notes)
        self.assertIn('Admin Two', self.ticket.admin_notes)

    def test_unresolved_with_reason_multipart_succeeds_with_attachment(self):
        self.client.force_login(self.admin)
        evidence = SimpleUploadedFile("evidence.jpg", b"fake_evidence_image_bytes", content_type="image/jpeg")
        response = self.client.post(
            reverse('update_ticket_ajax', args=[self.ticket.id]),
            data={
                'status': 'UNRESOLVED',
                'unresolved_reason': 'Waiting for client school approval signature.',
                'unresolved_attachment': evidence,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('success'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'UNRESOLVED')
        self.assertTrue(self.ticket.resolution_attachment)
        self.assertIn('Waiting for client school approval', self.ticket.admin_notes)


class AdminProfileSettingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='sysadmin',
            email='sysadmin@deped.gov.ph',
            password='pass1234',
            first_name='System',
            last_name='Admin',
            role='ADMIN',
            is_staff=True,
            bio='DepEd Division ICT Head',
        )
        self.employee = User.objects.create_user(
            username='empuser',
            email='empuser@deped.gov.ph',
            password='pass1234',
            first_name='Tech',
            last_name='Specialist',
            role='MEMBER',
        )

    def test_settings_view_shows_admin_profile_context(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['profile_user'], self.admin)
        self.assertTrue(response.context['is_admin_user'])
        self.assertContains(response, 'DepEd Division ICT Head')

    def test_settings_update_profile_updates_info(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('settings'), {
            'action': 'update_profile',
            'first_name': 'Chief',
            'last_name': 'Officer',
            'email': 'chiefofficer@deped.gov.ph',
            'bio': 'Updated official bio details',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, 'Chief')
        self.assertEqual(self.admin.last_name, 'Officer')
        self.assertEqual(self.admin.email, 'chiefofficer@deped.gov.ph')
        self.assertEqual(self.admin.bio, 'Updated official bio details')
        self.assertContains(response, 'Account profile updated successfully')

    def test_admin_visiting_own_employee_profile_redirects_to_settings(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('employee_profile', args=[self.admin.id]))
        self.assertRedirects(response, reverse('settings'))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SignedPhysicalJRFTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='approver',
            email='approver@deped.gov.ph',
            password='pass1234',
            role='ADMIN',
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            username='worker',
            email='worker@deped.gov.ph',
            password='pass1234',
            role='MEMBER',
        )
        self.ticket = Ticket.objects.create(
            first_name='Principal',
            last_name='Santos',
            school_name='Central Elementary',
            support_type='NETWORK',
            description='Fiber cable re-termination needed.',
            status='UNDER_REVIEW',
            assignee=self.employee,
        )

    def test_upload_signed_jrf_saves_attachment_and_redirects(self):
        self.client.force_login(self.admin)
        pdf_file = SimpleUploadedFile("signed_jrf_sample.pdf", b"%PDF-1.4 sample content", content_type="application/pdf")
        response = self.client.post(
            reverse('upload_signed_jrf', args=[self.ticket.id]),
            {'signed_jrf_attachment': pdf_file},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.signed_jrf_attachment)
        self.assertIn('signed_jrfs', self.ticket.signed_jrf_attachment.name)
        self.assertContains(response, 'Signed physical JRF document uploaded')

    def test_submit_performance_review_saves_signed_jrf_attachment(self):
        self.client.force_login(self.admin)
        img_file = SimpleUploadedFile("signed_scan.png", b"fake_png_data", content_type="image/png")
        response = self.client.post(
            reverse('submit_performance_review', args=[self.ticket.id]),
            {
                'rating_quality': 5,
                'rating_timeliness': 5,
                'rating_communication': 5,
                'review_notes': 'Great job on the fiber cable.',
                'signed_jrf_attachment': img_file,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'COMPLETED')
        self.assertTrue(self.ticket.signed_jrf_attachment)
        self.assertIsNotNone(self.ticket.actual_completion_date)


class PreDefenseHardeningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_predefense',
            email='admin_predefense@deped.gov.ph',
            password='pass1234',
            role='ADMIN',
            is_staff=True,
        )
        self.ticket = Ticket.objects.create(
            first_name='Principal',
            last_name='Reyes',
            school_name='Valenzuela West Elementary',
            support_type='HARDWARE',
            description='Defective computer monitors in ICT lab.',
            status='IN_PROGRESS',
            priority='LOW',
        )

    def test_password_reset_otp_str_without_school(self):
        otp = PasswordResetOTP.objects.create(
            user=self.admin,
            code='654321',
        )
        otp_str = str(otp)
        self.assertIn('admin_predefense@deped.gov.ph', otp_str)
        self.assertIn('654321', otp_str)
        self.assertIn('[Valid]', otp_str)

    def test_update_ticket_priority_choices_valid(self):
        self.client.force_login(self.admin)
        import json
        response = self.client.post(
            reverse('update_ticket_ajax', args=[self.ticket.id]),
            data=json.dumps({'priority': 'HIGH'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, 'HIGH')

    def test_calculate_overall_rating_supports_score_one_and_floats(self):
        from .ml_service import calculate_overall_rating
        rating_min = calculate_overall_rating(1, 1, 1)
        self.assertEqual(rating_min, 1.0)
        rating_float = calculate_overall_rating(4.5, 3.5, 4.0)
        expected = round((4.5 * 0.40) + (3.5 * 0.30) + (4.0 * 0.30), 2)
        self.assertEqual(rating_float, expected)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, f"{reverse('admin_login')}?next={reverse('dashboard')}")

    def test_recommend_staff_deterministic(self):
        from .ml_service import recommend_staff
        u1 = User.objects.create_user(
            username='tech_a',
            email='tech_a@deped.gov.ph',
            first_name='Alpha',
            last_name='Tech',
            role='MEMBER',
            expertise='HARDWARE',
            overall_rating=4.5,
        )
        u2 = User.objects.create_user(
            username='tech_b',
            email='tech_b@deped.gov.ph',
            first_name='Beta',
            last_name='Tech',
            role='MEMBER',
            expertise='HARDWARE',
            overall_rating=4.8,
        )
        rec = recommend_staff('Valenzuela West Elementary', 'HARDWARE')
        # Both have 0 active load, but u2 (Beta Tech) has higher rating (4.8 > 4.5)
        self.assertEqual(rec['recommended_name'], 'Beta Tech')

    def test_school_login_generic_error_message(self):
        # 1. Non-existent school ID
        resp_nonexistent = self.client.post(reverse('school_login'), {'school_id': 'NONEXISTENT', 'password': 'wrong'})
        messages_nonexistent = list(resp_nonexistent.context['messages']) if resp_nonexistent.context else []
        self.assertTrue(any('Invalid School ID or password.' in str(m) for m in messages_nonexistent))

        # 2. Existing school with wrong password
        school = School.objects.create(name='Test School Generic', school_id='SCH-GEN-01')
        school.set_password('CorrectPass123!')
        school.save()
        resp_wrongpass = self.client.post(reverse('school_login'), {'school_id': 'SCH-GEN-01', 'password': 'wrong'})
        messages_wrongpass = list(resp_wrongpass.context['messages']) if resp_wrongpass.context else []
        self.assertTrue(any('Invalid School ID or password.' in str(m) for m in messages_wrongpass))

    def test_admin_login_generic_error_message(self):
        # Non-existent user
        resp1 = self.client.post(reverse('admin_login'), {'email': 'nobody@example.com', 'password': 'pass'})
        self.assertContains(resp1, 'Invalid email or password.')

        # Existing user wrong password
        resp2 = self.client.post(reverse('admin_login'), {'email': self.admin.email, 'password': 'wrongpassword'})
        self.assertContains(resp2, 'Invalid email or password.')

    def test_backlog_restricted_to_admin_only(self):
        # Anonymous redirects to admin_login
        resp_anon = self.client.get(reverse('backlog'))
        self.assertEqual(resp_anon.status_code, 302)

        # Standard employee redirected to dashboard
        emp = User.objects.create_user(
            username='emp_test_backlog',
            email='emp_test_backlog@deped.gov.ph',
            password='pass',
            role='MEMBER'
        )
        self.client.force_login(emp)
        resp_emp = self.client.get(reverse('backlog'))
        self.assertRedirects(resp_emp, f"{reverse('dashboard')}?next={reverse('backlog')}")

        # Admin gets 200
        self.client.force_login(self.admin)
        resp_admin = self.client.get(reverse('backlog'))
        self.assertEqual(resp_admin.status_code, 200)

    def test_employee_receipt_unauthenticated_redirect(self):
        resp = self.client.get(reverse('employee_receipt', kwargs={'ticket_id': self.ticket.id}))
        self.assertRedirects(resp, reverse('admin_login'))

    def test_status_transition_guard_blocks_invalid_and_duplicate(self):
        import json
        self.client.force_login(self.admin)
        self.ticket.status = 'IN_PROGRESS'
        self.ticket.save()

        # 1. Duplicate status transition blocked
        resp_dup = self.client.post(
            reverse('update_ticket_ajax', kwargs={'ticket_id': self.ticket.id}),
            data=json.dumps({'status': 'IN_PROGRESS'}),
            content_type='application/json'
        )
        self.assertEqual(resp_dup.status_code, 400)
        self.assertIn('already', resp_dup.json().get('message', '').lower())

        # 2. Backward / invalid transition blocked (e.g. IN_PROGRESS -> PENDING or SCHEDULED)
        resp_inv = self.client.post(
            reverse('update_ticket_ajax', kwargs={'ticket_id': self.ticket.id}),
            data=json.dumps({'status': 'SCHEDULED'}),
            content_type='application/json'
        )
        self.assertEqual(resp_inv.status_code, 400)
        self.assertIn('status transition', resp_inv.json().get('message', '').lower())

        # 3. Valid transition succeeds and creates TicketAuditLog
        resp_valid = self.client.post(
            reverse('update_ticket_ajax', kwargs={'ticket_id': self.ticket.id}),
            data=json.dumps({'status': 'UNDER_REVIEW'}),
            content_type='application/json'
        )
        self.assertEqual(resp_valid.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'UNDER_REVIEW')
        self.assertTrue(TicketAuditLog.objects.filter(ticket=self.ticket, action='Status Changed').exists())



class Phase2FunctionalImprovementTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="Phase 2 Test School",
            school_id="SCH-9999",
            password="pbkdf2_sha256$870000$test$hashedpassword"
        )
        self.school.set_password("CorrectOldPass123!")
        self.school.save()

        self.admin = User.objects.create_user(
            username='admin_p2',
            email='admin_p2@deped.gov.ph',
            password='Password123!',
            role='ADMIN',
            is_staff=True,
            is_superuser=True
        )
        self.agent1 = User.objects.create_user(
            username='agent1_p2',
            email='agent1_p2@deped.gov.ph',
            password='Password123!',
            first_name='Agent',
            last_name='One',
            role='MEMBER',
            total_tasks_done=5
        )
        self.agent2 = User.objects.create_user(
            username='agent2_p2',
            email='agent2_p2@deped.gov.ph',
            password='Password123!',
            first_name='Agent',
            last_name='Two',
            role='MEMBER',
            total_tasks_done=3
        )
        self.ticket = Ticket.objects.create(
            ticket_number='TKT-P2-001',
            school_name=self.school.name,
            support_type='SOFTWARE',
            description='Test Phase 2 ticket',
            status='SCHEDULED',
            assignee=self.agent1,
            admin_notes='Assigned to: Agent One'
        )

    def test_acknowledge_ticket_success(self):
        self.client.force_login(self.agent1)
        resp = self.client.post(
            reverse('acknowledge_ticket', kwargs={'ticket_id': self.ticket.id}),
            {'ack_note_type': 'For checking', 'ack_notes': 'Checking local switch'}
        )
        self.assertRedirects(resp, reverse('employee_ticket_review', kwargs={'ticket_id': self.ticket.id}))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'IN_PROGRESS')
        self.assertIn('Acknowledged - For checking: Checking local switch', self.ticket.admin_notes)
        self.assertTrue(TicketAuditLog.objects.filter(ticket=self.ticket, action='Ticket Acknowledged').exists())

    def test_acknowledge_ticket_unauthorized(self):
        self.client.force_login(self.agent2)
        resp = self.client.post(
            reverse('acknowledge_ticket', kwargs={'ticket_id': self.ticket.id}),
            {'ack_note_type': 'For checking'}
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'SCHEDULED')
        self.assertFalse(TicketAuditLog.objects.filter(ticket=self.ticket, action='Ticket Acknowledged').exists())

    def test_transfer_ticket_success_and_preserves_total_tasks_done(self):
        self.client.force_login(self.agent1)
        resp = self.client.post(
            reverse('transfer_ticket', kwargs={'ticket_id': self.ticket.id}),
            {
                'target_agent_id': self.agent2.id,
                'transfer_reason': 'Rebalancing network maintenance load'
            }
        )
        self.assertRedirects(resp, reverse('my_tickets'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.agent2)
        self.assertIn('Assigned to: Agent Two', self.ticket.admin_notes)
        self.assertIn('Rebalancing network maintenance load', self.ticket.admin_notes)

        # Check total_tasks_done is NOT modified
        self.agent1.refresh_from_db()
        self.agent2.refresh_from_db()
        self.assertEqual(self.agent1.total_tasks_done, 5)
        self.assertEqual(self.agent2.total_tasks_done, 3)

        # Check audit log
        audit = TicketAuditLog.objects.filter(ticket=self.ticket, action='Ticket Transferred').first()
        self.assertIsNotNone(audit)
        self.assertIn('Agent One', audit.old_value)
        self.assertIn('Agent Two', audit.new_value)

    def test_transfer_ticket_to_superuser_blocked(self):
        self.client.force_login(self.agent1)
        admin_user = User.objects.create_superuser('admin_target', 'adm@example.com', 'adminpass', role='ADMIN')
        resp = self.client.post(
            reverse('transfer_ticket', kwargs={'ticket_id': self.ticket.id}),
            {'target_agent_id': admin_user.id, 'transfer_reason': 'Invalid transfer to admin'}
        )
        self.assertEqual(resp.status_code, 404)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.agent1)

    def test_transfer_ticket_by_admin_redirects_to_documents(self):
        admin_user = User.objects.create_superuser('admin_exec', 'exec@example.com', 'adminpass', role='ADMIN')
        self.client.force_login(admin_user)
        resp = self.client.post(
            reverse('transfer_ticket', kwargs={'ticket_id': self.ticket.id}),
            {
                'target_agent_id': self.agent2.id,
                'transfer_reason': 'Admin reassigning ticket'
            }
        )
        self.assertRedirects(resp, reverse('documents'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.agent2)

    def test_transfer_ticket_completed_blocked(self):
        self.client.force_login(self.agent1)
        self.ticket.status = 'COMPLETED'
        self.ticket.save()

        resp = self.client.post(
            reverse('transfer_ticket', kwargs={'ticket_id': self.ticket.id}),
            {'target_agent_id': self.agent2.id, 'transfer_reason': 'Too late'}
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.agent1)

    def test_school_change_password_flow(self):
        # 1. Unauthenticated redirects to school_login
        resp_unauth = self.client.post(reverse('school_change_password'), {
            'current_password': 'CorrectOldPass123!',
            'new_password': 'BrandNewPass888!',
            'confirm_password': 'BrandNewPass888!'
        })
        self.assertRedirects(resp_unauth, reverse('school_login'))

        # 2. Authenticated school session
        session = self.client.session
        session['is_school_authenticated'] = True
        session['school_name'] = self.school.name
        session.save()

        # Wrong current password fails
        resp_wrong = self.client.post(reverse('school_change_password'), {
            'current_password': 'WrongPassword!',
            'new_password': 'BrandNewPass888!',
            'confirm_password': 'BrandNewPass888!'
        })
        self.assertRedirects(resp_wrong, reverse('school_dashboard'))
        self.school.refresh_from_db()
        self.assertTrue(self.school.check_password('CorrectOldPass123!'))

        # Password mismatch fails
        resp_mismatch = self.client.post(reverse('school_change_password'), {
            'current_password': 'CorrectOldPass123!',
            'new_password': 'BrandNewPass888!',
            'confirm_password': 'DifferentPass888!'
        })
        self.assertRedirects(resp_mismatch, reverse('school_dashboard'))
        self.school.refresh_from_db()
        self.assertTrue(self.school.check_password('CorrectOldPass123!'))

        # Correct flow succeeds
        resp_success = self.client.post(reverse('school_change_password'), {
            'current_password': 'CorrectOldPass123!',
            'new_password': 'BrandNewPass888!',
            'confirm_password': 'BrandNewPass888!'
        })
        self.assertRedirects(resp_success, reverse('school_dashboard'))
        self.school.refresh_from_db()
        self.assertTrue(self.school.check_password('BrandNewPass888!'))

    def test_settings_update_notifications(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('settings'), {
            'action': 'update_notifications',
            'email_notifications': '1'
        })
        self.assertRedirects(resp, reverse('settings'))
        settings_obj = UserSettings.objects.get(user=self.admin)
        self.assertTrue(settings_obj.email_notifications)


class Phase3PerformanceAndUsabilityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_p3',
            email='admin_p3@deped.gov.ph',
            password='Password123!',
            role='ADMIN',
            is_staff=True,
            is_superuser=True
        )
        self.school = School.objects.create(
            name="Phase 3 Test School",
            school_id="SCH-P3-001"
        )
        # Create 30 completed tickets to test pagination (25 items/page)
        tickets = []
        for i in range(30):
            tickets.append(Ticket(
                ticket_number=f'TKT-P3-{i:03d}',
                school_name=self.school.name,
                support_type='SOFTWARE',
                description=f'Test completed ticket {i}',
                status='COMPLETED'
            ))
        Ticket.objects.bulk_create(tickets)

    def test_documents_pagination_25_rows_per_page(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('documents'))
        self.assertEqual(resp.status_code, 200)

        completed_tickets = resp.context['completed_tickets']
        self.assertEqual(len(completed_tickets), 25)
        self.assertTrue(resp.context['is_paginated'])
        self.assertGreaterEqual(resp.context['paginator'].count, 30)

        # Page 2 has the remaining 5
        resp_p2 = self.client.get(f"{reverse('documents')}?page=2")
        self.assertEqual(resp_p2.status_code, 200)
        completed_p2 = resp_p2.context['completed_tickets']
        self.assertEqual(len(completed_p2), 5)

    def test_documents_search_and_pagination(self):
        self.client.force_login(self.admin)
        # Create a uniquely searchable completed ticket
        unique_ticket = Ticket.objects.create(
            ticket_number='TKT-UNIQUE-999',
            school_name='Unique Elementary School',
            support_type='HARDWARE',
            description='Unique specialized hardware issue',
            status='COMPLETED'
        )

        resp = self.client.get(f"{reverse('documents')}?search=Unique")
        self.assertEqual(resp.status_code, 200)
        completed_tickets = resp.context['completed_tickets']
        self.assertEqual(len(completed_tickets), 1)
        self.assertEqual(completed_tickets[0].ticket_number, 'TKT-UNIQUE-999')

    def test_contact_number_validation_c1_7_r3_6(self):
        from .forms import validate_ph_mobile
        from django.core.exceptions import ValidationError

        # Valid 11-digit numbers starting with 09 pass
        self.assertEqual(validate_ph_mobile('09123456789'), '09123456789')
        self.assertEqual(validate_ph_mobile(' 09987654321 '), '09987654321')

        # Invalid prefixes or lengths raise ValidationError
        with self.assertRaises(ValidationError):
            validate_ph_mobile('08123456789')  # Non-09 prefix

        with self.assertRaises(ValidationError):
            validate_ph_mobile('0912345678')  # 10 digits

        with self.assertRaises(ValidationError):
            validate_ph_mobile('091234567890')  # 12 digits

        with self.assertRaises(ValidationError):
            validate_ph_mobile('0912345ABCD')  # Non-numeric
