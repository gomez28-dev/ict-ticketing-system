document.addEventListener('DOMContentLoaded', () => {
    const isAdminUser = window.DashboardData.isAdminUser;

    const getCookie = (name) => {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    };

    const moveCardToIndex = (itemEl, parentEl, index) => {
        const referenceNode = parentEl.children[index] || null;
        parentEl.insertBefore(itemEl, referenceNode);
    };

    // --- 1. INITIALIZE CHART ---
    const ctx = document.getElementById('activityChart');
    if (ctx) {
        new Chart(ctx.getContext('2d'), {
            type: 'line',
            data: {
                labels: window.DashboardData.chartLabels,
                datasets: [{
                    label: 'Tickets Received',
                    data: window.DashboardData.chartReceived,
                    borderColor: 'rgba(78, 115, 223, 1)',
                    backgroundColor: 'rgba(78, 115, 223, 0.05)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true
                }, {
                    label: 'Tickets Resolved',
                    data: window.DashboardData.chartResolved,
                    borderColor: 'rgba(28, 200, 138, 1)',
                    backgroundColor: 'rgba(28, 200, 138, 0.05)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true
                }]
            },
            options: {
                maintainAspectRatio: false,
                responsive: true,
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    // --- 2. MODAL LOGIC ---
    const cards = document.querySelectorAll('.ticket-card');
    const modal = document.getElementById('ticketModal');
    const closeBtns = [document.getElementById('closeModalBtn'), document.getElementById('cancelModalBtn')];
    const saveBtn = document.getElementById('saveModalBtn');
    let currentTicketId = null;
    let currentCardElement = null;
    let pendingReviewMove = null;

    const reviewModal = document.getElementById('reviewSubmissionModal');
    const reviewForm = document.getElementById('reviewSubmissionForm');
    const reviewError = document.getElementById('reviewSubmissionError');
    const reviewTicketNumber = document.getElementById('reviewSubmissionTicketNumber');
    const submitReviewBtn = document.getElementById('submitReviewModalBtn');

    const closeTicketModal = () => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        saveBtn.disabled = false;
        saveBtn.classList.remove('opacity-50');
        saveBtn.innerText = 'Save Changes';
        currentTicketId = null;
        currentCardElement = null;
    };

    const openReviewModal = ({ ticketId, ticketNumber, itemEl = null, targetZone = null }) => {
        pendingReviewMove = {
            ticketId,
            itemEl,
            targetZone: targetZone || document.querySelector('.kanban-zone[data-status="UNDER_REVIEW"]')
        };
        reviewTicketNumber.innerText = ticketNumber || 'Ticket';
        reviewForm.setAttribute('action', `/admin-dashboard/my-tickets/submit-review/${ticketId}/`);
        reviewForm.reset();
        reviewError.innerText = '';
        reviewError.classList.add('hidden');
        reviewModal.classList.remove('hidden');
        reviewModal.classList.add('flex');
    };

    const closeReviewModal = () => {
        pendingReviewMove = null;
        reviewForm.reset();
        reviewError.innerText = '';
        reviewError.classList.add('hidden');
        reviewModal.classList.add('hidden');
        reviewModal.classList.remove('flex');
    };

    cards.forEach(card => {
        card.addEventListener('click', () => {
            currentTicketId = card.getAttribute('data-id');
            currentCardElement = card;
            const currentStatus = card.getAttribute('data-status');

            document.getElementById('modalTicketNumber').innerText = card.getAttribute('data-number');
            document.getElementById('modalStatusBadge').innerText = currentStatus.replace('_', ' ');
            document.getElementById('modalPriorityBadge').innerText = card.getAttribute('data-priority');
            document.getElementById('modalPredictionBadge').innerHTML = `🤖 Est: ${card.getAttribute('data-predicted')}h`;
            document.getElementById('modalRequester').innerText = card.getAttribute('data-requester');
            document.getElementById('modalEmail').innerText = card.getAttribute('data-email');
            document.getElementById('modalContact').innerText = card.getAttribute('data-contact');
            document.getElementById('modalSchool').innerText = card.getAttribute('data-school');
            document.getElementById('modalSupportType').innerText = card.getAttribute('data-support-type');
            document.getElementById('modalDescription').innerText = card.getAttribute('data-description');
            const attachmentUrl = card.getAttribute('data-attachment-url');
            const attachmentWrap = document.getElementById('modalAttachmentWrap');
            const attachmentLink = document.getElementById('modalAttachmentLink');
            if (attachmentUrl) {
                attachmentLink.setAttribute('href', attachmentUrl);
                attachmentWrap.classList.remove('hidden');
            } else {
                attachmentLink.setAttribute('href', '#');
                attachmentWrap.classList.add('hidden');
            }
            const resolutionNotes = card.getAttribute('data-resolution-notes');
            const resolutionAttachmentUrl = card.getAttribute('data-resolution-attachment-url');
            const resolutionWrap = document.getElementById('modalResolutionWrap');
            const resolutionNotesEl = document.getElementById('modalResolutionNotes');
            const resolutionAttachmentLink = document.getElementById('modalResolutionAttachmentLink');
            if (['UNDER_REVIEW', 'RESOLVED', 'COMPLETED'].includes(currentStatus) || resolutionNotes || resolutionAttachmentUrl) {
                resolutionNotesEl.innerText = resolutionNotes || 'No resolution notes were submitted.';
                if (resolutionAttachmentUrl) {
                    resolutionAttachmentLink.setAttribute('href', resolutionAttachmentUrl);
                    resolutionAttachmentLink.classList.remove('hidden');
                } else {
                    resolutionAttachmentLink.setAttribute('href', '#');
                    resolutionAttachmentLink.classList.add('hidden');
                }
                resolutionWrap.classList.remove('hidden');
            } else {
                resolutionNotesEl.innerText = '';
                resolutionAttachmentLink.setAttribute('href', '#');
                resolutionAttachmentLink.classList.add('hidden');
                resolutionWrap.classList.add('hidden');
            }
            const adminNotesField = document.getElementById('modalAdminNotes');
            if (adminNotesField) {
                adminNotesField.value = card.getAttribute('data-notes');
            }
            document.getElementById('modalCreatedDate').innerText = card.getAttribute('data-created');
            document.getElementById('modalUpdatedDate').innerText = card.getAttribute('data-updated');
            document.getElementById('modalStatusSelect').value = currentStatus;
            const prioritySelect = document.getElementById('modalPrioritySelect');
            if (prioritySelect) {
                prioritySelect.value = card.getAttribute('data-priority');
            }
            saveBtn.disabled = !isAdminUser && currentStatus === 'RESOLVED';
            saveBtn.classList.toggle('opacity-50', saveBtn.disabled);

            modal.classList.remove('hidden');
            modal.classList.add('flex');
        });
    });

    closeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            closeTicketModal();
        });
    });

    document.getElementById('closeReviewModalBtn').addEventListener('click', closeReviewModal);
    document.getElementById('cancelReviewModalBtn').addEventListener('click', closeReviewModal);

    saveBtn.addEventListener('click', () => {
        if (!currentTicketId) return;

        const newStatus = document.getElementById('modalStatusSelect').value;
        const currentStatus = currentCardElement ? currentCardElement.getAttribute('data-status') : null;

        if (!isAdminUser && newStatus === 'UNDER_REVIEW') {
            closeTicketModal();
            if (currentStatus !== 'UNDER_REVIEW') {
                openReviewModal({
                    ticketId: currentTicketId,
                    ticketNumber: currentCardElement ? currentCardElement.getAttribute('data-number') : '',
                    itemEl: currentCardElement,
                    targetZone: document.querySelector('.kanban-zone[data-status="UNDER_REVIEW"]')
                });
            }
            return;
        }

        const payload = { status: newStatus };
        const prioritySelect = document.getElementById('modalPrioritySelect');
        const adminNotesField = document.getElementById('modalAdminNotes');
        if (prioritySelect) {
            payload.priority = prioritySelect.value;
        }
        if (adminNotesField) {
            payload.admin_notes = adminNotesField.value;
        }

        saveBtn.innerText = "Saving...";
        saveBtn.disabled = true;

        fetch(`/admin-dashboard/ticket/update/${currentTicketId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.location.reload();
            } else {
                alert("Error saving ticket: " + data.message);
                saveBtn.innerText = "Save Changes";
                saveBtn.disabled = false;
                saveBtn.classList.remove('opacity-50');
            }
        });
    });

    reviewForm.addEventListener('submit', (event) => {
        event.preventDefault();

        if (!pendingReviewMove) {
            closeReviewModal();
            return;
        }

        reviewError.innerText = '';
        reviewError.classList.add('hidden');
        submitReviewBtn.disabled = true;
        submitReviewBtn.innerText = 'Submitting...';

        const formData = new FormData(reviewForm);
        fetch(reviewForm.getAttribute('action'), {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: formData
        })
        .then(async (response) => {
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || 'Unable to submit ticket for review.');
            }
            return data;
        })
        .then(data => {
            const cardEl = pendingReviewMove.itemEl || document.querySelector(`.ticket-card[data-id="${pendingReviewMove.ticketId}"]`);
            const targetZone = pendingReviewMove.targetZone || document.querySelector('.kanban-zone[data-status="UNDER_REVIEW"]');
            if (cardEl && targetZone) {
                targetZone.appendChild(cardEl);
                cardEl.setAttribute('data-status', data.ticket.status);
                cardEl.setAttribute('data-resolution-notes', data.ticket.resolution_notes || '');
                cardEl.setAttribute('data-resolution-attachment-url', data.ticket.resolution_attachment_url || '');
            }
            closeReviewModal();
            window.location.reload();
        })
        .catch(error => {
            reviewError.innerText = error.message;
            reviewError.classList.remove('hidden');
        })
        .finally(() => {
            submitReviewBtn.disabled = false;
            submitReviewBtn.innerText = 'Submit for Review';
        });
    });

    // --- 3. KANBAN SORTABLE LOGIC ---
    const kanbanZones = document.querySelectorAll('.kanban-zone');
    kanbanZones.forEach(zone => {
        new Sortable(zone, {
            group: {
                name: 'kanban',
                put: function(to) {
                    if (isAdminUser) {
                        return true;
                    }
                    return to.el.getAttribute('data-status') !== 'RESOLVED';
                }
            },
            animation: 150,
            ghostClass: 'opacity-50',
            onEnd: function (evt) {
                const itemEl = evt.item;
                const ticketId = itemEl.getAttribute('data-id');
                const newStatus = evt.to.getAttribute('data-status');
                
                if (evt.from !== evt.to) {
                    if (!isAdminUser && newStatus === 'UNDER_REVIEW') {
                        moveCardToIndex(itemEl, evt.from, evt.oldIndex);
                        openReviewModal({
                            ticketId,
                            ticketNumber: itemEl.getAttribute('data-number'),
                            itemEl,
                            targetZone: evt.to
                        });
                        return;
                    }

                    fetch(`/admin-dashboard/ticket/update/${ticketId}/`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            status: newStatus
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (!data.success) {
                            alert("Error updating ticket status: " + data.message);
                            moveCardToIndex(itemEl, evt.from, evt.oldIndex);
                        } else {
                            itemEl.setAttribute('data-status', newStatus);
                        }
                    });
                }
            }
        });
    });
});
