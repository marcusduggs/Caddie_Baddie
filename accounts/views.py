
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView
from .forms import CustomUserCreationForm
from .models import CustomUser
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.urls import reverse

class SignUpView(CreateView):
    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = 'accounts/signup.html'
    success_url = reverse_lazy('login')

def login_view(request):
    from .forms import EmailAuthenticationForm
    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect(reverse("shots:home"))
        else:
            return render(request, "accounts/login.html", {"form": form, "error": "Invalid login details"})
    else:
        form = EmailAuthenticationForm()
    return render(request, "accounts/login.html", {"form": form})

def signup_view(request):
    from .forms import CustomUserCreationForm
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(reverse("shots:home"))
        else:
            return render(request, "accounts/signup.html", {"form": form})
    else:
        form = CustomUserCreationForm()
    return render(request, "accounts/signup.html", {"form": form})
