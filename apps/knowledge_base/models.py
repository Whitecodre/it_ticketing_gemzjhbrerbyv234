from django.db import models
from django.conf import settings
from django.utils.text import slugify
from apps.common.models import Category

class Article(models.Model):
    class Visibility(models.TextChoices):
        INTERNAL = 'INTERNAL', 'Internal'
        PUBLIC = 'PUBLIC', 'Public'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PENDING_REVIEW = 'PENDING_REVIEW', 'Pending Review',
        PUBLISHED = 'PUBLISHED', 'Published'
        ARCHIVED = 'ARCHIVED', 'Archived'

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='articles')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    content = models.TextField()
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.INTERNAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    tags = models.ManyToManyField('common.Tag', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Set once, the first time an article is published — distinct from
    # updated_at, which changes on every later edit while the article stays
    # published. Not overwritten by subsequent edits.
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='published_articles',
    )

    # Set when archived, to whatever status the article was in immediately
    # before — lets Restore put it back where it came from (e.g. back to
    # Published) instead of always dumping it into Draft. Cleared on restore.
    archived_from_status = models.CharField(max_length=20, choices=Status.choices, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class ArticleVersion(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='versions')
    content = models.TextField()
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Version {self.id} of {self.article}"
    
class ArticleFeedback(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='feedback')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    helpful = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('article', 'user')