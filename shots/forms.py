from django import forms
from .models import Shot


class ShotForm(forms.ModelForm):
    # Allow an optional video upload to extract coords from
    video = forms.FileField(required=False)

    class Meta:
        model = Shot
        fields = ['club', 'distance', 'accuracy', 'longitude', 'latitude', 'notes']


class ShotAnalysisForm(forms.ModelForm):
    """Form to upload a video for analysis, allowing the user to provide club and distance."""
    # Club selection: present common golf clubs as a dropdown for convenience.
    CLUB_CHOICES = [
        ('Driver', 'Driver'),
        ('3-wood', '3-wood'),
        ('5-wood', '5-wood'),
        ('3-iron', '3-iron'),
        ('4-iron', '4-iron'),
        ('5-iron', '5-iron'),
        ('6-iron', '6-iron'),
        ('7-iron', '7-iron'),
        ('8-iron', '8-iron'),
        ('9-iron', '9-iron'),
        ('PW', 'PW'),
        ('SW', 'SW'),
        ('LW', 'LW'),
        ('Putter', 'Putter'),
        ('Other', 'Other'),
    ]

    club = forms.ChoiceField(choices=CLUB_CHOICES, required=True, label='Club')
    distance = forms.FloatField(required=True, label='Distance (yards)', widget=forms.NumberInput(attrs={'placeholder': 'e.g. 120'}))

    class Meta:
        from .models import ShotAnalysis
        model = ShotAnalysis
        fields = ['input_video', 'club', 'distance']

