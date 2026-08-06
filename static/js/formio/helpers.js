// Utility functions for working with Formio
export function getFormSchema(formData) {
    if (typeof formData === 'string') {
        try {
            return JSON.parse(formData);
        } catch (e) {
            return { components: [] };
        }
    }
    return formData || { components: [] };
}

export function getFormData(submission) {
    return submission?.data || {};
}

export function formatSubmissionForDisplay(submission, schema) {
    // Helper to format submission data with labels
    // ... implementation
}