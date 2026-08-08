# apps/knowledge_base/widgets.py

from django import forms
from tinymce.widgets import TinyMCE


class KBTinyMCEWidget(TinyMCE):
    """
    Custom TinyMCE widget specifically for the Knowledge Base.
    Uses mce_attrs for configuration (the correct parameter name).
    """

    def __init__(self, attrs=None, mce_attrs=None):
        # Default TinyMCE configuration
        default_mce_attrs = {
            "height": "400px",
            "menubar": True,
            "plugins": """
                advlist autolink lists link image charmap print preview anchor
                searchreplace visualblocks code fullscreen
                insertdatetime media table paste code help wordcount
                image imagetools
            """,
            "toolbar": """
                undo redo | bold italic underline strikethrough | 
                forecolor backcolor | alignleft aligncenter alignright alignjustify | 
                bullist numlist | outdent indent | 
                link image media | table | code | 
                removeformat | help
            """,
            "paste_data_images": True,
            "relative_urls": False,
            "image_advtab": True,
            "branding": False,
            "autosave_ask_before_unload": True,
            "autosave_interval": "30s",
            "autosave_prefix": "kb-autosave",
        }

        # Merge any custom config passed in
        if mce_attrs:
            default_mce_attrs.update(mce_attrs)

        # Call parent with the correct parameter name
        super().__init__(attrs=attrs, mce_attrs=default_mce_attrs)