# apps/knowledge_base/forms.py

from django import forms
from django.core.exceptions import ValidationError
from .models import Article
from .widgets import KBTinyMCEWidget
from apps.common.models import Category, Tag


class ArticleForm(forms.ModelForm):
    content = forms.CharField(
        widget=KBTinyMCEWidget(),
        label="Content",
        required=True
    )
    
    tags_input = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
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
        fields = ['title', 'category', 'visibility', 'content']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
                'placeholder': 'Enter article title...',
            }),
            'category': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
            }),
            'visibility': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
            }),
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
        """
        Save the article, then handle tags separately.
        This ensures the article exists in the database before setting tags.
        """
        # Get the article instance (unsaved)
        article = super().save(commit=False)
        
        # ================================================================
        # STEP 1: Save the article to the database FIRST
        # ================================================================
        if commit:
            article.save()  # ✅ Article now has an ID
            # Save many-to-many relationships (if any)
            self.save_m2m()
        else:
            # If commit=False, we still need to handle tags later
            # But we should still save the article before setting tags
            # For safety, we'll save it anyway
            article.save()
        
        # ================================================================
        # STEP 2: Handle tags (article now has an ID)
        # ================================================================
        if self.cleaned_data.get('tags_input') is not None:
            tag_names = self.cleaned_data['tags_input']
            tag_objects = []
            for name in tag_names:
                tag, created = Tag.objects.get_or_create(name=name)
                tag_objects.append(tag)
            # ✅ Set the tags (article has an ID now)
            article.tags.set(tag_objects)
        
        # ================================================================
        # STEP 3: Save again if commit is True (to persist changes)
        # ================================================================
        if commit:
            article.save()
        
        return article


class KBFromTicketForm(forms.Form):
    """Form for creating a KB article from a ticket (wizard)."""

    title = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2',
            'placeholder': 'Enter article title...',
        })
    )
    
    content = forms.CharField(
        widget=KBTinyMCEWidget(),
        required=True,
        label="Article Content",
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