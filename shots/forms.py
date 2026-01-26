from django import forms
from .models import Shot, ShotAnalysis


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

    club = forms.ChoiceField(choices=CLUB_CHOICES, required=False, label='Club')
    distance = forms.FloatField(required=False, label='Distance (yards)', widget=forms.NumberInput(attrs={'placeholder': 'e.g. 120'}))
    # Golf course + hole info to enrich overlays (course left editable but not labeled as optional)
    course = forms.CharField(required=False, max_length=200, label='Course', widget=forms.TextInput(attrs={'placeholder': 'Course name, e.g. Pebble Beach'}))
    hole = forms.IntegerField(required=False, min_value=1, max_value=18, label='Hole (optional)', widget=forms.NumberInput(attrs={'placeholder': 'Hole number (1-18)'}))
    # Tee selection: let user pick a tee set; default blank means 'any'
    TEE_CHOICES = [
        ('', 'Any'),
        ('Blue', 'Blue'),
        ('White', 'White'),
        ('Gold', 'Gold'),
        ('Gold Combo', 'Gold Combo'),
        ('Red', 'Red'),
        ('Green', 'Green'),
        ('Black', 'Black'),
    ]
    # Require preferred tee selection before upload so overlays and yardages are predictable
    selected_tee = forms.ChoiceField(choices=TEE_CHOICES, required=True, label='Preferred tee')

    class Meta:
        model = ShotAnalysis
        fields = ['input_video', 'club', 'distance']

