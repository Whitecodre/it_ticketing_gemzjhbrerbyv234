# apps/knowledge_base/forms.py

from django import forms
from django.core.exceptions import ValidationError
from .models import Article
from apps.common.models import Category, Tag


FIELD_CLASS = 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2'


class ArticleMetadataForm(forms.ModelForm):
    """Step 1 of the article wizard: title/category/visibility/tags only.
    Content is handled separately by the TipTap-based content step."""

    tags_input = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': FIELD_CLASS,
            'placeholder': 'Enter tags separated by commas (e.g., "network, vpn, troubleshooting")',
            'list': 'tag-suggestions',
            'autocomplete': 'off',
        }),
        label="Tags",
        help_text="Enter comma-separated tags. Existing tags will be suggested.",
    )

    class Meta:
        model = Article
        # ⚠️ IMPORTANT: tags_input is NOT in fields - it's a custom field
        fields = ['title', 'category', 'visibility']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': FIELD_CLASS,
                'placeholder': 'Enter article title...',
            }),
            'category': forms.Select(attrs={'class': FIELD_CLASS}),
            'visibility': forms.Select(attrs={'class': FIELD_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.fields['category'].empty_label = "-- Select Category --"

        # If editing, pre-populate tags_input with existing tags
        if self.instance and self.instance.pk:
            existing_tags = self.instance.tags.all().values_list('name', flat=True)
            self.fields['tags_input'].initial = ', '.join(existing_tags)

    def clean_tags_input(self):
        """Parse comma-separated tags and return a list of clean tag names."""
        raw = self.cleaned_data.get('tags_input', '').strip()
        if not raw:
            return []
        tags = [t.strip() for t in raw.split(',') if t.strip()]
        return tags

    def save(self, commit=True):
        article = super().save(commit=commit)
        if commit and self.cleaned_data.get('tags_input') is not None:
            tag_names = self.cleaned_data['tags_input']
            tag_objects = [Tag.objects.get_or_create(name=name)[0] for name in tag_names]
            article.tags.set(tag_objects)
        return article


class KBFromTicketForm(forms.Form):
    """Metadata-only step for creating a KB article from a ticket — content
    isn't written here; Save creates a DRAFT article and hands off to the
    same TipTap editor (kb:edit_content) every other article uses, seeded
    with a scaffold built from the ticket (see convert_ticket_to_kb)."""

    title = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
            'placeholder': 'Enter article title...',
        })
    )

    # Initial = the ticket's own category, but editable — previously this
    # was silently inherited with no way to change it from this screen.
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
        })
    )

    visibility = forms.ChoiceField(
        choices=Article.Visibility.choices,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
        })
    )
    
    include_comment = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'space-y-2',
        })
    )

    def __init__(self, ticket, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ticket = ticket
        self.fields['category'].empty_label = '-- Select Category --'

        # Populate comment choices
        comments = ticket.comments.filter(visibility='PUBLIC').order_by('created_at')
        choices = []
        for comment in comments:
            choices.append((
                str(comment.pk),
                f"{comment.author.get_full_name()} - {comment.created_at.strftime('%b %d, %Y %H:%M')}: {comment.body[:80]}..."
            ))
        self.fields['include_comment'].choices = choices
        self.fields['include_comment'].initial = [str(c.pk) for c in comments]