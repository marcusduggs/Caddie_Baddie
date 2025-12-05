
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
    template_name = 'signup.html'
    success_url = reverse_lazy('login')

def login_view(request):
    if request.method == "POST":
        email = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            return redirect(reverse("shots:shot_list"))
        else:
            return render(request, "login.html", {"error": "Invalid login details"})
    return render(request, "login.html")

def signup_view(request):
    User = get_user_model()
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        if User.objects.filter(email=email).exists():
            return render(request, "signup.html", {"error": "Email already exists."})
        user = User.objects.create_user(email=email, password=password)
        login(request, user)
        return redirect(reverse("shots:my_shots"))
    return render(request, "signup.html")
