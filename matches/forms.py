from django import forms
from .models import Block
from .models import Match, Stadium


class BlockForm(forms.ModelForm):
    class Meta:
        model = Block
        fields = ['name', 'order', 'zone_type', 'price', 'is_vip', 'is_class1', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
            'zone_type': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_vip': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_class1': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MatchForm(forms.ModelForm):
    class Meta:
        model = Match
        fields = [
            'sport_type',
            'home_team', 'away_team',
            'home_team_logo', 'away_team_logo',
            'stadium', 'date_time', 'is_active'
        ]
        widgets = {
            'sport_type': forms.Select(attrs={'class': 'form-select'}),
            'home_team': forms.TextInput(attrs={'class': 'form-control'}),
            'away_team': forms.TextInput(attrs={'class': 'form-control'}),
            'home_team_logo': forms.FileInput(attrs={'class': 'form-control'}),
            'away_team_logo': forms.FileInput(attrs={'class': 'form-control'}),
            'stadium': forms.Select(attrs={'class': 'form-select'}),
            'date_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


from django import forms
from .models import Stadium


# matches/forms.py
class StadiumForm(forms.ModelForm):
    class Meta:
        model = Stadium
        fields = ['name', 'capacity', 'image']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'image': 'تصویر ورزشگاه',
        }
