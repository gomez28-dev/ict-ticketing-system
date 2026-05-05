import os

files_to_update = {
    'tickets/templates/tickets/login.html': [
        (
            '                <div class="w-8 h-8 bg-white/5 border border-dashed border-white/20 rounded flex items-center justify-center">\n                <img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-10 w-auto object-contain">\n                </div>',
            '                <img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-10 w-auto object-contain">'
        )
    ],
    'tickets/templates/tickets/forgot_password.html': [
        (
            '<div style="width: 40px; height: 40px; background-color: rgba(255,255,255,0.1); border: 1px dashed rgba(255,255,255,0.3); border-radius: 4px; display: flex; align-items: center; justify-content: center;">\n                    <span style="font-size: 8px; font-weight: bold; color: white; text-transform: uppercase; letter-spacing: 2px;">Logo</span>\n                </div>',
            '<img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-10 w-auto object-contain">'
        )
    ],
    'tickets/templates/tickets/verify_otp.html': [
        (
            '<div style="width: 40px; height: 40px; background-color: rgba(255,255,255,0.1); border: 1px dashed rgba(255,255,255,0.3); border-radius: 4px; display: flex; align-items: center; justify-content: center;">\n                    <span style="font-size: 8px; font-weight: bold; color: white; text-transform: uppercase; letter-spacing: 2px;">Logo</span>\n                </div>',
            '<img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-10 w-auto object-contain">'
        )
    ],
    'tickets/templates/tickets/reset_password_confirm.html': [
        (
            '<div style="width: 40px; height: 40px; background-color: rgba(255,255,255,0.1); border: 1px dashed rgba(255,255,255,0.3); border-radius: 4px; display: flex; align-items: center; justify-content: center;">\n                    <span style="font-size: 8px; font-weight: bold; color: white; text-transform: uppercase; letter-spacing: 2px;">Logo</span>\n                </div>',
            '<img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-10 w-auto object-contain">'
        )
    ],
    'tickets/templates/tickets/request_access.html': [
        (
            '<div style="width: 40px; height: 40px; background-color: rgba(255,255,255,0.1); border: 1px dashed rgba(255,255,255,0.3); border-radius: 4px; display: flex; align-items: center; justify-content: center;">\n                    <span style="font-size: 8px; font-weight: bold; color: white; text-transform: uppercase; letter-spacing: 2px;">Logo</span>\n                </div>',
            '<img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-10 w-auto object-contain">'
        )
    ],
    'tickets/templates/tickets/school_dashboard.html': [
        (
            '<div class="w-10 h-10 bg-white/20 rounded flex items-center justify-center font-bold text-white uppercase text-xs">LOGO</div>',
            '<img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-10 w-auto object-contain">'
        )
    ],
    'tickets/templates/tickets/employee_receipt.html': [
        (
            '                <header class="border-b border-slate-900 pb-4 text-center print:border-black">\n                    <p class="text-xs font-semibold uppercase tracking-[0.2em]">Republic of the Philippines</p>',
            '                <header class="border-b border-slate-900 pb-4 flex items-center print:border-black">\n                    <div class="mr-4">\n                        <img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-14 w-auto object-contain">\n                    </div>\n                    <div class="flex-1 text-center pr-14">\n                        <p class="text-xs font-semibold uppercase tracking-[0.2em]">Republic of the Philippines</p>'
        ),
        (
            '                    <h1 class="mt-4 text-xl font-extrabold uppercase tracking-[0.18em]">Job Request Form (JRF)</h1>\n                </header>',
            '                    <h1 class="mt-4 text-xl font-extrabold uppercase tracking-[0.18em]">Job Request Form (JRF)</h1>\n                    </div>\n                </header>'
        )
    ],
    'tickets/templates/tickets/school_print_ticket.html': [
        (
            '                <header class="border-b border-slate-900 pb-4 text-center print:border-black">\n                    <p class="text-xs font-semibold uppercase tracking-[0.2em]">Schools Division Office Valenzuela</p>',
            '                <header class="border-b border-slate-900 pb-4 flex items-center print:border-black">\n                    <div class="mr-4">\n                        <img src="{% static \'tickets/images/ICT_Helpdesk_Logo.jpeg\' %}" alt="ICT Helpdesk Logo" class="h-14 w-auto object-contain">\n                    </div>\n                    <div class="flex-1 text-center pr-14">\n                        <p class="text-xs font-semibold uppercase tracking-[0.2em]">Schools Division Office Valenzuela</p>'
        ),
        (
            '                    <h1 class="mt-4 text-xl font-extrabold uppercase tracking-[0.18em]">Proof of Request</h1>\n                </header>',
            '                    <h1 class="mt-4 text-xl font-extrabold uppercase tracking-[0.18em]">Proof of Request</h1>\n                    </div>\n                </header>'
        )
    ]
}

for filepath, replacements in files_to_update.items():
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        continue
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    for old, new in replacements:
        # replace CRLF with LF to normalize
        content = content.replace(old.replace('\n', '\r\n'), new.replace('\n', '\r\n'))
        # in case file has only LF
        content = content.replace(old, new)
        
    if '{% load static %}' not in content:
        content = '{% load static %}\n' + content

    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {filepath}")
    else:
        print(f"No changes for {filepath}")
