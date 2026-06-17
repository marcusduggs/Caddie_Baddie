from django.urls import reverse_lazy, reverse
from django.views.generic.edit import CreateView
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib import messages

import logging

from .forms import CustomUserCreationForm, EmailAuthenticationForm
from .models import CustomUser, EmailVerificationToken

logger = logging.getLogger(__name__)


# ── Email helper ────────────────────────────────────────────────────────────

def _send_verification_email(request, user):
    token = EmailVerificationToken.objects.create(user=user)
    verify_url = request.build_absolute_uri(
        reverse('verify_email', args=[str(token.token)])
    )
    subject = render_to_string('accounts/email/verify_email_subject.txt').strip()
    body = render_to_string('accounts/email/verify_email_body.txt', {
        'user': user,
        'verify_url': verify_url,
    })
    try:
        from django.conf import settings as _settings
        logger.info('Sending verification email to %s via backend %s', user.email, _settings.EMAIL_BACKEND)
        send_mail(subject, body, None, [user.email], fail_silently=False)
        logger.info('Verification email sent successfully to %s', user.email)
    except Exception:
        logger.exception('Failed to send verification email to %s', user.email)


# ── Auth views ──────────────────────────────────────────────────────────────

def login_view(request):
    if request.method == 'POST':
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.GET.get('next') or reverse('shots:home')
            return redirect(next_url)
        return render(request, 'accounts/login.html', {'form': form, 'error': 'Invalid login details'})
    form = EmailAuthenticationForm()
    return render(request, 'accounts/login.html', {'form': form})


def signup_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            _send_verification_email(request, user)
            return redirect(reverse('shots:home'))
        return render(request, 'accounts/signup.html', {'form': form})
    form = CustomUserCreationForm()
    return render(request, 'accounts/signup.html', {'form': form})


# ── Email verification ──────────────────────────────────────────────────────

def verify_email(request, token):
    token_obj = get_object_or_404(EmailVerificationToken, token=token)
    if not token_obj.is_valid():
        messages.error(request, 'This verification link has expired. Please request a new one.')
        return redirect('shots:home')
    user = token_obj.user
    user.email_verified = True
    user.save(update_fields=['email_verified'])
    token_obj.delete()
    messages.success(request, 'Your email has been verified. Welcome to Caddie Baddie!')
    return redirect('shots:home')


@login_required
def resend_verification(request):
    if request.method == 'POST':
        if request.user.email_verified:
            messages.info(request, 'Your email is already verified.')
        else:
            # Delete old tokens and send a fresh one
            request.user.verification_tokens.all().delete()
            _send_verification_email(request, request.user)
            messages.success(request, f'Verification email sent to {request.user.email}. Check your inbox.')
    return redirect(request.META.get('HTTP_REFERER', '/'))


# ── Legacy class-based signup (kept for url name 'signup' from SignUpView) ──

class SignUpView(CreateView):
    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = 'accounts/signup.html'
    success_url = reverse_lazy('login')
