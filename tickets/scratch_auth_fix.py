import os

files = [
    'tickets/templates/tickets/forgot_password.html',
    'tickets/templates/tickets/verify_otp.html',
    'tickets/templates/tickets/reset_password_confirm.html',
    'tickets/templates/tickets/request_access.html'
]

css_to_add = "        .auth-logo { max-height: 96px; width: auto; max-width: 200px; object-fit: contain; margin: 0 auto 24px auto; display: block; }\n"
logo_tag = '            <img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="auth-logo">\n'

for fpath in files:
    if not os.path.exists(fpath):
        continue
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Task 1: Add CSS
    if '.auth-logo {' not in content:
        if '</style>' in content:
            content = content.replace('</style>', css_to_add + '    </style>')
        else:
            # Should not happen based on view_file
            pass
            
    # Task 2: Add/Apply auth-logo to main logo in form-container
    if 'class="auth-logo"' not in content:
        if '<div class="form-container">' in content:
            content = content.replace('<div class="form-container">', '<div class="form-container">\n' + logo_tag)
        elif '<div class="form-container">' in content:
             # handle possible whitespace variations if any
             pass

    # Task 3: Fix footer logos
    content = content.replace('class="h-10 w-auto object-contain"', 'style="height: 40px; width: auto; object-fit: contain;"')

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)
