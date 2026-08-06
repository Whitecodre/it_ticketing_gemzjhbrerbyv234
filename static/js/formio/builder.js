// Formio Builder - for admin form creation
import { FormBuilder } from 'formiojs';
import 'formiojs/dist/formio.full.min.css';

// Make it globally available
window.FormBuilder = FormBuilder;
window.Formio = window.Formio || {};

console.log('✅ Formio Builder loaded');