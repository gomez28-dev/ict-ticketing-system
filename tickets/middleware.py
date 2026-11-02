from django.shortcuts import redirect
from django.urls import reverse, NoReverseMatch


class ForcePasswordChangeMiddleware:
    """
    Blocks authenticated staff users who have not changed their default
    password (flagged in session during login) from accessing protected views
    until they complete password change.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.session.get('force_password_change'):
            try:
                exempt_paths = [
                    reverse('change_password'),
                    reverse('dismiss_password_change'),
                    reverse('logout'),
                ]
            except NoReverseMatch:
                exempt_paths = []

            path = request.path
            is_exempt = path in exempt_paths or path.startswith('/static/') or path.startswith('/media/')
            if not is_exempt:
                return redirect('change_password')

        return self.get_response(request)

